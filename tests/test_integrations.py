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

    def test_downloadstation_client_schema_is_safe_and_complete(self):
        schema = [{"implementation": "TorrentDownloadStation",
                   "fields": [{"name": name} for name in
                     ("host", "port", "useSsl", "username", "password",
                      "tvCategory", "tvDirectory")],
                   "removeCompletedDownloads": True}]
        payload = mod.downloadstation_client_payload(
            schema, "100.68.10.95", 5001, "media_user", "secret", "sonarr")
        fields = {item["name"]: item["value"] for item in payload["fields"]}
        self.assertEqual(fields["host"], "100.68.10.95")
        self.assertTrue(fields["useSsl"])
        self.assertEqual(fields["tvCategory"], "sonarr")
        self.assertEqual(fields["tvDirectory"], "")
        self.assertFalse(payload["removeCompletedDownloads"])
        self.assertNotIn("value", schema[0]["fields"][0])
        with self.assertRaises(RuntimeError):
            mod.downloadstation_client_payload(
                [{"implementation": "TorrentDownloadStation", "fields": []}],
                "100.68.10.95", 5001, "user", "pw", "radarr")
        with self.assertRaises(ValueError):
            mod.downloadstation_client_payload(schema, "8.8.8.8", 5001,
                                               "user", "password", "radarr")

    def test_downloadstation_link_idempotence_without_writes(self):
        addr = "http://127.0.0.1:8989"
        opener = FakeOpener({
            (addr + "/api/v5/system/status", "GET"):
                encode({"version": "5.0.0"}),
            (addr + "/api/v5/downloadclient", "GET"):
                encode([{"id": 12, "implementation": "TorrentDownloadStation",
                         "fields": [{"name": "host", "value": "100.68.10.95"},
                                    {"name": "port", "value": 5001},
                                    {"name": "tvCategory", "value": "sonarr"}]}]),
        })
        result = mod.link_downloadstation_to_arr(
            "Sonarr", "127.0.0.1", 8989, "arr-api-key", "100.68.10.95", 5001,
            "media_user", "nas_password", opener=opener)
        self.assertEqual(result, "déjà configuré, aucune modification")
        self.assertTrue(all(method == "GET" for _, method, _, _ in opener.calls))

    def test_downloadstation_add_requires_server_test(self):
        addr = "http://127.0.0.1:7878"
        fields = ["host", "port", "useSsl", "username", "password", "tvCategory"]
        mapping = {
            (addr + "/api/v3/system/status", "GET"):
                encode({"version": "5.1.0"}),
            (addr + "/api/v3/downloadclient", "GET"): encode([]),
            (addr + "/api/v3/downloadclient/schema", "GET"):
                encode([{"implementation": "TorrentDownloadStation",
                         "fields": [{"name": name} for name in fields]}]),
            (addr + "/api/v3/downloadclient/test", "POST"):
                encode([{"error": "The NAS was not reachable"}]),
        }
        opener = FakeOpener(mapping)
        with self.assertRaises(RuntimeError):
            mod.link_downloadstation_to_arr(
                "Radarr", "127.0.0.1", 7878, "arr-key",
                "100.68.10.95", 5001, "user", "pw", opener=opener)
        self.assertEqual([method for _, method, _, _ in opener.calls][-1], "POST")
        self.assertFalse(any(url.endswith("/downloadclient") and method == "POST"
                             for url, method, _, _ in opener.calls))

    def test_prowlarr_indexers_count_read_only(self):
        opener = FakeOpener({
            ("http://127.0.0.1:9696/api/v1/indexer", "GET"):
                encode([{"id": 1}, {"id": 2}])
        })
        self.assertEqual(mod.prowlarr_indexer_count(
            "127.0.0.1", 9696, "key", opener=opener), 2)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(opener.calls[0][1], "GET")

    def test_kodi_media_paths_only_include_media_library(self):
        expected = {
            "Films": "smb://192.168.1.12/Media/Films/",
            "Series": "smb://192.168.1.12/Media/Series/"
        }
        self.assertEqual(mod.kodi_media_paths("192.168.1.12"), expected)
        self.assertEqual(mod.kodi_media_paths("100.65.32.4")["Films"],
                         "smb://100.65.32.4/Media/Films/")
        for invalid in ("https://example.org", "8.8.8.8", "host/share"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                mod.kodi_media_paths(invalid)
        self.assertEqual(set(mod.SERVICE_PORTS),
                         {"Prowlarr", "Sonarr", "Radarr", "Kodi"})

    def test_kodi_scan_uses_existing_library_without_other_servers(self):
        kodi = "http://192.168.1.3:8080"
        opener = FakeOpener({
            (kodi + "/jsonrpc", "POST"): encode({
                "jsonrpc": "2.0", "id": 1, "result": "OK"})
        })
        self.assertTrue(mod.kodi_scan("192.168.1.3", 8080, opener=opener))
        self.assertEqual(len(opener.calls), 1)
        call = opener.calls[0]
        self.assertEqual(call[1], "POST")
        self.assertEqual(json.loads(call[3])["method"], "VideoLibrary.Scan")
        self.assertNotIn("X-Plex-Token", call[2])

if __name__ == "__main__":
    unittest.main()
