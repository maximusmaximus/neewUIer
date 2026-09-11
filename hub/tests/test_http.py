from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _get(origin: str, path: str) -> tuple[int, dict | str]:
    with urlopen(origin + path, timeout=3) as res:
        raw = res.read().decode()
        try:
            return res.status, json.loads(raw)
        except json.JSONDecodeError:
            return res.status, raw


def test_rest_health_and_ha_color_roundtrip(hub, isolated_hub) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), hub.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        origin = f"http://127.0.0.1:{port}"
        isolated_hub.patch("key", {"connected": True, "power": True})
        status, health = _get(origin, "/api/health")
        assert status == 200
        assert health["ok"] is True
        assert health["name"] == "cinenode"

        req = Request(
            origin + "/api/lights/key",
            data=json.dumps(
                {"state": "ON", "color_mode": "hs", "color": {"h": 88, "s": 24}, "brightness": 100}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=3) as res:
            body = json.loads(res.read().decode())
        assert body["mode"] == "hsi"
        assert body["hue"] == 88
        assert body["ha"]["state"] == "ON"

        _, docs = _get(origin, "/api/ha/mqtt")
        assert "cinenode/+/set" in docs["subscribe"]
        assert docs["documents"][0]["payload"]["schema"] == "json"

        _, lights = _get(origin, "/api/lights")
        assert lights["ok"] is True
        assert any(item["id"] == "key" for item in lights["lights"])

        _, one = _get(origin, "/api/lights/key")
        assert one["id"] == "key"
        assert "ha" in one

        _, disco = _get(origin, "/api/discovery")
        assert disco["name"] == "CineNode"
        assert "/api/health" in disco["health"]

        options = Request(origin + "/api/health", method="OPTIONS")
        with urlopen(options, timeout=3) as res:
            assert res.status == 204
            assert res.headers.get("Access-Control-Allow-Origin") == "*"

        put = Request(
            origin + "/api/lights/key",
            data=json.dumps({"state": "OFF"}).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urlopen(put, timeout=3) as res:
            off = json.loads(res.read().decode())
        assert off["power"] is False

        bad = Request(origin + "/api/lights/missing", data=b"{}", method="POST")
        try:
            urlopen(bad, timeout=3)
            raise AssertionError("expected 404")
        except HTTPError as exc:
            assert exc.code == 404

        try:
            urlopen(origin + "/api/nope", timeout=3)
            raise AssertionError("expected 404")
        except HTTPError as exc:
            assert exc.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
