import io
import json
import unittest
from unittest.mock import patch

import media_integrations as mod


class FakeOpener:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def open(self, request, timeout=7):
        self.calls.append((request.full_url, request.get_method(),
                           request.headers, request.data))
        if (request.full_url, request.get_method()) not in self.mapping:
            raise AssertionError("Unexpected API call: " + repr((request.full_url, request.get_method())))
        raw = self.mapping[(request.full_url, request.get_method())]
        return io.BytesIO(raw)


def encode(data):
    return json.dumps(data).encode("utf-8")


class IntegrationsTests(unittest.TestCase):
    def test_only_local_hosts_are_allowed(self):
        self.assertEqual(mod.local_host("100.68.10.95"), "100.68.10.95")
        self.assertEqual(mod.local_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(mod.local_host("server.tail.example.ts.net"), "server.tail.example.ts.net")
        self.assertEqual(mod.service_address("192.168.1.5", 8989),
                         "http://192.168.1.5:8989")
        for invalid in ["8.8.8.8", "example.org", "http://server", "host/path",
                        "127.0.0.1:9999", "host\nInjected", ""]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                mod.local_host(invalid)
        with self.assertRaises(ValueError):
            mod.service_address("localhost", 99999)

    def test_prowlarr_schema_fills_only_allowed_fields(self):
        schema = [{"implementation": "Sonarr", "fields": [
            {"name": "prowlarrUrl", "value": ""},
            {"name": "baseUrl", "value": ""},
            {"name": "apiKey", "value": ""},
            {"name": "tags", "value": ["old"]},
        ], "name": ""}]
        result = mod.prowlarr_application_payload(
            schema, "Sonarr", "http://localhost:9696",
            "http://localhost:8989", "a-key")
        values = {f["name"]: f["value"] for f in result["fields"]}
        self.assertEqual(values["apiKey"], "a-key")
        self.assertEqual(values["tags"], ["old"])
        self.assertEqual(result["syncLevel"], "addOnly")
        with self.assertRaises(RuntimeError):
            mod.prowlarr_application_payload([{"implementation": "Sonarr", "fields": []}],
                                             "Sonarr", "a", "b", "key")

    def test_idempotent_prowlarr_link_and_no_existing_overwrite(self):
        base = "http://127.0.0.1:9696"
        opener = FakeOpener({
            (base + "/api/v1/applications", "GET"): encode([{
                "id": 17, "implementation": "Sonarr"}]),
            (base + "/api/v1/applications/schema", "GET"): encode([
                {"implementation": "Sonarr", "fields": []}
            ]),
        })
        results = mod.link_prowlarr(("127.0.0.1", 9696), "secret", {
            "Sonarr": ("127.0.0.1", 8989, "sonarr-key")}, opener=opener)
        self.assertEqual(results, [("Sonarr", "déjà relié")])
        self.assertEqual([c[1] for c in opener.calls], ["GET", "GET"])

    def test_new_prowlarr_link_uses_schema_and_acknowledgement(self):
        base = "http://127.0.0.1:9696"
        sonar = "http://127.0.0.1:8989"
        opener = FakeOpener({
            (base + "/api/v1/applications", "GET"): encode([]),
            (base + "/api/v1/applications/schema", "GET"): encode([{
                "implementation": "Sonarr", "fields": [
                    {"name": "prowlarrUrl"}, {"name": "baseUrl"},
                    {"name": "apiKey"}
                ]}]),
            (sonar + "/api/v5/system/status", "GET"): encode({
                "version": "5.0.0"}),
            (base + "/api/v1/applications", "POST"): encode({"id": 47}),
        })
        result = mod.link_prowlarr(("127.0.0.1", 9696), "prowlarr-key", {
            "Sonarr": ("127.0.0.1", 8989, "sonarr-key")}, opener=opener)
        self.assertEqual(result, [("Sonarr", "liaison créée")])
        post = [r for r in opener.calls if r[1] == "POST"]
        self.assertEqual(len(post), 1)
        data = json.loads(post[0][3].decode("utf-8"))
        self.assertEqual(next(f["value"] for f in data["fields"]
                              if f["name"] == "apiKey"), "sonarr-key")
        self.assertNotIn("sonarr-key", post[0][0])

    def test_existing_plex_emby_packages_detected_from_dsm(self):
        installed = mod.installed_video_servers([
            {"name": "Plex Media Server", "id": "PlexMediaServer"},
            {"name": "Emby Server", "id": "EmbyServer"},
            {"name": "Download Station", "id": "DownloadStation"},
        ])
        self.assertEqual(installed, {"Plex", "Emby"})
        self.assertEqual(mod.installed_video_servers([]), set())
        self.assertEqual(mod.installed_video_servers(None), set())

    def test_plex_emby_no_token_read_only_detection(self):
        plex_base = "http://100.68.10.95:32400"
        emby_base = "http://100.68.10.95:8096"
        opener = FakeOpener({
            (plex_base + "/identity", "GET"): (
                b'<MediaContainer version="1.42.3" machineIdentifier="SECRET-ID" claimed="1"/>'),
            (emby_base + "/emby/System/Info/Public", "GET"):
                encode({"ServerName": "PrivateNAS", "Id": "SECRET-ID",
                        "Version": "4.9.2.0", "LocalAddresses": ["10.0.0.7"]}),
        })
        self.assertEqual(mod.probe_video_server("Plex", "100.68.10.95", opener), "1.42.3")
        self.assertEqual(mod.probe_video_server("Emby", "100.68.10.95", opener), "4.9.2.0")
        self.assertTrue(all(call[1] == "GET" for call in opener.calls))
        self.assertTrue(all("Authorization" not in call[2] and "X-Plex-Token" not in call[2]
                            for call in opener.calls))
        self.assertNotIn("SECRET-ID", str([
            mod.probe_video_server("Plex", "100.68.10.95", opener),
            mod.probe_video_server("Emby", "100.68.10.95", opener)]))

    def test_video_server_urls_are_local(self):
        self.assertEqual(mod.video_server_address("Plex", "192.168.1.2"),
                         "http://192.168.1.2:32400/web")
        self.assertEqual(mod.video_server_address("Emby", "192.168.1.2"),
                         "http://192.168.1.2:8096/web/index.html")
        with self.assertRaises(ValueError):
            mod.video_server_address("Plex", "8.8.8.8")
        with self.assertRaises(ValueError):
            mod.video_server_address("Other", "192.168.1.2")

    def test_kodi_scan_and_plex_sections(self):
        kodi = "http://192.168.1.3:8080"
        opener = FakeOpener({
            (kodi + "/jsonrpc", "POST"): encode({"jsonrpc": "2.0", "id": 1,
                                                 "result": "OK"})
        })
        self.assertTrue(mod.kodi_scan("192.168.1.3", 8080, opener=opener))
        kodi_call = opener.calls[0]
        self.assertEqual(json.loads(kodi_call[3])["method"], "VideoLibrary.Scan")
        plex = "http://192.168.1.4:32400"
        plex_opener = FakeOpener({
            (plex + "/library/sections", "GET"): (
                b'<MediaContainer><Directory key="1" type="movie"/>'
                b'<Directory key="2" type="show"/>'
                b'<Directory key="3" type="artist"/></MediaContainer>'),
            (plex + "/library/sections/1/refresh", "GET"): b"",
            (plex + "/library/sections/2/refresh", "GET"): b"",
        })
        self.assertEqual(mod.plex_scan("192.168.1.4", 32400, "TOKEN",
                                      opener=plex_opener), 2)
        self.assertEqual(len(plex_opener.calls), 3)
        self.assertTrue(all("TOKEN" not in call[0]
                            for call in plex_opener.calls))


if __name__ == "__main__":
    unittest.main()
