"""Command-line downloader built on the same engine as the GUI.

    python -m daryafter.cli URL [-o FOLDER] [-n NAME] [-c CONNECTIONS] [--limit KB/s] [--max-speed]

Asks for the file name before downloading (use -n or --yes to skip)."""
from __future__ import annotations

import argparse
import asyncio
import sys

from .core.fmt import human_size, human_speed, human_time
from .core.manager import DownloadManager
from .core.models import AddRequest, DownloadOptions, Event, State
from .core.settings import Settings
from .core.storage import Storage
from .errors_text import friendly


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="daryafter", description="Daryafter command-line downloader")
    p.add_argument("url")
    p.add_argument("-o", "--folder", default="", help="save folder (default: Downloads)")
    p.add_argument("-n", "--name", default="", help="file name (skips the question)")
    p.add_argument("-y", "--yes", action="store_true", help="accept the suggested file name")
    p.add_argument("-c", "--connections", type=int, default=8)
    p.add_argument("--limit", type=int, default=0, help="speed limit in KB/s (0 = unlimited)")
    p.add_argument("--max-speed", action="store_true", help="use up to 32 connections")
    p.add_argument("--sha256", default="", help="expected SHA-256 checksum")
    return p


async def run(argv: list[str] | None = None, transport_factory=None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings(download_dir=args.folder, auto_categorize=False)
    done = asyncio.Event()
    result: dict = {}

    def on_event(ev: Event) -> None:
        if ev.kind == "progress" and ev.snapshots:
            s = ev.snapshots[0]
            pct = f"{s.progress * 100:5.1f}%" if s.total > 0 else "  ...  "
            line = (f"\r{s.filename[:32]:32} {pct}  {human_speed(s.speed):>11}  "
                    f"ETA {human_time(s.eta)}  {s.connections} conn {s.message[:30]:30}")
            sys.stdout.write(line)
            sys.stdout.flush()
        elif ev.kind == "updated" and ev.snapshot and ev.snapshot.state in (State.COMPLETED, State.FAILED):
            result["snap"] = ev.snapshot
            done.set()

    manager = DownloadManager(Storage(None), settings, on_event, transport_factory)
    await manager.startup()
    try:
        print("Checking link...")
        probe = await manager.probe(args.url)
        print(f"  size: {human_size(probe.total_size)}   resume supported: "
              f"{'yes' if probe.resumable else 'no'}")
        name = args.name or probe.filename
        if not args.name and not args.yes and sys.stdin.isatty():
            typed = input(f"File name [{name}]: ").strip()
            name = typed or name
        options = DownloadOptions(connections=args.connections, speed_limit=args.limit * 1024,
                                  max_speed=args.max_speed, expected_hash=args.sha256,
                                  expected_hash_algo="sha256" if args.sha256 else "")
        await manager.add(AddRequest(url=args.url, filename=name, directory=args.folder,
                                     use_category_folder=False, options=options, probe=probe))
        await done.wait()
        snap = result["snap"]
        print()
        if snap.state == State.COMPLETED:
            print(f"Saved: {snap.final_path}")
            print(f"Average {human_speed(snap.avg_speed)}   max {human_speed(snap.max_speed)}   "
                  f"min {human_speed(snap.min_speed)}   time {human_time(snap.active_seconds)}")
            return 0
        print(f"Failed: {snap.error}")
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except Exception as exc:                     # noqa: BLE001 - show a readable message
        print(f"Error: {friendly(exc)}")
        return 1
    finally:
        await manager.shutdown()


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
