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
        isolated_hub.lights = [hub.new_light(id="key", name="Key", mac="AA:BB:CC:DD:EE:FF", connected=True, power=True)]
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
        isolated_hub.last_seen = [{"mac": "C5:02:F5:0D:CA:BA", "name": "(no name)", "reason": "probe", "rssi": -40}]
        _, seen = _get(origin, "/api/seen")
        assert seen["ok"] is True
        assert seen["seen"][0]["mac"] == "C5:02:F5:0D:CA:BA"

        isolated_hub.adapters_info = [
            {"id": "hci0", "name": "hci0", "kind": "builtin", "default": True},
            {"id": "hci1", "name": "hci1", "kind": "usb"},
        ]
        isolated_hub.adapter_prefer = "all"
        _, radios = _get(origin, "/api/adapters")
        assert radios["ok"] is True
        assert len(radios["adapters"]) == 2
        assert radios["prefer"] == "all"

        disc = Request(origin + "/api/disconnect/key", data=b"{}", method="POST")
        with urlopen(disc, timeout=3) as res:
            dropped = json.loads(res.read().decode())
        assert dropped["ok"] is True
        assert dropped["disconnect"] == "key"
        assert isolated_hub.disconnect_macs

        _, one = _get(origin, "/api/lights/key")
        assert one["id"] == "key"
        assert "ha" in one

        _, disco = _get(origin, "/api/discovery")
        assert disco["name"] == "CineNode"
        assert "/api/health" in disco["health"]

        home = urlopen(origin + "/", timeout=3)
        html = home.read().decode()
        assert "CineNode" in html
        assert "Home Assistant is not required" in html
        assert home.headers.get("Content-Type", "").startswith("text/html")

        scan_req = Request(origin + "/api/scan", data=b"{}", method="POST")
        with urlopen(scan_req, timeout=3) as res:
            scanned = json.loads(res.read().decode())
        assert scanned["ok"] is True
        assert isolated_hub.scan_requested is True

        agent = urlopen(origin + "/agent.md", timeout=3).read().decode()
        assert "exactly ONE" in agent
        mcp_info = json.loads(urlopen(origin + "/mcp", timeout=3).read().decode())
        assert "list_lights" in mcp_info["tools"]
        assert "list_seen" in mcp_info["tools"]
        assert "connect_light" in mcp_info["tools"]
        mcp_req = Request(
            origin + "/mcp",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(mcp_req, timeout=3) as res:
            listed = json.loads(res.read().decode())
        assert listed["result"]["tools"][0]["name"]

        isolated_hub.api_key = "secret"
        try:
            urlopen(Request(origin + "/api/lights/key", data=b"{}", method="POST"), timeout=3)
            raise AssertionError("expected 401")
        except HTTPError as exc:
            assert exc.code == 401
        keyed = Request(
            origin + "/api/lights/key",
            data=json.dumps({"state": "ON"}).encode(),
            headers={"Content-Type": "application/json", "X-CineNode-Key": "secret"},
            method="POST",
        )
        with urlopen(keyed, timeout=3) as res:
            assert json.loads(res.read().decode())["power"] is True
        isolated_hub.api_key = ""

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
