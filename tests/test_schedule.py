import asyncio
import tempfile
import unittest
from datetime import datetime

from daryafter.core.manager import DownloadManager
from daryafter.core.models import AddRequest, DownloadOptions, State
from daryafter.core.schedule import DISCONNECT, START, STOP, Rule, Scheduler, rules_from_settings
from daryafter.core.settings import Settings
from daryafter.core.storage import Storage

from .support import StdlibTransport, TestServer


def at(day, hour, minute, second=0):
    return datetime(2026, 10, day, hour, minute, second)     # 2026-10-22 is a Thursday


class RuleTests(unittest.TestCase):
    def test_bad_settings_are_ignored(self):
        s = Settings(schedule=[{"action": "start", "hour": 2, "minute": 30}, "junk", {"action": "boom"},
                               {"action": "stop", "hour": 25, "minute": 0},
                               {"action": "stop", "hour": "x"}, {"action": "disconnect", "hour": 1,
                                                                 "minute": 5, "days": [0, 9, "3"]}])
        rules = rules_from_settings(s)
        self.assertEqual([(r.action, r.clock_text(), r.index) for r in rules],
                         [(START, "02:30", 0), (DISCONNECT, "01:05", 5)])
        self.assertEqual(rules[1].days, [0, 3])                  # out-of-range day dropped

    def test_round_trip(self):
        r = Rule(STOP, 23, 15, [4, 5], once=True)
        back = Rule.from_dict(r.to_dict())
        self.assertEqual((back.action, back.hour, back.minute, back.days, back.once), (STOP, 23, 15, [4, 5], True))
        self.assertNotIn("index", r.to_dict())

    def test_settings_copy_keeps_rules(self):
        s = Settings(schedule=[Rule(START, 1, 0).to_dict()])
        c = s.copy()
        c.schedule[0]["hour"] = 9
        self.assertEqual(s.schedule[0]["hour"], 1)               # a copy, not shared


class SchedulerTests(unittest.TestCase):
    def test_fires_once_when_time_passes(self):
        sch = Scheduler()
        rule = Rule(START, 2, 0)
        self.assertEqual(sch.due([rule], at(22, 1, 59, 50)), [])         # first call never fires
        self.assertEqual(sch.due([rule], at(22, 1, 59, 55)), [])
        self.assertEqual(sch.due([rule], at(22, 2, 0, 3)), [rule])
        self.assertEqual(sch.due([rule], at(22, 2, 0, 8)), [])           # not twice
        self.assertEqual(sch.due([rule], at(23, 2, 0, 1)), [rule])       # next day again

    def test_days_and_enabled(self):
        sch = Scheduler()
        weekdays = Rule(STOP, 8, 0, [0, 1, 2, 3, 4])
        off = Rule(STOP, 8, 0, enabled=False)
        sch.due([weekdays, off], at(24, 7, 59, 0))                       # Saturday
        self.assertEqual(sch.due([weekdays, off], at(24, 8, 0, 5)), [])
        sch.due([weekdays, off], at(26, 7, 59, 0))                       # Monday
        self.assertEqual(sch.due([weekdays, off], at(26, 8, 0, 5)), [weekdays])

    def test_after_sleep_fires_only_if_recent(self):
        rule = Rule(START, 2, 0)
        sch = Scheduler(max_late=600)
        sch.due([rule], at(22, 1, 0))
        self.assertEqual(sch.due([rule], at(22, 2, 5)), [rule])          # woke up 5 min late: still run
        sch = Scheduler(max_late=600)
        sch.due([rule], at(22, 1, 0))
        self.assertEqual(sch.due([rule], at(22, 9, 0)), [])              # woke up hours late: skip

    def test_order_and_clock_going_back(self):
        sch = Scheduler(max_late=7200)
        a, b = Rule(STOP, 3, 0), Rule(START, 2, 0)
        sch.due([a, b], at(22, 1, 0))
        self.assertEqual(sch.due([a, b], at(22, 4, 0)), [b, a])          # in time order
        self.assertEqual(sch.due([a, b], at(22, 1, 0)), [])              # clock turned back: no fire
        self.assertEqual(sch.due([a, b], at(22, 3, 30)), [b, a])         # and it works again afterwards

    def test_next_run(self):
        sch = Scheduler()
        rules = [Rule(START, 2, 0), Rule(STOP, 23, 0, [0]), Rule(DISCONNECT, 9, 0, enabled=False)]
        when, rule = sch.next_run(rules, at(22, 10, 0))
        self.assertEqual((when, rule.action), (at(23, 2, 0), START))
        when, rule = sch.next_run(rules, at(22, 1, 0))
        self.assertEqual((when, rule.action), (at(22, 2, 0), START))
        self.assertIsNone(sch.next_run([Rule(START, 2, 0, [])], at(22, 1, 0)))


class QueueOrderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = TestServer().start()
        self.tmp = tempfile.mkdtemp()
        self.events = []
        self.m = DownloadManager(Storage(None), Settings(download_dir=self.tmp, max_concurrent=1,
                                                         prevent_sleep=False, set_file_time=False,
                                                         auto_categorize=False),
                                 self.events.append, lambda opts: StdlibTransport())
        await self.m.startup()
        self.probe = await self.m.probe(self.server.base + "/cd.bin")    # links can't be checked offline

    async def asyncTearDown(self):
        await self.m.shutdown()
        self.server.stop()

    async def add(self, name, start=True):
        return await self.m.add(AddRequest(url=self.server.base + "/cd.bin", filename=name, probe=self.probe,
                                           use_category_folder=False, options=DownloadOptions(),
                                           start_now=start))

    def order(self):
        return [i.filename for i in sorted((i for i in self.m.items.values() if i.state != State.COMPLETED),
                                           key=lambda i: (-i.priority, i.id))]

    async def test_move(self):
        ids = [await self.add(n, start=False) for n in "abcd"]
        self.assertEqual(self.order(), list("abcd"))
        await self.m.move_in_queue(ids[3], "top")
        self.assertEqual(self.order(), list("dabc"))
        await self.m.move_in_queue(ids[0], "down")
        self.assertEqual(self.order(), list("dbac"))
        await self.m.move_in_queue(ids[0], "up")
        await self.m.move_in_queue(ids[0], "up")
        await self.m.move_in_queue(ids[0], "up")                         # already first: nothing happens
        self.assertEqual(self.order(), list("adbc"))
        await self.m.move_in_queue(ids[0], "bottom")
        self.assertEqual(self.order(), list("dbca"))
        await self.m.move_in_queue(999, "top")                           # unknown id is ignored
        self.assertEqual(self.order(), list("dbca"))

    async def test_queue_order_is_the_download_order(self):
        await self.m.set_offline(True)                                   # hold everything in the queue
        ids = [await self.add(n) for n in ("first", "second", "third")]
        self.assertTrue(all(i.state == State.QUEUED for i in self.m.items.values()))
        await self.m.move_in_queue(ids[2], "top")
        await self.m.set_offline(False)
        for _ in range(400):
            if sum(1 for e in self.events if e.kind == "completed") == 3:
                break
            await asyncio.sleep(0.05)
        done = [e.snapshot.filename for e in self.events if e.kind == "completed"]
        self.assertEqual(done, ["third", "first", "second"])


class TimerOnEngineTests(unittest.IsolatedAsyncioTestCase):
    """The manager runs the rules (clock replaced by a fake one; _check_schedule is what the 0.5 s tick calls)."""

    async def asyncSetUp(self):
        self.server = TestServer().start()
        self.tmp = tempfile.mkdtemp()
        self.events = []
        self.clock = [at(22, 1, 59, 0)]
        self.settings = Settings(download_dir=self.tmp, prevent_sleep=False, set_file_time=False,
                                 auto_categorize=False)
        self.m = DownloadManager(Storage(None), self.settings, self.events.append,
                                 lambda opts: StdlibTransport(), now=lambda: self.clock[0])
        await self.m.startup()
        self.probe = await self.m.probe(self.server.base + "/cd.bin")

    async def asyncTearDown(self):
        await self.m.shutdown()
        self.server.stop()

    async def add(self, name, start):
        return await self.m.add(AddRequest(url=self.server.base + "/cd.bin", filename=name, probe=self.probe,
                                           use_category_folder=False, options=DownloadOptions(), start_now=start))

    async def pass_time(self, to):
        self.m._check_schedule()                     # look just before ...
        self.clock[0] = to
        self.m._check_schedule()                     # ... and just after the planned time
        for _ in range(100):
            await asyncio.sleep(0.05)
            if any(e.kind == "schedule" for e in self.events):
                break

    async def test_start_goes_online_and_downloads(self):
        await self.m.set_offline(True)
        item_id = await self.add("a.bin", start=False)               # waiting, not started
        self.settings.schedule = [Rule(START, 2, 0).to_dict()]
        await self.pass_time(at(22, 2, 0, 2))
        self.assertFalse(self.m.offline)
        for _ in range(200):
            if self.m.items[item_id].state == State.COMPLETED:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(self.m.items[item_id].state, State.COMPLETED)
        self.assertEqual([e.text for e in self.events if e.kind == "schedule"], ["start"])

    async def test_stop_pauses_everything_and_disconnect_goes_offline(self):
        await self.m.set_offline(True)
        item_id = await self.add("b.bin", start=True)                # queued behind offline mode
        self.assertEqual(self.m.items[item_id].state, State.QUEUED)
        self.settings.schedule = [Rule(STOP, 2, 0).to_dict()]
        await self.pass_time(at(22, 2, 0, 1))
        self.assertEqual(self.m.items[item_id].state, State.PAUSED)

        await self.m.set_offline(False)
        self.events.clear()
        self.settings.schedule = [Rule(DISCONNECT, 3, 0).to_dict()]
        await self.pass_time(at(22, 3, 0, 1))
        self.assertTrue(self.m.offline)
        self.assertEqual([e.text for e in self.events if e.kind == "schedule"], ["disconnect"])

    async def test_once_rule_switches_itself_off(self):
        self.settings.schedule = [Rule(STOP, 2, 0, once=True).to_dict(), Rule(STOP, 5, 0).to_dict()]
        await self.pass_time(at(22, 2, 0, 1))
        self.assertFalse(self.settings.schedule[0]["enabled"])
        self.assertTrue(self.settings.schedule[1]["enabled"])
        ev = next(e for e in self.events if e.kind == "schedule")
        self.assertTrue(ev.flag)

    async def test_no_rules_no_events(self):
        await self.pass_time(at(22, 2, 0, 1))
        self.assertEqual([e for e in self.events if e.kind == "schedule"], [])


if __name__ == "__main__":
    unittest.main()
