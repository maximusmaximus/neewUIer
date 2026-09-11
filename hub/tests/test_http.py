from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def test_rest_health_and_ha_color_roundtrip(hub) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), hub.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        origin = f"http://127.0.0.1:{port}"
        hub.HUB.patch("key", {"connected": True, "power": True})
        with urlopen(origin + "/api/health", timeout=3) as res:
            health = json.loads(res.read().decode())
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

        with urlopen(origin + "/api/ha/mqtt", timeout=3) as res:
            docs = json.loads(res.read().decode())
        assert "cinenode/+/set" in docs["subscribe"]
        assert docs["documents"][0]["payload"]["schema"] == "json"

        bad = Request(origin + "/api/lights/missing", data=b"{}", method="POST")
        try:
            urlopen(bad, timeout=3)
            raise AssertionError("expected 404")
        except HTTPError as exc:
            assert exc.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
