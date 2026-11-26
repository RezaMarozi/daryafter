"""Guard the browser-extension layout and build output.

Both browsers are assembled from one shared source tree:

    extension/src/                     shared HTML/CSS/JS/icons
    extension/firefox/manifest.json    Firefox MV3 event page
    extension/chrome/manifest.json     Chrome MV3 service worker

``extension/build.py`` copies ``src/`` plus the right manifest into
``dist/extensions/<browser>/`` and writes a ZIP. These tests keep the
manifests honest and make sure the builds stay independent.
"""
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXTENSION = REPO / "extension"
SRC = EXTENSION / "src"
SHARED = (
    "common.js", "common.css", "background.js", "content.js",
    "popup.html", "popup.js", "options.html", "options.js",
    "icons/icon16.png", "icons/icon32.png", "icons/icon48.png",
    "icons/icon96.png", "icons/icon128.png",
)


def load_manifest(browser):
    return json.loads((EXTENSION / browser / "manifest.json").read_text())


class SharedSourceTestCase(unittest.TestCase):
    def test_shared_files_exist_once(self):
        for name in SHARED:
            self.assertTrue((SRC / name).is_file(), f"missing extension/src/{name}")
        # The old duplicated trees must not come back.
        for stale in ("background.js", "content.js", "options.js", "popup.js",
                      "options.html", "popup.html", "manifest.json"):
            self.assertFalse((EXTENSION / stale).exists(), f"stale extension/{stale}")
        for stale in SHARED:
            self.assertFalse((EXTENSION / "chrome" / stale).exists(),
                             f"duplicated extension/chrome/{stale}")

    def test_pages_load_shared_helpers(self):
        for page in ("options.html", "popup.html"):
            html = (SRC / page).read_text()
            self.assertIn('src="common.js"', html, page)
            self.assertIn('href="common.css"', html, page)
        background = (SRC / "background.js").read_text()
        self.assertIn('importScripts("common.js")', background)
        content = (SRC / "content.js").read_text()
        self.assertIn("DaryafterCommon", content)


class FirefoxManifestTestCase(unittest.TestCase):
    def setUp(self):
        self.data = load_manifest("firefox")

    def test_is_firefox_manifest(self):
        self.assertEqual(self.data["manifest_version"], 3)
        self.assertEqual(self.data["background"].get("scripts"),
                         ["common.js", "background.js"])
        self.assertNotIn("service_worker", self.data["background"])
        self.assertIn("browser_specific_settings", self.data)
        self.assertEqual(
            self.data["browser_specific_settings"]["gecko"]["data_collection_permissions"],
            {"required": ["none"]},
        )

    def test_gecko_id_matches_native_host(self):
        host = (REPO / "packaging" / "daryafter-native-host.json")
        allowed = json.loads(host.read_text())["allowed_extensions"]
        gecko_id = self.data["browser_specific_settings"]["gecko"]["id"]
        self.assertIn(gecko_id, allowed)

    def test_permissions_and_files(self):
        self.assertIn("nativeMessaging", self.data["permissions"])
        self.assertEqual(self.data["content_scripts"][0]["js"],
                         ["common.js", "content.js"])
        for path in ("background.js", "content.js", "popup.html", "options.html",
                     "icons/icon48.png"):
            self.assertTrue((SRC / path).exists(), path)


class ChromeManifestTestCase(unittest.TestCase):
    def setUp(self):
        self.data = load_manifest("chrome")

    def test_is_chrome_manifest(self):
        self.assertEqual(self.data["manifest_version"], 3)
        self.assertEqual(self.data["background"].get("service_worker"), "background.js")
        self.assertNotIn("scripts", self.data["background"])
        self.assertNotIn("browser_specific_settings", self.data)
        self.assertNotIn("data_collection_permissions", self.data)

    def test_permissions_and_files(self):
        self.assertIn("nativeMessaging", self.data["permissions"])
        self.assertEqual(self.data["content_scripts"][0]["js"],
                         ["common.js", "content.js"])
        for path in ("background.js", "content.js", "popup.html", "options.html",
                     "icons/icon48.png"):
            self.assertTrue((SRC / path).exists(), path)


class BuildTestCase(unittest.TestCase):
    def test_check_passes(self):
        result = subprocess.run(
            [sys.executable, str(EXTENSION / "build.py"), "--check"],
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok   firefox", result.stdout)
        self.assertIn("ok   chrome", result.stdout)

    def test_builds_independent_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(EXTENSION / "build.py"), "--output", tmp],
                capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            out = Path(tmp)

            firefox = out / "firefox" / "manifest.json"
            chrome = out / "chrome" / "manifest.json"
            self.assertTrue(firefox.is_file())
            self.assertTrue(chrome.is_file())
            self.assertEqual(json.loads(firefox.read_text())["background"]["scripts"],
                             ["common.js", "background.js"])
            self.assertEqual(json.loads(chrome.read_text())["background"]["service_worker"],
                             "background.js")

            for name in SHARED:
                self.assertTrue((out / "firefox" / name).is_file(), name)
                self.assertTrue((out / "chrome" / name).is_file(), name)

            for browser in ("firefox", "chrome"):
                archives = list(out.glob(f"daryafter-{browser}-*.zip"))
                self.assertEqual(len(archives), 1, browser)
                with zipfile.ZipFile(archives[0]) as bundle:
                    names = set(bundle.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("common.js", names)
                self.assertIn("background.js", names)
                self.assertIn("options.html", names)
                self.assertNotIn("../", " ".join(names))

    def test_build_rejects_broken_manifest(self):
        # A manifest that points at a file we do not ship must fail loudly.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "daryafter_extension_build", EXTENSION / "build.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        manifest = load_manifest("firefox")
        manifest["options_ui"]["page"] = "missing.html"
        with self.assertRaises(module.BuildError):
            module.validate("firefox", manifest)


if __name__ == "__main__":
    unittest.main()
