"""Guard the extension folder layout.

The Firefox manifest is ``extension/manifest.json`` (so Firefox's
"Load Temporary Add-on" finds it whatever file is picked), while
Chrome's manifest lives in ``extension/chrome/`` (Chrome's
"Load unpacked" needs it at a folder root). The shared files exist in
both places; this test keeps the copies identical.
"""
import json
import unittest
from pathlib import Path

EXTENSION = Path(__file__).resolve().parent.parent / "extension"
SHARED = ("background.js", "content.js", "popup.html", "popup.js",
          "options.html", "options.js", "icons/icon16.png", "icons/icon32.png",
          "icons/icon48.png", "icons/icon96.png", "icons/icon128.png")


class FirefoxManifestTestCase(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((EXTENSION / "manifest.json").read_text())

    def test_is_firefox_manifest(self):
        self.assertEqual(self.data["manifest_version"], 3)
        self.assertEqual(self.data["background"].get("scripts"), ["background.js"])
        self.assertNotIn("service_worker", self.data["background"])
        self.assertIn("browser_specific_settings", self.data)   # gecko id required

    def test_gecko_id_matches_native_host(self):
        host = (EXTENSION.parent / "packaging" / "daryafter-native-host.json")
        allowed = json.loads(host.read_text())["allowed_extensions"]
        gecko_id = self.data["browser_specific_settings"]["gecko"]["id"]
        self.assertIn(gecko_id, allowed)

    def test_permissions_and_files(self):
        self.assertIn("nativeMessaging", self.data["permissions"])
        for path in ("background.js", "content.js", "popup.html", "options.html",
                     "icons/icon48.png"):
            self.assertTrue((EXTENSION / path).exists(), path)


class ChromeManifestTestCase(unittest.TestCase):
    def setUp(self):
        self.root = EXTENSION / "chrome"
        self.data = json.loads((self.root / "manifest.json").read_text())

    def test_is_chrome_manifest(self):
        self.assertEqual(self.data["manifest_version"], 3)
        self.assertEqual(self.data["background"].get("service_worker"), "background.js")
        self.assertNotIn("scripts", self.data["background"])
        self.assertNotIn("browser_specific_settings", self.data)
        self.assertNotIn("data_collection_permissions", self.data)

    def test_permissions_and_files(self):
        self.assertIn("nativeMessaging", self.data["permissions"])
        for path in ("background.js", "content.js", "popup.html", "options.html",
                     "icons/icon48.png"):
            self.assertTrue((self.root / path).exists(), path)


class CopiesInSyncTestCase(unittest.TestCase):
    def test_shared_files_are_identical(self):
        for name in SHARED:
            firefox = (EXTENSION / name).read_bytes()
            chrome = (EXTENSION / "chrome" / name).read_bytes()
            self.assertEqual(firefox, chrome, f"{name} differs between extension/ and extension/chrome/")


if __name__ == "__main__":
    unittest.main()
