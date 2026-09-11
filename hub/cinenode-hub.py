#!/usr/bin/env python3
"""CineNode local hub — Neewer BLE + REST + Home Assistant MQTT subscribe.

Run on the machine that has Bluetooth (native Windows, macOS, or Linux — not WSL):

    python cinenode-hub.py --mqtt mqtt://homeassistant.local:1883

Home Assistant JSON lights publish to cinenode/<id>/set. This hub listens,
writes HSI / CCT / scene frames over GATT, and publishes state back.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse

SERVICE = "69400001-b5a3-f393-e0a9-e50e24dcca99"
WRITE = "69400002-b5a3-f393-e0a9-e50e24dcca99"
NOTIFY = "69400003-b5a3-f393-e0a9-e50e24dcca99"

SCENES = {
    1: "Cop Car",
    2: "Ambulance",
    3: "Fire Truck",
    4: "Fireworks",
    5: "Party",
    6: "Candlelight",
    7: "Lightning",
    8: "Paparazzi",
    9: "TV Screen",
}
SCENE_BY_NAME = {name.lower(): sid for sid, name in SCENES.items()}


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def frame(*parts: int) -> bytes:
    body = bytes(parts)
    return body + bytes([checksum(body)])


def power_frame(on: bool) -> bytes:
    return frame(0x78, 0x81, 0x01, 0x01 if on else 0x02)


def hsi_frame(hue: int, sat: int, bri: int) -> bytes:
    hue = max(0, min(360, int(hue)))
    hue_lo = hue if hue <= 255 else hue - 256
    hue_hi = 0 if hue <= 255 else 1
    return frame(0x78, 0x86, 0x04, hue_lo, hue_hi, max(0, min(100, int(sat))), max(0, min(100, int(bri))))


def cct_frame(bri: int, kelvin: int) -> bytes:
    return frame(0x78, 0x87, 0x02, max(0, min(100, int(bri))), max(0, min(255, int(kelvin) // 100)))


def scene_frame(bri: int, scene_id: int) -> bytes:
    return frame(0x78, 0x88, 0x02, max(0, min(100, int(bri))), max(1, min(17, int(scene_id))))


def rgb_to_hs(r: float, g: float, b: float) -> tuple[float, float]:
    rr, gg, bb = [max(0.0, min(255.0, float(v))) / 255.0 for v in (r, g, b)]
    mx, mn = max(rr, gg, bb), min(rr, gg, bb)
    d = mx - mn
    h = 0.0
    if d:
        if mx == rr:
            h = ((gg - bb) / d) % 6
        elif mx == gg:
            h = (bb - rr) / d + 2
        else:
            h = (rr - gg) / d + 4
        h *= 60
        if h < 0:
            h += 360
    s = 0.0 if mx == 0 else (d / mx) * 100
    return h, s


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _brightness(value: Any) -> int | None:
    n = _num(value)
    if n is None:
        return None
    if n <= 100:
        return int(round(max(0.0, min(100.0, n))))
    return int(round(max(0.0, min(100.0, n * 100.0 / 255.0))))


def effect_to_scene(effect: str) -> int | None:
    raw = effect.strip().lower()
    if not raw:
        return None
    if raw in SCENE_BY_NAME:
        return SCENE_BY_NAME[raw]
    m = re.match(r"^(?:scene\s*)?(\d+)$", raw)
    if m:
        sid = int(m.group(1))
        return sid if 1 <= sid <= 17 else None
    return None


def parse_ha_command(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    patch: dict[str, Any] = {}
    if isinstance(body.get("power"), bool):
        patch["power"] = body["power"]
    if body.get("mode") in ("cct", "hsi", "scene"):
        patch["mode"] = body["mode"]
    if isinstance(body.get("connected"), bool):
        patch["connected"] = body["connected"]
    for key in ("brightness", "kelvin", "gm", "hue", "saturation", "sceneId"):
        n = _num(body.get(key))
        if n is not None:
            patch[key] = n

    state = body.get("state")
    if isinstance(state, str):
        low = state.strip().lower()
        if low in ("on", "true", "1"):
            patch["power"] = True
        elif low in ("off", "false", "0"):
            patch["power"] = False

    bri = _brightness(body.get("brightness", body.get("brightness_pct")))
    if bri is not None:
        patch["brightness"] = bri
        patch.setdefault("power", True)

    color_mode = str(body.get("color_mode") or "").lower()
    prefer_hs = color_mode in ("hs", "rgb", "xy")
    prefer_cct = color_mode in ("color_temp", "colour_temp")

    kelvin = _num(body.get("color_temp_kelvin"))
    mireds = _num(body.get("color_temp"))
    if kelvin is None and mireds and mireds > 0:
        kelvin = 1_000_000.0 / mireds
    if kelvin is not None and (prefer_cct or not prefer_hs) and patch.get("mode") not in ("hsi", "scene"):
        patch["kelvin"] = int(round(kelvin))
        patch["mode"] = "cct"
        patch.setdefault("power", True)

    color = body.get("color")
    if isinstance(color, dict) and (prefer_hs or not prefer_cct):
        h, s = _num(color.get("h")), _num(color.get("s"))
        if h is not None and s is not None:
            patch["hue"] = h
            patch["saturation"] = s
            patch["mode"] = "hsi"
            patch.setdefault("power", True)
        else:
            r, g, b = _num(color.get("r")), _num(color.get("g")), _num(color.get("b"))
            if r is not None and g is not None and b is not None:
                hh, ss = rgb_to_hs(r, g, b)
                patch["hue"] = hh
                patch["saturation"] = ss
                patch["mode"] = "hsi"
                patch.setdefault("power", True)

    hs_color = body.get("hs_color")
    if isinstance(hs_color, (list, tuple)) and len(hs_color) >= 2 and (prefer_hs or not prefer_cct):
        h, s = _num(hs_color[0]), _num(hs_color[1])
        if h is not None and s is not None:
            patch["hue"] = h
            patch["saturation"] = s
            patch["mode"] = "hsi"
            patch.setdefault("power", True)

    rgb = body.get("rgb_color")
    if isinstance(rgb, (list, tuple)) and len(rgb) >= 3 and (prefer_hs or not prefer_cct):
        r, g, b = _num(rgb[0]), _num(rgb[1]), _num(rgb[2])
        if r is not None and g is not None and b is not None:
            hh, ss = rgb_to_hs(r, g, b)
            patch["hue"] = hh
            patch["saturation"] = ss
            patch["mode"] = "hsi"
            patch.setdefault("power", True)

    if isinstance(body.get("effect"), str):
        sid = effect_to_scene(body["effect"])
        if sid:
            patch["mode"] = "scene"
            patch["sceneId"] = sid
            patch.setdefault("power", True)
    return patch


def ha_state(light: dict[str, Any]) -> dict[str, Any]:
    on = bool(light.get("connected") and light.get("power"))
    payload: dict[str, Any] = {
        "state": "ON" if on else "OFF",
        "brightness": int(round(max(0, min(100, float(light.get("brightness") or 0))))),
    }
    mode = light.get("mode")
    if mode == "hsi":
        payload["color_mode"] = "hs"
        payload["color"] = {"h": int(round(light.get("hue") or 0)), "s": int(round(light.get("saturation") or 0))}
    elif mode == "scene":
        payload["color_mode"] = "hs"
        payload["color"] = {"h": int(round(light.get("hue") or 0)), "s": int(round(light.get("saturation") or 0))}
        payload["effect"] = SCENES.get(int(light.get("sceneId") or 1), "Party")
    else:
        kelvin = max(1, int(light.get("kelvin") or 5600))
        payload["color_mode"] = "color_temp"
        payload["color_temp"] = int(round(1_000_000 / kelvin))
        payload["color_temp_kelvin"] = kelvin
    return payload


def parse_broker(url: str) -> tuple[str, int, bool, str | None, str | None]:
    raw = url.strip()
    if "://" not in raw:
        raw = "mqtt://" + raw
    parsed = urlparse(raw)
    tls = parsed.scheme in ("mqtts", "ssl", "tls")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (8883 if tls else 1883)
    user = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    return host, port, tls, user, password


def new_light(**kwargs: Any) -> dict[str, Any]:
    now = int(time.time() * 1000)
    light = {
        "id": "key",
        "name": "Key",
        "model": "RGB660 PRO",
        "modelCode": "RGB660PRO",
        "mac": "",
        "connected": False,
        "power": False,
        "mode": "cct",
        "brightness": 70,
        "kelvin": 5600,
        "gm": 0,
        "hue": 30,
        "saturation": 0,
        "sceneId": 1,
        "lastSeen": now,
        "rssi": None,
        "rgb": True,
        "cctRange": [3200, 5600],
        "lightType": 0,
        "cctOnly": False,
    }
    light.update(kwargs)
    return light


DEMO = [
    new_light(id="key", name="Key", model="RGB660 PRO", connected=False),
]


def stable_id(mac: str, name: str, index: int) -> str:
    hexid = re.sub(r"[^0-9A-Fa-f]", "", mac)[-6:]
    if hexid:
        return "n" + hexid.lower()
    slug = re.sub(r"[^a-z0-9]+", "", (name or "light").lower())[:8] or "light"
    return f"{slug}{index}"


class Hub:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.lights = [dict(x) for x in DEMO]
        self.clients: dict[str, Any] = {}
        self.pending: dict[str, bytes] = {}
        self.revision = 1
        self.loop: asyncio.AbstractEventLoop | None = None
        self.mqtt_status = "disabled"
        self.on_change = lambda: None
        self.simulator = False

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "ok": True,
                "revision": self.revision,
                "mqtt": self.mqtt_status,
                "simulator": self.simulator,
                "lights": [dict(item) for item in self.lights],
            }

    def patch(self, light_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
        parsed = parse_ha_command(body)
        with self.lock:
            targets = self.lights if light_id in ("all", "hub", "*") else [l for l in self.lights if l["id"] == light_id]
            if not targets and light_id not in ("all", "hub", "*"):
                return None
            updated = None
            for light in targets:
                for key, value in parsed.items():
                    light[key] = value
                light["lastSeen"] = int(time.time() * 1000)
                pkt = self._packet(light)
                mac = light.get("mac") or ""
                if mac:
                    self.pending[mac] = pkt
                updated = dict(light)
            self.revision += 1
        self.on_change()
        return updated

    def _packet(self, light: dict[str, Any]) -> bytes:
        if not light.get("power"):
            return power_frame(False)
        mode = light.get("mode")
        if mode == "hsi":
            return hsi_frame(light.get("hue") or 0, light.get("saturation") or 0, light.get("brightness") or 0)
        if mode == "scene":
            return scene_frame(light.get("brightness") or 100, light.get("sceneId") or 1)
        return cct_frame(light.get("brightness") or 0, light.get("kelvin") or 5600)

    def drain_writes(self) -> list[tuple[str, bytes]]:
        with self.lock:
            items = list(self.pending.items())
            self.pending.clear()
            return items

    def set_lights(self, lights: list[dict[str, Any]], simulator: bool) -> None:
        with self.lock:
            self.lights = lights
            self.simulator = simulator
            self.revision += 1
        self.on_change()

    def mark(self, mac: str, **fields: Any) -> None:
        with self.lock:
            for light in self.lights:
                if light.get("mac") == mac:
                    light.update(fields)
                    light["lastSeen"] = int(time.time() * 1000)
            self.revision += 1


HUB = Hub()


def mqtt_docs(origin: str, prefix: str) -> list[dict[str, Any]]:
    docs = []
    snap = HUB.snapshot()
    for light in snap["lights"]:
        unique = f"cinenode_{light['id']}"
        docs.append(
            {
                "topic": f"{prefix}/light/{unique}/config",
                "payload": {
                    "name": light["name"],
                    "unique_id": unique,
                    "schema": "json",
                    "command_topic": f"cinenode/{light['id']}/set",
                    "state_topic": f"cinenode/{light['id']}/state",
                    "brightness": True,
                    "brightness_scale": 100,
                    "color_mode": True,
                    "supported_color_modes": ["hs", "color_temp"] if light.get("rgb") else ["color_temp"],
                    "min_mireds": 153,
                    "max_mireds": 370,
                    "effect": True,
                    "effect_list": list(SCENES.values()),
                    "availability_topic": "cinenode/hub/availability",
                    "payload_available": "online",
                    "payload_not_available": "offline",
                    "device": {
                        "identifiers": ["cinenode_hub"],
                        "name": "CineNode",
                        "manufacturer": "CineNode",
                        "model": "Local lighting hub",
                        "sw_version": "1.1.0",
                    },
                    "origin": {"name": "CineNode", "url": origin},
                },
            }
        )
    return docs


class MqttBridge:
    def __init__(self, broker: str, user: str | None, password: str | None, prefix: str, origin_fn: Any) -> None:
        self.broker = broker
        self.user = user
        self.password = password
        self.prefix = prefix or "homeassistant"
        self.origin_fn = origin_fn
        self.client: Any = None

    def start(self) -> None:
        if not self.broker:
            HUB.mqtt_status = "disabled"
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            print("paho-mqtt not installed — REST only (pip install paho-mqtt)", file=sys.stderr)
            HUB.mqtt_status = "missing"
            return

        host, port, tls, url_user, url_password = parse_broker(self.broker)
        user = self.user or url_user
        password = self.password or url_password
        client_id = "cinenode-hub"

        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        except Exception:
            client = mqtt.Client(client_id=client_id)

        if user:
            client.username_pw_set(user, password or "")
        if tls:
            client.tls_set()
        client.will_set("cinenode/hub/availability", "offline", retain=True, qos=1)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        HUB.mqtt_status = "connecting"
        print(f"MQTT connecting {host}:{port} (HA color wheel listens on cinenode/+/set)")
        try:
            client.connect_async(host, port, 60)
            client.loop_start()
            self.client = client
            HUB.on_change = self.publish_states
        except Exception as exc:  # noqa: BLE001
            HUB.mqtt_status = "error"
            print("MQTT connect failed:", exc, file=sys.stderr)

    def _on_connect(self, client: Any, _userdata: Any, _flags: Any, reason_code: Any, *_rest: Any) -> None:
        rc = getattr(reason_code, "value", reason_code)
        if rc not in (0, "Success"):
            HUB.mqtt_status = "error"
            print("MQTT refused:", reason_code, file=sys.stderr)
            return
        HUB.mqtt_status = "connected"
        client.subscribe("cinenode/+/set", qos=0)
        client.subscribe("cinenode/hub/set", qos=0)
        client.subscribe(f"{self.prefix}/status", qos=0)
        client.publish("cinenode/hub/availability", "online", retain=True, qos=1)
        self.publish_all()
        print("MQTT connected — Home Assistant can set color on the fly")

    def _on_disconnect(self, _client: Any, _userdata: Any, *args: Any) -> None:
        if HUB.mqtt_status != "disabled":
            HUB.mqtt_status = "connecting"

    def _on_message(self, _client: Any, _userdata: Any, msg: Any) -> None:
        topic = str(msg.topic)
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        if topic.endswith("/status") and payload.lower() == "online":
            self.publish_all()
            return
        parts = topic.split("/")
        if len(parts) < 3 or parts[0] != "cinenode" or parts[-1] != "set":
            return
        light_id = parts[1]
        if payload in ("ON", "OFF", "on", "off"):
            body: Any = {"state": payload}
        else:
            try:
                body = json.loads(payload or "{}")
            except json.JSONDecodeError:
                print("bad MQTT payload", payload, file=sys.stderr)
                return
        updated = HUB.patch(light_id, body if isinstance(body, dict) else {})
        if updated is None:
            print("MQTT unknown light", light_id, file=sys.stderr)

    def publish_states(self) -> None:
        client = self.client
        if client is None:
            return
        try:
            client.publish("cinenode/hub/availability", "online", retain=True, qos=1)
            for light in HUB.snapshot()["lights"]:
                client.publish(
                    f"cinenode/{light['id']}/state",
                    json.dumps(ha_state(light)),
                    retain=True,
                    qos=0,
                )
        except Exception as exc:  # noqa: BLE001
            print("MQTT state publish failed", exc, file=sys.stderr)

    def publish_all(self) -> None:
        client = self.client
        if client is None:
            return
        origin = self.origin_fn()
        try:
            for doc in mqtt_docs(origin, self.prefix):
                client.publish(doc["topic"], json.dumps(doc["payload"]), retain=True, qos=1)
            self.publish_states()
        except Exception as exc:  # noqa: BLE001
            print("MQTT publish failed", exc, file=sys.stderr)


class Handler(BaseHTTPRequestHandler):
    prefix = "homeassistant"
    origin_override = ""

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        sys.stderr.write("hub %s\n" % (fmt % args))

    def _origin(self) -> str:
        if self.origin_override:
            return self.origin_override
        host = self.headers.get("Host", "127.0.0.1")
        return f"http://{host}"

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CineNode-Key")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, b"")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        origin = self._origin()
        snap = HUB.snapshot()
        if path in ("/api/health", "/"):
            self._send(
                200,
                json.dumps(
                    {
                        "ok": True,
                        "name": "cinenode",
                        "revision": snap["revision"],
                        "mqtt": snap["mqtt"],
                        "simulator": snap["simulator"],
                        "connected": sum(1 for l in snap["lights"] if l.get("connected")),
                        "lights": len(snap["lights"]),
                    }
                ).encode(),
            )
            return
        if path == "/api/lights":
            self._send(200, json.dumps(snap).encode())
            return
        if path.startswith("/api/lights/"):
            light_id = path.rsplit("/", 1)[-1]
            light = next((l for l in snap["lights"] if l["id"] == light_id), None)
            if not light:
                self._send(404, b'{"error":"not found"}')
                return
            body = dict(light)
            body["ha"] = ha_state(light)
            self._send(200, json.dumps(body).encode())
            return
        if path == "/api/ha/mqtt":
            self._send(
                200,
                json.dumps(
                    {
                        "status": snap["mqtt"],
                        "subscribe": ["cinenode/+/set", "cinenode/hub/set"],
                        "availability": "cinenode/hub/availability",
                        "documents": mqtt_docs(origin, self.prefix),
                    }
                ).encode(),
            )
            return
        if path == "/api/discovery":
            self._send(
                200,
                json.dumps({"name": "CineNode", "origin": origin, "health": origin + "/api/health"}).encode(),
            )
            return
        self._send(404, b'{"error":"not found"}')

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            body = {}
        if path.startswith("/api/lights/"):
            light_id = path.rsplit("/", 1)[-1]
            light = HUB.patch(light_id, body if isinstance(body, dict) else {})
            if not light:
                self._send(404, b'{"error":"not found"}')
                return
            payload = dict(light)
            payload["ha"] = ha_state(light)
            self._send(200, json.dumps(payload).encode())
            return
        self._send(404, b'{"error":"not found"}')

    do_PUT = do_POST


def looks_like_neewer(device: Any, adv: Any) -> bool:
    name = f"{getattr(device, 'name', '') or ''} {getattr(adv, 'local_name', '') or ''}"
    upper = name.upper()
    uuids = [str(u).lower() for u in (getattr(adv, "service_uuids", None) or [])]
    return (
        "NEEWER" in upper
        or "NW-" in upper
        or upper.strip().startswith("SL")
        or SERVICE.lower() in uuids
    )


async def ble_worker() -> None:
    HUB.loop = asyncio.get_running_loop()
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError:
        print("bleak not installed — simulator only (pip install bleak)", file=sys.stderr)
        with HUB.lock:
            for light in HUB.lights:
                light["connected"] = True
                light["mac"] = light.get("mac") or "SIM"
            HUB.simulator = True
            HUB.revision += 1
        HUB.on_change()
        while True:
            await asyncio.sleep(1)
        return

    print("scanning for NEEWER / NW- advertisements…")
    found: dict[str, Any] = {}

    def _cb(device: Any, adv: Any) -> None:
        if looks_like_neewer(device, adv):
            found[device.address] = device

    try:
        scanner = BleakScanner(detection_callback=_cb)
        await scanner.start()
        await asyncio.sleep(8)
        await scanner.stop()
    except Exception as exc:  # noqa: BLE001
        print("BLE scan failed:", exc, file=sys.stderr)
        print("On Windows use native Python (not WSL). Close the Neewer app.", file=sys.stderr)
        found.clear()

    if found:
        lights = []
        for i, device in enumerate(found.values(), start=1):
            lights.append(
                new_light(
                    id=stable_id(device.address, device.name or "", i),
                    name=device.name or f"Light {i}",
                    model=device.name or "Neewer",
                    modelCode=device.name or "Neewer",
                    mac=device.address,
                    connected=False,
                    power=True,
                    brightness=50,
                )
            )
        HUB.set_lights(lights, simulator=False)
    else:
        print("no Neewer advertisements — simulator mode (HA color commands still apply)")
        with HUB.lock:
            for light in HUB.lights:
                light["connected"] = True
                light["mac"] = light.get("mac") or "SIM"
            HUB.simulator = True
            HUB.revision += 1
        HUB.on_change()

    for light in list(HUB.snapshot()["lights"]):
        mac = light.get("mac") or ""
        if not mac or mac == "SIM":
            continue
        try:
            client = BleakClient(mac)
            await client.connect()
            HUB.clients[mac] = client
            HUB.mark(mac, connected=True)
            print("connected", light["name"], mac)
        except Exception as exc:  # noqa: BLE001
            print("connect failed", mac, exc, file=sys.stderr)

    HUB.on_change()

    while True:
        for mac, pkt in HUB.drain_writes():
            client = HUB.clients.get(mac)
            if client is None:
                continue
            try:
                if not client.is_connected:
                    await client.connect()
                    HUB.mark(mac, connected=True)
                await client.write_gatt_char(WRITE, pkt, response=False)
            except Exception as exc:  # noqa: BLE001
                print("write failed", mac, exc, file=sys.stderr)
                HUB.mark(mac, connected=False)
        await asyncio.sleep(0.04)


def lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def load_config(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        print("could not read", path, exc, file=sys.stderr)
        return {}


def self_test() -> int:
    failures = 0

    def check(name: str, cond: bool) -> None:
        nonlocal failures
        if not cond:
            print("FAIL", name)
            failures += 1
        else:
            print("ok  ", name)

    check("power on", power_frame(True).hex(" ") == "78 81 01 01 fb")
    check("power off", power_frame(False).hex(" ") == "78 81 01 02 fc")
    check("hsi 88", hsi_frame(88, 24, 100).hex(" ") == "78 86 04 58 00 18 64 d6")
    check("cct 5600", cct_frame(100, 5600).hex(" ") == "78 87 02 64 38 9d")
    hs = parse_ha_command({"state": "ON", "brightness": 80, "color": {"h": 210, "s": 70}})
    check("ha hs", hs.get("mode") == "hsi" and hs.get("hue") == 210 and hs.get("brightness") == 80)
    cct = parse_ha_command({"state": "ON", "color_temp": 153})
    check("ha cct", cct.get("mode") == "cct" and cct.get("kelvin") == round(1_000_000 / 153))
    scene = parse_ha_command({"effect": "Party"})
    check("ha effect", scene.get("sceneId") == 5 and scene.get("mode") == "scene")
    off = parse_ha_command({"state": "OFF"})
    check("ha off", off.get("power") is False)
    scale = parse_ha_command({"brightness": 204})
    check("bri 255 scale", scale.get("brightness") == 80)
    return 1 if failures else 0


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = load_config(os.path.join(here, "cinenode.json"))
    parser = argparse.ArgumentParser(description="CineNode local lighting hub")
    parser.add_argument("--host", default=str(cfg.get("host") or "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(cfg.get("port") or 8787))
    parser.add_argument("--mqtt", default=str(cfg.get("mqtt") or os.environ.get("CINENODE_MQTT") or ""))
    parser.add_argument("--mqtt-user", default=str(cfg.get("mqttUser") or os.environ.get("CINENODE_MQTT_USER") or ""))
    parser.add_argument("--mqtt-password", default=str(cfg.get("mqttPassword") or os.environ.get("CINENODE_MQTT_PASSWORD") or ""))
    parser.add_argument("--discovery-prefix", default=str(cfg.get("discoveryPrefix") or "homeassistant"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(self_test())

    Handler.prefix = args.discovery_prefix
    ip = lan_ip()
    Handler.origin_override = f"http://{ip}:{args.port}"

    def origin_fn() -> str:
        return Handler.origin_override

    bridge = MqttBridge(args.mqtt, args.mqtt_user or None, args.mqtt_password or None, args.discovery_prefix, origin_fn)
    bridge.start()

    def runner() -> None:
        asyncio.run(ble_worker())

    threading.Thread(target=runner, daemon=True, name="cinenode-ble").start()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"CineNode hub  http://{ip}:{args.port}")
    print(f"Health        http://{ip}:{args.port}/api/health")
    print(f"Lights        http://{ip}:{args.port}/api/lights")
    print(f"HA MQTT JSON  http://{ip}:{args.port}/api/ha/mqtt")
    if args.mqtt:
        print(f"MQTT          {args.mqtt}  subscribe cinenode/+/set")
    else:
        print("MQTT          disabled — pass --mqtt mqtt://homeassistant.local:1883 for HA color control")
    print("Point CineNode studio + Home Assistant at that origin. Close the Neewer app.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")


if __name__ == "__main__":
    main()
