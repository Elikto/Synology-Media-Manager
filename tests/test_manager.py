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

    def test_clear_log_erases_only_display_and_preserves_future_logs(self):
        import queue

        class FakeRoot:
            def after(self, delay, cb):
                pass

        class FakeLog:
            def __init__(self):
                self.contents = ""
                self.states = []
            def configure(self, **kwargs):
                self.states.append(kwargs.get("state"))
            def insert(self, where, text):
                self.contents += text
            def see(self, where):
                pass
            def delete(self, start, end):
                self.contents = ""

        app = APP["Application"].__new__(APP["Application"])
        app.root = FakeRoot()
        app.events = queue.Queue()
        app.logarea = FakeLog()
        app.log("Ancien message")
        app.clear_log()
        app.log("Nouveau message")
        app.poll()
        self.assertNotIn("Ancien message", app.logarea.contents)
        self.assertIn("Nouveau message", app.logarea.contents)
        self.assertEqual(app.logarea.states[-1], "disabled")
        self.assertFalse(hasattr(app, "report"))

    def test_update_log_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "update_error.txt"
            self.assertIn("Aucun journal", APP["update_log_tail"](file))
            file.write_text(
                "[00:00] Updater started\n"
                "[00:01] Replacement successful\n"
                "[00:02] New executable launched\n", encoding="utf-8")
            log = APP["update_log_tail"](file, max_lines=2)
            self.assertNotIn("Updater started", log)
            self.assertIn("Replacement successful", log)
            self.assertIn("New executable launched", log)

    def test_update_prompt_waits_for_idle(self):
        """Régression : le clic Oui ne doit pas être bloqué par le worker de vérification."""
        import queue

        class FakeRoot:
            def __init__(self):
                self.idle = []
            def after_idle(self, cb):
                self.idle.append(cb)
            def after(self, delay, cb):
                pass

        class FakeStatus:
            def set(self, value):
                pass

        class FakeProgress:
            def start(self, milliseconds):
                pass
            def stop(self):
                pass

        app = APP["Application"].__new__(APP["Application"])
        app.root = FakeRoot()
        app.events = queue.Queue()
        app.busy = False
        app.pending_update = None
        app.status = FakeStatus()
        app.progress = FakeProgress()
        app.log = lambda message: None
        offered = []
        app.offer_update = lambda info: offered.append((info, app.busy))

        app.events.put(("busy", True))
        app.events.put(("update", ("0.4.2", "exe")))
        app.events.put(("busy", False))
        app.poll()

        self.assertFalse(app.busy)
        self.assertEqual(offered, [])
        self.assertEqual(len(app.root.idle), 1)
        app.root.idle[0]()
        self.assertEqual(offered, [(("0.4.2", "exe"), False)])
        self.assertIsNone(app.pending_update)

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

    def test_automatic_package_source_guards(self):
        verifier = APP["verified_synology_package"]
        valid = {"id": "DownloadStation", "maintainer": "Synology Inc.",
                 "link": "https://global.synologydownload.com/DownloadStation.spk",
                 "md5": "b" * 32, "size": 12_000_000}
        self.assertEqual(verifier(valid, "DownloadStation")["id"], "DownloadStation")
        for change in [
            {"maintainer": "Random Maintainer"},
            {"link": "https://updates.synologydownload.com.evil.example/app.spk"},
            {"link": "http://global.synologydownload.com/app.spk"},
            {"md5": "not-a-checksum"},
            {"size": 10},
            {"deppkgs": ["UnknownDependency"]},
        ]:
            with self.subTest(change=change), self.assertRaises((RuntimeError, ValueError)):
                verifier({**valid, **change}, "DownloadStation")
        with self.assertRaises(ValueError):
            verifier(valid, "PlexMediaServer")

    def test_package_api_version_discovery(self):
        class Fake:
            def request(self, api, version, method, params=None, path="entry.cgi", **kw):
                self.assert_not_called = False
                return {name: {"path": "entry.cgi", "minVersion": 2,
                               "maxVersion": 3} for name in (
                    "SYNO.Core.Package.Server", "SYNO.Core.Package.Installation",
                    "SYNO.Core.Package.Installation.Download", "SYNO.Entry.Request")}
        api = APP["package_api_info"](Fake())
        self.assertEqual(api["SYNO.Core.Package.Server"]["minVersion"], 2)

    def test_compound_installation_refuses_partial_failure(self):
        validate = APP["package_install_response_ok"]
        self.assertTrue(validate({"has_fail": False,
            "result": [{"success": True}, {"success": True}]}))
        for response in [
            {}, {"has_fail": True, "result": [{"success": True}, {"success": False}]},
            {"has_fail": False, "result": [{"success": True}, {"success": False}]},
            {"has_fail": False, "result": [{"success": True}]},
        ]:
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                validate(response)

    def test_automated_install_never_forces_or_uninstalls(self):
        import json
        class FakeDSM:
            def __init__(self):
                self.calls = []
            def request(self, api, version, method, params=None, sid=None, path="entry.cgi"):
                self.calls.append((api, method, params, sid))
                if api == "SYNO.API.Info":
                    return {name: {"path": "entry.cgi", "minVersion": 1,
                                   "maxVersion": 3} for name in (
                        "SYNO.Core.Package.Server", "SYNO.Core.Package.Installation",
                        "SYNO.Core.Package.Installation.Download", "SYNO.Entry.Request")}
                if method == "install" and params.get("operation") == "install":
                    return {"taskid": "@SYNOPKG_DOWNLOAD_DownloadStation"}
                if method == "status":
                    return {"finished": True, "progress": 1}
                if api.endswith("Installation.Download") and method == "check":
                    return {"id": "DownloadStation",
                            "maintainer": "Synology Inc.",
                            "filename": "/volume1/@tmp/synopkg/download.x/DownloadStation"}
                if api == "SYNO.Entry.Request":
                    return {"has_fail": False,
                            "result": [{"success": True}, {"success": True}]}
                raise AssertionError("Unexpected call: " + str((api, method)))
        dsm = FakeDSM()
        spec = {"id": "DownloadStation",
                "url": "https://global.synologydownload.com/test.spk",
                "md5": "b" * 32, "size": 100_000}
        APP["install_verified_synology_package"](dsm, "fake_sid", spec,
            lambda message: None, sleep=lambda seconds: None)
        methods = [x[1] for x in dsm.calls]
        self.assertNotIn("uninstall", methods)
        self.assertNotIn("delete", methods)
        final = dsm.calls[-1]
        self.assertEqual(final[0], "SYNO.Entry.Request")
        compound = json.loads(final[2]["compound"])
        self.assertEqual(compound[1]["check_codesign"], True)
        self.assertEqual(compound[1]["force"], False)
        self.assertEqual(compound[1]["volume_path"], "/volume1")
        self.assertEqual(final[2]["stop_when_error"], "true")

    def test_wait_package_checks_real_state_and_never_installs_again(self):
        class FakeDSM:
            def __init__(self):
                self.checks = 0
                self.methods = []
            def request(self, api, version, method, params=None, sid=None):
                self.checks += 1
                self.methods.append(method)
                if self.checks < 3:
                    return {"packages": []}
                return {"packages": [{"id": "DownloadStation",
                                      "name": "Download Station"}]}
        fake = FakeDSM()
        result = APP["wait_for_package"](fake, "sid", "DownloadStation",
             lambda text: None, sleep=lambda secs: None, attempts=5)
        self.assertTrue(result)
        self.assertEqual(fake.checks, 3)
        self.assertEqual(set(fake.methods), {"list"})

    def test_wait_package_returns_false_when_dsm_never_confirms(self):
        class FakeDSM:
            def request(self, api, version, method, params=None, sid=None):
                return {"packages": []}
        self.assertFalse(APP["wait_for_package"](FakeDSM(), "sid", "MediaServer",
            lambda text: None, sleep=lambda secs: None, attempts=2))

    def test_media_indexing_status_read_only(self):
        class FakeDSM:
            def __init__(self, folders):
                self.folders = folders
                self.methods = []
            def request(self, api, version, method, params=None, sid=None, path="entry.cgi"):
                self.methods.append(method)
                if api == "SYNO.API.Info":
                    return {"SYNO.Core.MediaIndexing.IndexFolder":
                            {"path": "entry.cgi", "maxVersion": 1}}
                return {"folders": self.folders}
        files = [
            {"path": "/volume1/Media/Films", "type": "video"},
            {"path": "/volume1/Media/Series", "type": "video"},
        ]
        client = FakeDSM(files)
        state, _ = APP["media_index_status"](client, "sid")
        self.assertEqual(state, "ready")
        self.assertEqual(client.methods, ["query", "get"])
        state, _ = APP["media_index_status"](FakeDSM(files[:1]), "sid")
        self.assertEqual(state, "missing")

    def test_download_destination_is_idempotent_and_rechecked(self):
        class FakeDSM:
            def __init__(self, current):
                self.current = current
                self.calls = []
            def request(self, api, version, method, params=None, sid=None, path="entry.cgi"):
                self.calls.append((api, method, params))
                if api == "SYNO.API.Info":
                    return {"SYNO.DownloadStation.Info":
                            {"path": "DownloadStation/info.cgi", "maxVersion": 2}}
                if method == "getconfig":
                    return {"default_destination": self.current}
                if method == "setserverconfig":
                    self.current = params["default_destination"]
                    return {}
                raise AssertionError("Unexpected method")
        unchanged = FakeDSM("Media/Telechargements")
        self.assertEqual(APP["configure_default_download_destination"](
            unchanged, "sid", lambda message: None), "unchanged")
        self.assertNotIn("setserverconfig", [x[1] for x in unchanged.calls])
        changed = FakeDSM("downloads")
        self.assertEqual(APP["configure_default_download_destination"](
            changed, "sid", lambda message: None), "configured")
        self.assertEqual(changed.current, "Media/Telechargements")
        self.assertEqual(sum(1 for call in changed.calls if call[1] == "setserverconfig"), 1)

    def test_download_uri_validation(self):
        f = APP["validated_download_uri"]
        self.assertEqual(f("https://example.org/video.mp4"), "https://example.org/video.mp4")
        self.assertTrue(f("magnet:?xt=urn:btih:0123456789abcdef").startswith("magnet:"))
        for bad in [
            "file:///etc/passwd", "ftp://example.org/a", "http://localhost/file",
            "http://192.168.1.100/file", "http://127.0.0.1/file",
            "http://10.1.1.1/file", "http://[::1]/", "https://user:pass@example.org/file",
            "http://nas.local/download", "https://example.org/foo,https://example.org/bar",
            "https://example.org/\nmore", "magnet:?dn=missinghash",
        ]:
            with self.subTest(uri=bad), self.assertRaises(ValueError):
                f(bad)

    def test_downloadstation_endpoint_allowlist(self):
        endpoint = APP["downloadstation_endpoint"]
        self.assertEqual(endpoint({
            "SYNO.DownloadStation.Task": {"path": "DownloadStation/task.cgi",
                                           "minVersion": 1, "maxVersion": 2}
        }), "DownloadStation/task.cgi")
        for bad in [
            {}, {"SYNO.DownloadStation.Task": {"path": "../../evil", "maxVersion": 1}},
            {"SYNO.DownloadStation.Task": {"path": "entry.cgi", "minVersion": 2, "maxVersion": 2}}
        ]:
            with self.subTest(value=bad), self.assertRaises(RuntimeError):
                endpoint(bad)

    def test_downloadstation_methods_do_not_delete(self):
        class FakeClient:
            def __init__(self):
                self.calls = []
            def request(self, api, version, method, params=None, sid=None, path="entry.cgi"):
                self.calls.append((api, version, method, params, sid, path))
                if api == "SYNO.API.Info":
                    return {"SYNO.DownloadStation.Task":
                        {"path": "DownloadStation/task.cgi", "minVersion": 1, "maxVersion": 1}}
                if method == "list":
                    return {"total": 1, "tasks": [{"title": "Sample", "status": "waiting"}]}
                return {"task_id": "example"}
        client = FakeClient()
        tasks, total = APP["downloadstation_tasks"](client, "test_session")
        self.assertEqual((len(tasks), total), (1, 1))
        APP["create_downloadstation_task"](client, "test_session", "https://example.org/file.mp4")
        write = client.calls[-1]
        self.assertEqual(write[:3], ("SYNO.DownloadStation.Task", 1, "create"))
        self.assertEqual(write[3]["destination"], "Media/Telechargements")
        self.assertEqual(write[5], "DownloadStation/task.cgi")
        self.assertNotIn("delete", [call[2] for call in client.calls])

    def test_sha256(self):
        self.assertEqual(APP["sha256"](b"abc"),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


if __name__ == "__main__":
    unittest.main()
