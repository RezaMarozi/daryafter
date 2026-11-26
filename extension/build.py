#!/usr/bin/env python3
"""Assemble the Daryafter browser extensions from the shared sources.

Layout:

    extension/src/            shared HTML/CSS/JS/icons
    extension/firefox/manifest.json
    extension/chrome/manifest.json

This script copies ``src/`` and the matching manifest into
``dist/extensions/<browser>/`` and writes a ZIP next to it. Both browsers
are built independently; nothing is copied by hand, so the two builds can
never drift apart.

Usage:
    python extension/build.py                 # build both + ZIPs
    python extension/build.py --check         # validate sources only
    python extension/build.py --browser firefox
    python extension/build.py --output /tmp/ext
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

EXTENSION = Path(__file__).resolve().parent
REPO = EXTENSION.parent
SRC = EXTENSION / "src"
DEFAULT_OUTPUT = REPO / "dist" / "extensions"
BROWSERS = ("firefox", "chrome")
ZIP_DATE = (2020, 1, 1, 0, 0, 0)          # reproducible archives

REQUIRED_SRC = (
    "common.js",
    "common.css",
    "background.js",
    "content.js",
    "popup.html",
    "popup.js",
    "options.html",
    "options.js",
    "icons/icon16.png",
    "icons/icon32.png",
    "icons/icon48.png",
    "icons/icon96.png",
    "icons/icon128.png",
)


class BuildError(RuntimeError):
    pass


def read_manifest(browser: str) -> dict:
    path = EXTENSION / browser / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BuildError(f"missing manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BuildError(f"invalid JSON in {path}: {exc}") from exc


def manifest_files(manifest: dict) -> list[str]:
    """Every file the manifest itself points at."""
    files: list[str] = []
    files.extend((manifest.get("icons") or {}).values())
    action = manifest.get("action") or manifest.get("browser_action") or {}
    files.extend((action.get("default_icon") or {}).values())
    if action.get("default_popup"):
        files.append(action["default_popup"])
    if (manifest.get("options_ui") or {}).get("page"):
        files.append(manifest["options_ui"]["page"])
    background = manifest.get("background") or {}
    files.extend(background.get("scripts") or [])
    if background.get("service_worker"):
        files.append(background["service_worker"])
    if background.get("page"):
        files.append(background["page"])
    for script in manifest.get("content_scripts") or []:
        files.extend(script.get("js") or [])
        files.extend(script.get("css") or [])
    return [item for item in files if item]


def validate(browser: str, manifest: dict) -> None:
    if manifest.get("manifest_version") != 3:
        raise BuildError(f"{browser}: manifest_version must be 3")
    if not manifest.get("name") or not manifest.get("version"):
        raise BuildError(f"{browser}: manifest needs name and version")

    missing = [name for name in REQUIRED_SRC if not (SRC / name).is_file()]
    if missing:
        raise BuildError(f"missing shared source files: {', '.join(missing)}")

    for name in manifest_files(manifest):
        if name.startswith(("/", "..")) or ".." in Path(name).parts:
            raise BuildError(f"{browser}: manifest points outside the extension: {name}")
        if not (SRC / name).is_file():
            raise BuildError(f"{browser}: manifest references a missing file: {name}")

    background = manifest.get("background") or {}
    if browser == "firefox":
        if not background.get("scripts"):
            raise BuildError("firefox: background.scripts is required")
        if background.get("service_worker"):
            raise BuildError("firefox: service_worker is not supported here")
        if "browser_specific_settings" not in manifest:
            raise BuildError("firefox: browser_specific_settings (gecko id) is required")
        gecko = manifest.get("browser_specific_settings", {}).get("gecko", {})
        if gecko.get("data_collection_permissions", {}).get("required") != ["none"]:
            raise BuildError("firefox: gecko.data_collection_permissions.required must be ['none']")
    else:
        if background.get("service_worker") != "background.js":
            raise BuildError("chrome: background.service_worker must be background.js")
        if background.get("scripts"):
            raise BuildError("chrome: background.scripts is not supported in MV3")
        for key in ("browser_specific_settings", "data_collection_permissions"):
            if key in manifest:
                raise BuildError(f"chrome: {key} is Firefox-only")

    for key in ("storage", "nativeMessaging"):
        if key not in (manifest.get("permissions") or []):
            raise BuildError(f"{browser}: missing permission: {key}")


def assemble(browser: str, output: Path) -> Path:
    manifest = read_manifest(browser)
    validate(browser, manifest)

    target = output / browser

    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir():
            raise BuildError(f"refusing to replace non-directory or symlink: {target}")
        shutil.rmtree(target)

    shutil.copytree(SRC, target)
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def make_zip(browser: str, folder: Path, output: Path) -> Path:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    archive = output / f"daryafter-{browser}-{manifest['version']}.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                relative = path.relative_to(folder).as_posix()
                info = zipfile.ZipInfo(relative, date_time=ZIP_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                bundle.writestr(info, path.read_bytes())
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--browser", choices=BROWSERS, action="append",
                        help="build only this browser (repeatable)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"output directory (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--check", action="store_true",
                        help="validate the sources without writing anything")
    args = parser.parse_args(argv)

    browsers = args.browser or list(BROWSERS)
    if not args.check:
        args.output.mkdir(parents=True, exist_ok=True)
    if not args.check:
        args.output.mkdir(parents=True, exist_ok=True)
    try:
        for browser in browsers:
            manifest = read_manifest(browser)
            validate(browser, manifest)
            if args.check:
                print(f"ok   {browser}: {manifest['name']} {manifest['version']}")
                continue
            folder = assemble(browser, args.output)
            archive = make_zip(browser, folder, args.output)
            print(f"built {browser}: {folder.relative_to(REPO) if folder.is_relative_to(REPO) else folder}")
            print(f"      {archive.relative_to(REPO) if archive.is_relative_to(REPO) else archive}")
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
