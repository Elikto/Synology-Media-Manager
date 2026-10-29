import runpy
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = runpy.run_path(str(ROOT / "SynologyMediaManager.pyw"))


class TestManager(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP["version_tuple"]("1.10.3"), (1, 10, 3))
        with self.assertRaises(ValueError):
            APP["version_tuple"]("not-a-version")

    def test_update_manifest_validation(self):
        digest = "a" * 64
        self.assertEqual(APP["check_manifest"]({"version": "1.2.0", "sha256": digest}),
                         ("1.2.0", digest))
        with self.assertRaises(ValueError):
            APP["check_manifest"]({"version": "1.2.0", "sha256": "none"})

    def test_sanitized_report(self):
        source = {
            "disks": [{"name": "Drive 1", "serial": "PRIVATE123", "temp": 23,
                       "status": "normal", "unc": 129, "smart_status": "normal"}],
            "storagePools": [{"status": "normal", "device_type": "shr_with_1_disk_protect"}],
            "volumes": [{"id": "volume_1", "status": "normal", "uuid": "PRIVATE"}],
            "sid": "SECRET",
        }
        output = APP["redact_report"](source)
        self.assertEqual(output["disks"][0]["unc"], 129)
        self.assertNotIn("PRIVATE", str(output))
        self.assertNotIn("SECRET", str(output))

    def test_github_release_version(self):
        release = {
            "tag_name": "v0.2.0", "draft": False, "prerelease": False,
            "assets": [{"name": "SynologyMediaManager.exe"},
                       {"name": "SHA256SUMS.txt"}]
        }
        self.assertEqual(APP["release_version"](release), "0.2.0")
        release["assets"] = []
        with self.assertRaises(ValueError):
            APP["release_version"](release)

    def test_executable_checksum_format(self):
        checksum = "b" * 64
        self.assertEqual(APP["release_checksum"](
            checksum + "  SynologyMediaManager.exe\n"), checksum)
        with self.assertRaises(ValueError):
            APP["release_checksum"](checksum + "  Other.exe")

    def test_media_checks_healthy_storage(self):
        valid = {
            "storagePools": [{"status": "normal",
                              "is_backgroundbuilding": False,
                              "progress": {"percent": "-1"}}],
            "volumes": [{"status": "normal"}],
        }
        self.assertTrue(APP["check_media_storage"](valid))
        valid["storagePools"][0]["status"] = "degraded"
        with self.assertRaises(RuntimeError):
            APP["check_media_storage"](valid)

    def test_media_share_requires_volume1(self):
        self.assertFalse(APP["check_media_share"]([]))
        self.assertTrue(APP["check_media_share"](
            [{"name": "Media", "vol_path": "/volume1"}]))
        with self.assertRaises(RuntimeError):
            APP["check_media_share"](
                [{"name": "Media", "vol_path": "/volume2"}])

    def test_media_folders_idempotent(self):
        entries = [{"name": "Films", "isdir": True},
                   {"name": "Series", "isdir": True}]
        self.assertEqual(APP["missing_media_folders"](entries), ["Telechargements"])
        entries.append({"name": "Telechargements", "isdir": True})
        self.assertEqual(APP["missing_media_folders"](entries), [])
        with self.assertRaises(RuntimeError):
            APP["missing_media_folders"]([{"name": "Films", "isdir": False}])

    def test_creation_restricted_to_expected_folders(self):
        class FakeClient:
            def __init__(self):
                self.calls = []
            def request(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return {}
        client = FakeClient()
        APP["create_media_subfolder"](client, "fake_sid", "Films")
        args, kwargs = client.calls[0]
        self.assertEqual(args[:3],
                         ("SYNO.FileStation.CreateFolder", 2, "create"))
        self.assertEqual(kwargs["sid"], "fake_sid")
        self.assertEqual(args[3]["folder_path"], '["/Media"]')
        with self.assertRaises(ValueError):
            APP["create_media_subfolder"](client, "fake_sid", "../secrets")

    @unittest.skipUnless(sys.platform == "win32", "Windows PowerShell only")
    def test_windows_updater_replaces_and_backs_up(self):
        """Run the same embedded script used for GUI updates in isolated files."""
        with tempfile.TemporaryDirectory(prefix="SynologyManagerTest") as path:
            work = Path(path)
            target = work / "SynologyMediaManager (1).exe"
            staged = work / "staged.exe"
            log = work / "updater.log"
            script = work / "updater.ps1"
            target.write_bytes(b"old-release")
            staged.write_bytes(b"new-release")
            script.write_text(APP["EXE_UPDATER"], encoding="utf-8-sig")
            completed = subprocess.run([
                "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(script),
                "-Target", str(target), "-Staged", str(staged),
                "-LogPath", str(log), "-NoLaunch"
            ], capture_output=True, text=True, timeout=45)
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            self.assertEqual(target.read_bytes(), b"new-release")
            self.assertEqual(Path(str(target) + ".backup").read_bytes(), b"old-release")
            self.assertIn("Replacement successful", log.read_text(encoding="utf-8-sig"))

    def test_sha256(self):
        self.assertEqual(APP["sha256"](b"abc"),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


if __name__ == "__main__":
    unittest.main()
