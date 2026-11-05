import os
import tempfile
import unittest

from daryafter.core.applock import AttemptLimiter, LockController, check_new_password
from daryafter.core.settings import Settings
from daryafter.core.storage import Storage


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class PasswordRuleTests(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(check_new_password("abcd", "abcd"), "")
        self.assertTrue(check_new_password("", ""))
        self.assertTrue(check_new_password("    ", "    "))
        self.assertTrue(check_new_password("abc", "abc"))
        self.assertTrue(check_new_password("abcd", "abce"))
        self.assertTrue(check_new_password("x" * 129, "x" * 129))
        self.assertEqual(check_new_password("pass word", "pass word"), "")     # spaces are fine
        self.assertEqual(check_new_password("رمز-عبور", "رمز-عبور"), "")        # non-English is fine


class LimiterTests(unittest.TestCase):
    def test_backoff(self):
        clock = FakeClock()
        lim = AttemptLimiter(clock=clock)
        for _ in range(3):
            self.assertEqual(lim.failed(), 0.0)          # three free mistakes
        self.assertEqual(lim.failed(), 5.0)
        clock.now += 5
        self.assertEqual(lim.wait_seconds(), 0.0)
        self.assertEqual(lim.failed(), 10.0)
        clock.now += 10
        self.assertEqual(lim.failed(), 20.0)
        for _ in range(30):
            lim.failed()
        self.assertEqual(lim.wait_seconds(), 300.0)       # capped
        lim.succeeded()
        self.assertEqual(lim.wait_seconds(), 0.0)
        self.assertEqual(lim.failures, 0)


class ControllerTests(unittest.TestCase):
    def make(self, minutes=0, idle=0.0):
        s = Settings(lock_after_minutes=minutes)
        s.set_password("secret")
        clock = FakeClock()
        state = {"idle": idle}
        c = LockController(s, lambda: state["idle"], AttemptLimiter(clock=clock))
        return s, c, clock, state

    def test_no_password_never_locks(self):
        c = LockController(Settings())
        self.assertFalse(c.lock())
        self.assertFalse(c.locked)

    def test_unlock_flow_and_cooldown(self):
        s, c, clock, _ = self.make()
        self.assertTrue(c.lock())
        for _ in range(3):
            r = c.try_unlock("nope")
            self.assertFalse(r.ok)
            self.assertEqual(r.wait, 0.0)
        r = c.try_unlock("nope")
        self.assertEqual((r.ok, r.wait), (False, 5.0))
        # during the cool-down even the right password is refused
        r = c.try_unlock("secret")
        self.assertFalse(r.ok)
        self.assertTrue(c.locked)
        clock.now += 5.1
        self.assertTrue(c.try_unlock("secret").ok)
        self.assertFalse(c.locked)
        c.lock()
        self.assertEqual(c.limiter.failures, 0)          # success reset the counter

    def test_inactivity(self):
        s, c, _, state = self.make(minutes=5)
        state["idle"] = 299
        self.assertFalse(c.inactivity_expired())
        state["idle"] = 300
        self.assertTrue(c.inactivity_expired())
        c.lock()
        self.assertFalse(c.inactivity_expired())         # already locked
        s2, c2, _, st2 = self.make(minutes=0, idle=99999)
        self.assertFalse(c2.inactivity_expired())        # 0 = never
        s2.set_password("")
        s2.lock_after_minutes = 1
        self.assertFalse(c2.inactivity_expired())        # no password = nothing to lock

    def test_follows_settings_changes(self):
        s, c, _, _ = self.make()
        s.set_password("")
        self.assertFalse(c.lock())


class SettingsPersistenceTests(unittest.TestCase):
    def test_lock_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.db")
            st = Storage(path)
            s = Settings(lock_after_minutes=7, lock_on_minimize=False)
            s.set_password("secret")
            s.save(st)
            st.close()
            st = Storage(path)
            loaded = Settings.load(st)
            st.close()
            self.assertTrue(loaded.lock_enabled)
            self.assertTrue(loaded.check_password("secret"))
            self.assertFalse(loaded.check_password("Secret"))
            self.assertEqual((loaded.lock_after_minutes, loaded.lock_on_minimize), (7, False))

    def test_old_database_without_new_fields(self):
        with tempfile.TemporaryDirectory() as d:
            st = Storage(os.path.join(d, "t.db"))
            st.set_setting("app_settings", '{"theme": "dark", "lock_hash": ""}')
            loaded = Settings.load(st)
            st.close()
            self.assertEqual(loaded.theme, "dark")
            self.assertTrue(loaded.lock_on_minimize)
            self.assertFalse(loaded.lock_enabled)


if __name__ == "__main__":
    unittest.main()
