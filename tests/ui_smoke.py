"""Run: python -m tests.ui_smoke   (uses a fake Qt; checks the GUI code for Python errors)."""
import time

from tests import qt_stub

qt_stub.install()

from daryafter.core.models import AddRequest, Event, ProbeResult, State  # noqa: E402
from daryafter.core.models import DownloadItem, make_snapshot  # noqa: E402
from daryafter.core.settings import Settings  # noqa: E402
from daryafter.ui import models as ui_models  # noqa: E402
from daryafter.ui.add_dialog import AddDownloadDialog  # noqa: E402
from daryafter.ui.main_window import MainWindow  # noqa: E402
from daryafter.ui.bridge import EngineBridge  # noqa: E402


class FakeIndex:
    def __init__(self, snap, col):
        self.snap, self.col = snap, col

    def isValid(self):
        return True

    def row(self):
        return 0

    def column(self):
        return self.col

    def data(self, role=None):
        return self.snap


class FakeFuture:
    def add_done_callback(self, f):
        pass


class FakeService:
    def __init__(self):
        self.calls = []

    def snapshots(self):
        return [make_snapshot(DownloadItem(id=1, url="http://a/b.zip", filename="b.zip", directory="/tmp",
                                           state=State.DOWNLOADING, total_size=1000))]

    def probe(self, url, options=None):
        self.calls.append(("probe", url))
        return FakeFuture()

    def add(self, req):
        self.calls.append(("add", req))
        return FakeFuture()

    def __getattr__(self, name):
        def call(*a, **k):
            self.calls.append((name, a))
            return FakeFuture()
        return call


def main():
    snap = FakeService().snapshots()[0]
    model = ui_models.DownloadsModel()
    model.upsert(snap)
    model.update_many([snap])
    for col in range(len(ui_models.COLUMNS)):
        model.data(FakeIndex(snap, col))
    for state in State:
        item = DownloadItem(id=2, url="http://x/y.mp4", filename="y.mp4", state=state, total_size=500)
        s = make_snapshot(item, speed=1e6, eta=5, message="m")
        ui_models.status_text(s)
        for name in ui_models.FILTERS:
            ui_models.matches_filter(s, name)
    model.remove(1)

    service = FakeService()
    bridge = EngineBridge()
    win = MainWindow(service, bridge, Settings(download_dir="/tmp"), private=True)
    for ev in (Event("added", snapshot=snap), Event("updated", snapshot=snap),
               Event("progress", snapshots=[snap], speed=1234.0), Event("completed", snapshot=snap),
               Event("offline", flag=True), Event("removed", item_id=1)):
        win._on_event(ev)
    win.save_state()
    win.running_count()
    win._update_detail()
    win._retheme = lambda: None
    win.apply_new_settings(Settings(download_dir="/tmp", theme="dark"))
    from daryafter.ui.extras import SummaryDialog, Toast
    from daryafter.ui.settings_dialog import SettingsDialog
    from daryafter.ui.widgets import SegmentMap, SpeedChart
    from daryafter.ui import icons
    done = make_snapshot(DownloadItem(id=3, url="http://a/c.zip", filename="c.zip", directory="/tmp",
                                      state=State.COMPLETED, total_size=1000, active_seconds=5,
                                      session_bytes=1000, min_speed=100.0, max_speed=300.0))
    SummaryDialog(done, None)
    Toast(None)
    dlg = SettingsDialog(Settings(download_dir="/tmp"), None)
    assert dlg.result_settings().connections == 8
    chart = SpeedChart()
    chart.set_values([1.0, 5e5, 2e6])
    chart.paintEvent(None)
    segmap = SegmentMap()
    segmap.set_data(1000, [(0, 500, 300), (500, 1000, 600)])
    segmap.paintEvent(None)
    icons.icon("plus")
    from PySide6.QtCore import QRectF
    from daryafter.ui import theme
    delegate = ui_models.RowDelegate()
    painter = qt_stub.Dummy()
    for st in (done, snap):
        delegate._paint_name(painter, QRectF(0, 0, 500, 56), st, theme.colors())
        delegate._paint_progress(painter, QRectF(0, 0, 230, 56), st, theme.colors())
    win.detail.show_snapshot(done, [1.0, 2.0])
    win.detail.show_snapshot(snap, [1.0, 2.0])
    win.detail.show_overview(10.0, [1.0, 2.0])

    dlg = AddDownloadDialog(service, Settings(download_dir="/tmp"), None, "http://example.com/f.zip")
    dlg._check_link()
    dlg._seq = 1
    dlg._on_probed(1, ProbeResult("http://example.com/f.zip", "http://example.com/f.zip", 206, 5000, True,
                                  "f.zip", is_html=True), "")
    assert dlg.name_edit.text() == "f.zip", dlg.name_edit.text()
    dlg._on_probed(1, None, "boom")
    dlg._finish(True)
    req = dlg.request()
    assert isinstance(req, AddRequest) and req.filename == "f.zip" and req.start_now
    lock_flow(service)
    timers_and_queue(service)
    print("UI smoke test OK")


