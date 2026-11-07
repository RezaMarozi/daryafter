"""Unit tests for the optional desktop notification fallback."""
import subprocess
import unittest
from unittest import mock

from daryafter.ui.notifications import notify_desktop


class DesktopNotificationTests(unittest.TestCase):
    @mock.patch("daryafter.ui.notifications.subprocess.run")
    @mock.patch("daryafter.ui.notifications.shutil.which", return_value="/usr/bin/notify-send")
    def test_successful_notification(self, which, run):
        run.return_value = mock.Mock(returncode=0, stderr="")
        self.assertTrue(notify_desktop("Title", "Message"))
        which.assert_called_once_with("notify-send")
        run.assert_called_once_with(
            [
                "/usr/bin/notify-send",
                "--app-name", "Daryafter",
                "--icon", "daryafter",
                "--expire-time", "6000",
                "Title",
                "Message",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )

    @mock.patch("daryafter.ui.notifications.subprocess.run")
    @mock.patch("daryafter.ui.notifications.shutil.which", return_value=None)
    def test_missing_notify_send(self, which, run):
        self.assertFalse(notify_desktop("Title", "Message"))
        run.assert_not_called()

    @mock.patch("daryafter.ui.notifications.subprocess.run")
    @mock.patch("daryafter.ui.notifications.shutil.which", return_value="/usr/bin/notify-send")
    def test_nonzero_exit_status(self, which, run):
        run.return_value = mock.Mock(returncode=1, stderr="No notification daemon")
        self.assertFalse(notify_desktop("Title", "Message"))

    @mock.patch("daryafter.ui.notifications.subprocess.run", side_effect=OSError("execution failed"))
    @mock.patch("daryafter.ui.notifications.shutil.which", return_value="/usr/bin/notify-send")
    def test_execution_error_is_nonfatal(self, which, run):
        self.assertFalse(notify_desktop("Title", "Message"))

    @mock.patch(
        "daryafter.ui.notifications.subprocess.run",
        side_effect=subprocess.TimeoutExpired("notify-send", 2),
    )
    @mock.patch("daryafter.ui.notifications.shutil.which", return_value="/usr/bin/notify-send")
    def test_timeout_is_nonfatal(self, which, run):
        self.assertFalse(notify_desktop("Title", "Message"))

    @mock.patch("daryafter.ui.notifications.subprocess.run")
    @mock.patch("daryafter.ui.notifications.shutil.which", return_value="/usr/bin/notify-send")
    def test_custom_arguments_and_negative_timeout(self, which, run):
        run.return_value = mock.Mock(returncode=0, stderr="")
        self.assertTrue(
            notify_desktop(
                "Done",
                "Finished",
                app_name="Custom App",
                icon="custom-icon",
                timeout_ms=-500,
            )
        )
        command = run.call_args.args[0]
        self.assertEqual(command[2], "Custom App")
        self.assertEqual(command[4], "custom-icon")
        self.assertEqual(command[6], "0")


if __name__ == "__main__":
    unittest.main()