def timers_and_queue(service):
    """Timers tab, timer dialog, timer messages, queue menu and queue position."""
    from daryafter.core.schedule import Rule
    from daryafter.ui.models import DownloadsModel
    from daryafter.ui.schedule_dialog import RuleDialog, rule_text
    from daryafter.ui.settings_dialog import SettingsDialog

    rule = Rule("stop", 23, 30, [0, 4], once=True, enabled=False)
    text = rule_text(rule)
    assert "23:30" in text and "once" in text and "(off)" in text, text
    assert "every day" in rule_text(Rule("start", 2, 0))
    dialog = RuleDialog(rule)
    back = dialog.rule()
    assert back.action in ("start", "stop", "disconnect") and back.days, back

    s = Settings(download_dir="/tmp", schedule=[Rule("start", 2, 0).to_dict(), "junk"])
    dlg = SettingsDialog(s, None)
    assert len(dlg._s.schedule) == 2
    dlg._add_rule()
    assert len(dlg._s.schedule) == 3
    dlg._edit_rule()
    dlg._remove_rule()
    dlg._refresh_rules()
    assert dlg.result_settings().schedule is not s.schedule          # a copy

    win = MainWindow(service, EngineBridge(), Settings(download_dir="/tmp"), private=False)
    for action in ("start", "stop", "disconnect"):
        win._on_event(Event("schedule", text=action))
    win._on_event(Event("schedule", text="stop", flag=True))         # a once-timer: window saves the settings

    import dataclasses
    base = service.snapshots()[0]
    queue = [dataclasses.replace(base, id=101, state=State.QUEUED, priority=1),
             dataclasses.replace(base, id=102, state=State.QUEUED, priority=3),
             dataclasses.replace(base, id=103, state=State.QUEUED, priority=3),
             dataclasses.replace(base, id=104, state=State.PAUSED, priority=9)]
    qmodel = DownloadsModel()
    qmodel.set_all(queue)
    assert [qmodel._queue_position(i) for i in (102, 103, 101, 104)] == [1, 2, 3, 0], "higher priority first, then older"
    qmodel.upsert(dataclasses.replace(base, id=101, state=State.QUEUED, priority=5))
    assert qmodel._queue_position(101) == 1, "position must follow a change of priority"

    model = DownloadsModel()
    snaps = service.snapshots()
    model.set_all(snaps)
    for snap in snaps:                                               # queue position never crashes, any state
        for col in range(6):
            model.data(model.index(snaps.index(snap), col))


def lock_flow(service):
    """App lock, lock screen, password dialog, privacy tab (fake Qt: catches Python mistakes only)."""
    from daryafter.ui.lock_screen import LockScreen
    from daryafter.ui.password_dialog import CHANGE, REMOVE, SET, PasswordDialog
    from daryafter.ui.settings_dialog import SettingsDialog

    locked_settings = Settings(download_dir="/tmp")
    locked_settings.set_password("secret")
    win = MainWindow(service, EngineBridge(), locked_settings, private=False)
    assert win.lock.locked, "a password is set, so the app must start locked"
    snap = service.snapshots()[0]
    opened = []
    win.add_download = lambda url="", _orig=win.add_download: (opened.append(url), _orig(url))[1]
    win._pending_url = ""
    win.add_download("http://example.com/a.zip")                  # asked while locked: must wait
    assert win._pending_url == "http://example.com/a.zip"
    win._on_event(Event("completed", snapshot=snap))               # no pop-up / name while locked
    win._on_event(Event("progress", snapshots=[snap], speed=10.0))
    win._clipboard_changed()
    win.open_settings()                                            # refused while locked
    win._try_unlock("wrong")
    assert win.lock.locked
    win._try_unlock("secret")
    assert not win.lock.locked
    assert win._pending_url == "" and opened[-1] == "http://example.com/a.zip"
    win.lock_now()
    assert win.lock.locked
    win._try_unlock("secret")
    win._check_idle()
    win.clear_history()
    win.show_about()
    win.apply_new_settings(locked_settings.copy())
    assert win.settings.lock_enabled

    plain = MainWindow(service, EngineBridge(), Settings(download_dir="/tmp"), private=True)
    assert not plain.lock.locked
    plain.lock_now()
    assert not plain.lock.locked, "no password: nothing to lock"
    plain._on_event(Event("completed", snapshot=snap))             # private: generic notification text

    screen = LockScreen()
    got = []
    screen.unlock_requested.connect(got.append)
    screen.edit.setText("pw")
    screen._submit()
    assert got == ["pw"]
    screen.show_failure(0)
    screen.show_failure(3)
    screen._tick()
    screen.reset()

    s = Settings()
    dlg = PasswordDialog(s, SET)
    dlg.new.setText("abcd")
    dlg.confirm.setText("abce")
    assert dlg.problem()
    dlg.confirm.setText("abcd")
    assert dlg.problem() == "" and dlg.new_password() == "abcd"
    s.set_password("abcd")
    dlg = PasswordDialog(s, CHANGE)
    dlg.current.setText("zzzz")
    dlg.new.setText("efgh")
    dlg.confirm.setText("efgh")
    assert dlg.problem(), "wrong current password must be refused"
    dlg.current.setText("abcd")
    assert dlg.problem() == ""
    dlg = PasswordDialog(s, REMOVE)
    assert dlg.problem()
    dlg.current.setText("abcd")
    assert dlg.problem() == "" and dlg.new_password() == ""

    settings_dlg = SettingsDialog(s, None, private=False, on_clear_history=lambda parent: None)
    settings_dlg.lock_minutes.setValue(15)
    settings_dlg.lock_minimize.setChecked(False)
    result = settings_dlg.result_settings()
    assert (result.lock_after_minutes, result.lock_on_minimize) == (15, False)
    assert result.lock_enabled and result.check_password("abcd")
    SettingsDialog(s, None, private=True)._update_lock_ui()
    from daryafter.ui import icons
    icons.icon("lock")


if __name__ == "__main__":
    main()
