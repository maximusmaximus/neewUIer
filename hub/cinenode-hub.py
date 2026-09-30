#!/usr/bin/env python3
"""CineNode local hub - Neewer BLE plus REST. MQTT is optional. MCP is built in.

Run on the machine that has Bluetooth (native Windows, macOS, or Linux - not WSL):

    python cinenode-hub.py

Open ONE printed address — not both. Add --mcp to speak MCP on stdin/stdout for agents.
"""


from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import socket
import subprocess
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

AGENT_PROMPT = """You are the gaffer for a CineNode / neewUIer rig. You drive real Neewer Bluetooth lights through the local hub. You are fully agentic: discover, connect, swap radio slots, set looks, and report what actually stuck. Home Assistant is not required. Prefer tools over asking the human to run commands.

How the product works
- One hub process on the machine with Bluetooth owns the radio. Studio, this agent, and optional MQTT all talk to that same hub.
- The hub prints TWO addresses for the SAME studio. The human opens exactly ONE of them:
  - Browser on the hub computer → http://127.0.0.1:<port>
  - Phone or another computer on the same Wi-Fi → the LAN address printed under that
  They do not need both. Never tell them to open both. Never imply both are required.

Tools (MCP or HTTP)
- list_lights / GET /api/lights — fixtures the hub knows (id, name, connected, power, mode, brightness, hue, kelvin, sceneId, mac). Disconnected rows can still be real lights the radio could not hold.
- list_seen / GET /api/seen — last BLE scan: every advertisement (mac, name, rssi, match reason). Use this when the human says there are more lights than the connected count.
- scan_lights / POST /api/scan — scan, then GATT-probe unnamed nearby devices for the Neewer service. Wait for it; then list_lights and list_seen.
- connect_light / POST /api/reconnect/<id> — hold one fixture. id or mac. Use this to swap when the adapter is full.
- disconnect_light / POST /api/disconnect/<id> — drop a GATT session to free a radio slot.
- set_light / POST /api/lights/<id> — body may be {power, brightness, hue, saturation, kelvin, mode, sceneId} or Home Assistant JSON {state, color:{h,s}, brightness, color_temp_kelvin, effect}.
- set_all / POST /api/lights/all — same body applied to every held fixture.
- hub_health / GET /api/health
- list_adapters / GET /api/adapters — Bluetooth radios. Windows Bleak only listens on the DEFAULT radio; a USB dongle is preferred over Intel built-in.

Operating rules
1. Call list_lights before any look. Use only ids the hub returned. Never invent fixture ids or MAC addresses.
2. If the list is empty or the human says lights are missing, scan_lights, then list_seen. The official Neewer app must be closed or it steals the GATT session.
3. Connected lights stop advertising. A later scan that finds nothing new is normal. Do not tell the user the rig vanished.
4. Windows often hides the local name. Unnamed nearby devices are probed for service 69400001-…. That is expected and can take a minute. Do not abort it.
5. One PC Bluetooth adapter often holds about 3-8 connections. Cheap dongles stop at 3. If many more exist, connect what you can, say the adapter is full, keep extras in the list as disconnected, and offer connect_light / disconnect_light to swap.
6. Prefer set_all for a whole-rig look. Prefer set_light to isolate key / fill / hair / tubes.
7. HSI: hue 0-360, saturation 0-100, brightness 0-100. CCT: kelvin typically 2700-7500. Scenes 1-17 (1 Cop Car, 5 Party, 6 Candlelight).
8. After a change the user cares about, list_lights again and report what actually stuck.
9. If a write fails, say the hub is down or that fixture is offline. Do not pretend the color changed.
10. Do not blackout the room unless asked. Do not enable MQTT/Home Assistant unless asked.
11. Keep replies short and concrete: which ids, which numbers, what is still offline, whether the radio is full.
12. PCs with two radios (Intel + USB dongle) only scan the default radio unless --adapter all. If lights are missing on Windows, list_adapters and tell the human to disable the unused radio in Device Manager or rerun with --adapter all.
"""

MODEL_NAME = re.compile(
    r"(NEEWER|NEEWEAR|NW[-_ ]|RGB[- ]?\d+|TL[- ]?\d+|GL[- ]?\d|CB[- ]?\d+|BH[- ]?\d|HS[- ]?\d+|HB[- ]?\d+|MS[- ]?\d+|MC[- ]?\d+|SL[- ]?\d|SNL[- ]?\d|NL[- ]?\d|FS[- ]?\d+|PX[- ]?\d+|PL[- ]?\d+|CL[- ]?\d+|C80|SRP\d|WRP\d|ZRP\d|\b20[2-3]\d{5}\b)",
    re.I,
)
NOT_LIGHT = re.compile(
    r"(airpods|iphone|ipad|ipod|macbook|imac|\bwatch\b|galaxy|pixel\b|oneplus|bose|sony|jbl|beats|wh-\d|wf-\d|\btv\b|samsung|xbox|playstation|nintendo|logitech|keyboard|mouse|headset|headphone|huawei|xiaomi|mi band|fitbit|garmin|\btile\b|\becho\b|alexa|homepod|chromecast|roku|kindle|surface|philips|\bhue\b|lifx|tradfri|ikea|yeelight|govee|tuya|wled|airtag)",
    re.I,
)
RADIO_FULL = re.compile(r"(out of resource|not enough resources|connection limit|error 19|max connection)", re.I)
# Company IDs that are almost never a Neewer fixture. Probe budget is wasted on these.
PHONE_MFG = frozenset(
    {
        0x004C,  # Apple
        0x0006,  # Microsoft
        0x0075,  # Samsung
        0x00E0,  # Google
        0x00D2,
        0x0157,  # Huami / Amazfit
        0x02E5,  # Tile
        0x012D,  # Sony
        0x00D0,  # Garmin
        0x0078,  # Nike
    }
)


def ready_banner(port: int, ip: str, host: str) -> str:
    local = f"http://127.0.0.1:{port}"
    lines = [
        "CineNode hub is ready.",
        "",
        "Open exactly ONE URL. They are the same studio.",
        "Pick based on where the browser is. You do not need both.",
        "",
        "  IF the browser is on THIS computer:",
        f"      {local}",
    ]
    lan_ok = host in ("0.0.0.0", "::", ip) and ip not in ("127.0.0.1", "0.0.0.0")
    if lan_ok:
        lines.extend(
            [
                "",
                "  IF the browser is on a PHONE or another computer on the same Wi-Fi:",
                f"      http://{ip}:{port}",
                "",
                "Do not open both. One tab is enough.",
            ]
        )
    else:
        lines.extend(["", "This hub is only reachable on this computer."])
    return "\n".join(lines)


def normalize_mac(mac: str) -> str:
    hexid = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    if len(hexid) < 12:
        return ""
    hexid = hexid[-12:].upper()
    return ":".join(hexid[i : i + 2] for i in range(0, 12, 2))


def known_path(base: str | None = None) -> str:
    here = base or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "cinenode-known.json")


def load_known(path: str | None = None) -> dict[str, dict[str, Any]]:
    data = load_config(path or known_path())
    raw = data.get("macs") if isinstance(data.get("macs"), dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for mac, meta in raw.items():
        key = normalize_mac(str(mac))
        out[key] = meta if isinstance(meta, dict) else {"name": str(meta)}
    return out


def remember_mac(store: dict[str, dict[str, Any]], mac: str, name: str = "") -> dict[str, dict[str, Any]]:
    key = normalize_mac(mac)
    if not key:
        return store
    current = dict(store.get(key) or {})
    if name:
        current["name"] = name
    current["lastSeen"] = int(time.time() * 1000)
    store[key] = current
    return store


def save_known(store: dict[str, dict[str, Any]], path: str | None = None) -> None:
    dest = path or known_path()
    payload = {"macs": store}
    tmp = dest + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, dest)
    except OSError as exc:
        print("could not save known lights", dest, exc, file=sys.stderr)


def _adv_name(device: Any, adv: Any) -> str:
    return f"{getattr(device, 'name', '') or ''} {getattr(adv, 'local_name', '') or ''}".strip()


def _adv_uuids(adv: Any) -> list[str]:
    return [str(u).lower() for u in (getattr(adv, "service_uuids", None) or [])]


def _mfg_map(adv: Any) -> dict[Any, bytes]:
    raw = getattr(adv, "manufacturer_data", None) or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[Any, bytes] = {}
    for key, payload in raw.items():
        try:
            out[key] = bytes(payload or b"")
        except Exception:
            continue
    return out


def _adv_text(device: Any, adv: Any) -> str:
    chunks = [_adv_name(device, adv)]
    for payload in _mfg_map(adv).values():
        chunks.append(payload.decode("ascii", "ignore"))
        chunks.append(payload.decode("latin-1", "ignore"))
    for uuid, payload in (getattr(adv, "service_data", None) or {}).items():
        chunks.append(str(uuid))
        try:
            chunks.append(bytes(payload or b"").decode("ascii", "ignore"))
        except Exception:
            pass
    return " ".join(chunk for chunk in chunks if chunk)


def match_reason(device: Any, adv: Any, known: dict[str, Any] | set[str] | None = None) -> str:
    text = _adv_text(device, adv)
    uuids = _adv_uuids(adv)
    mac = normalize_mac(getattr(device, "address", "") or "")
    if SERVICE.lower() in uuids:
        return "service"
    if known is not None and mac and mac in known:
        return "known"
    if MODEL_NAME.search(text):
        return "name" if MODEL_NAME.search(_adv_name(device, adv)) else "mfg"
    return ""


def is_phone_adv(device: Any, adv: Any) -> bool:
    name = _adv_name(device, adv)
    if name and NOT_LIGHT.search(name):
        return True
    ids = set()
    for key in _mfg_map(adv):
        try:
            ids.add(int(key))
        except (TypeError, ValueError):
            continue
    if ids and ids <= PHONE_MFG:
        return True
    if 0x004C in ids and not MODEL_NAME.search(_adv_text(device, adv)):
        return True
    return False


def is_probe_candidate(device: Any, adv: Any, known: dict[str, Any] | set[str] | None = None) -> bool:
    if match_reason(device, adv, known):
        return False
    if is_phone_adv(device, adv):
        return False
    return True


REASON_RANK = {"service": 5, "name": 4, "mfg": 4, "known": 3, "probe": 2, "skip": 1, "": 0}
USB_HINTS = ("usb", "dongle", "tp-link", "tplink", "realtek", "csr", "barrot", "vid_2357", "2357", "orico", "asus bt")
BUILTIN_HINTS = ("intel", "qualcomm", "atheros", "killer", "ax210", "ax211", "ax201", "ax200", "built-in", "internal")
PNP_SKIP = ("enumerator", "protocol", "avrcp", "a2dp", "hid\\", "service", "rfcomm", "bnep")


def adapter_blob(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key) or "") for key in ("id", "name", "address", "bus", "instance", "kind")).lower()


def adapter_kind(item: dict[str, Any]) -> str:
    explicit = str(item.get("kind") or "").lower()
    if explicit in ("usb", "builtin", "unknown"):
        return explicit
    blob = adapter_blob(item)
    bus = str(item.get("bus") or "").lower()
    if bus == "usb" or any(hint in blob for hint in USB_HINTS):
        return "usb"
    if bus == "pci" or any(hint in blob for hint in BUILTIN_HINTS):
        return "builtin"
    return "unknown"


def adapter_score(item: dict[str, Any]) -> int:
    blob = adapter_blob(item)
    kind = adapter_kind(item)
    score = 0
    if kind == "usb":
        score += 50
    if "2357" in blob or "tp-link" in blob or "tplink" in blob:
        score += 40
    if kind == "builtin":
        score -= 20
    if item.get("default"):
        score += 1
    if str(item.get("state") or "").lower() in ("on", "ok", "up", "started"):
        score += 2
    return score


def prefer_windows_adapter(adapters: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not adapters:
        return None
    return max(adapters, key=adapter_score)


def match_adapter(prefer: str, adapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    token = (prefer or "").strip()
    if not token or token.lower() in ("auto", "default"):
        return []
    if token.lower() in ("all", "*", "any"):
        return list(adapters)
    low = token.lower()
    hits: list[dict[str, Any]] = []
    for item in adapters:
        ident = str(item.get("id") or "").lower()
        name = str(item.get("name") or "").lower()
        address = str(item.get("address") or "").lower()
        instance = str(item.get("instance") or "").lower()
        if low in (ident, name, address) or low in adapter_blob(item) or low in instance:
            hits.append(item)
    return hits


def resolve_scan_adapters(
    prefer: str | None,
    adapters: list[dict[str, Any]] | None = None,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    listed = list(adapters or [])
    plat = platform or sys.platform
    token = (prefer or "").strip()
    matched = match_adapter(token, listed) if token else []
    if matched:
        return matched
    if plat == "win32":
        preferred = prefer_windows_adapter(listed)
        if preferred:
            return [preferred]
        return listed[:1] or [_default_adapter_row(plat)]
    if listed:
        return listed
    return [_default_adapter_row(plat)]


def scan_plan(
    prefer: str | None,
    adapters: list[dict[str, Any]] | None,
    held: int = 0,
    platform: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    listed = list(adapters or [])
    plat = platform or sys.platform
    token = (prefer or "auto").strip() or "auto"
    low = token.lower()
    explicit_one = bool(token) and low not in ("auto", "default", "all", "*", "any", "")
    if explicit_one:
        matched = match_adapter(token, listed) or resolve_scan_adapters(token, listed, plat)
        return (matched or [_default_adapter_row(plat)]), "single"
    want_all = low in ("all", "*", "any", "auto", "default", "")
    if plat == "win32":
        if want_all and len(listed) > 1 and held <= 0:
            return listed, "sequential"
        resolved = resolve_scan_adapters(token, listed, plat)
        return (resolved[:1] or listed[:1] or [_default_adapter_row(plat)]), "single"
    resolved = resolve_scan_adapters("all" if want_all else token, listed, plat)
    if len(resolved) > 1:
        return resolved, "parallel"
    return (resolved or [_default_adapter_row(plat)]), "single"


def _default_adapter_row(platform: str | None = None) -> dict[str, Any]:
    plat = platform or sys.platform
    name = "macOS Bluetooth" if plat == "darwin" else ("Windows default Bluetooth adapter" if plat == "win32" else "default")
    return {"id": None, "name": name, "platform": plat, "default": True, "kind": "unknown"}


def list_linux_adapters(sys_root: str = "/sys/class/bluetooth") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not os.path.isdir(sys_root):
        return out
    try:
        names = sorted(os.listdir(sys_root))
    except OSError:
        return out
    for name in names:
        if not name.startswith("hci"):
            continue
        path = os.path.join(sys_root, name)
        address = ""
        for rel in ("address", os.path.join("device", "address")):
            addr_file = os.path.join(path, rel)
            if os.path.isfile(addr_file):
                try:
                    with open(addr_file, encoding="utf-8") as handle:
                        address = handle.read().strip().upper()
                except OSError:
                    address = ""
                if address:
                    break
        bus = "unknown"
        try:
            real = os.path.realpath(path).lower()
        except OSError:
            real = path.lower()
        if "/usb" in real:
            bus = "usb"
        elif "/pci" in real:
            bus = "pci"
        out.append(
            {
                "id": name,
                "name": name,
                "address": address,
                "bus": bus,
                "kind": "usb" if bus == "usb" else ("builtin" if bus == "pci" else "unknown"),
                "platform": "linux",
                "default": name == "hci0",
            }
        )
    return out


def parse_windows_pnp_json(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("FriendlyName") or item.get("Name") or "").strip()
        instance = str(item.get("InstanceId") or item.get("InstanceID") or item.get("PNPDeviceID") or "").strip()
        status = str(item.get("Status") or item.get("State") or "").strip()
        if not name and not instance:
            continue
        blob = f"{name} {instance}".lower()
        if any(skip in blob for skip in PNP_SKIP):
            continue
        if "bluetooth" not in blob and "bth" not in blob and "vid_" not in blob:
            continue
        kind = adapter_kind({"name": name, "instance": instance, "bus": "usb" if ("usb" in blob or "vid_" in blob) else ""})
        out.append(
            {
                "id": instance or name,
                "name": name or instance,
                "instance": instance,
                "address": "",
                "state": status,
                "bus": "usb" if kind == "usb" else ("pci" if kind == "builtin" else ""),
                "kind": kind,
                "platform": "win32",
                "default": False,
            }
        )
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in out:
        key = str(item.get("id") or item.get("name"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    if unique:
        on = [item for item in unique if str(item.get("state") or "").lower() in ("ok", "started", "up", "on")]
        (on[0] if on else unique[0])["default"] = True
    return unique


def list_windows_adapters() -> list[dict[str, Any]]:
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$items=@();"
        "Get-PnpDevice -Class Bluetooth | ForEach-Object {"
        "  $items += [pscustomobject]@{FriendlyName=$_.FriendlyName; InstanceId=$_.InstanceId; Status=[string]$_.Status}"
        "};"
        "if (-not $items.Count) {"
        "  Get-PnpDevice | Where-Object { $_.FriendlyName -match 'Bluetooth' } | ForEach-Object {"
        "    $items += [pscustomobject]@{FriendlyName=$_.FriendlyName; InstanceId=$_.InstanceId; Status=[string]$_.Status}"
        "  }"
        "};"
        "$items | ConvertTo-Json -Compress"
    )
    raw = ""
    for exe in ("powershell", "pwsh"):
        try:
            raw = subprocess.check_output(
                [exe, "-NoProfile", "-Command", script],
                timeout=8,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            if raw.strip():
                break
        except (OSError, subprocess.SubprocessError):
            continue
    parsed = parse_windows_pnp_json(raw)
    if parsed:
        return parsed
    return [_default_adapter_row("win32")]


def list_ble_adapters() -> list[dict[str, Any]]:
    if sys.platform.startswith("linux"):
        return list_linux_adapters()
    if sys.platform == "win32":
        return list_windows_adapters()
    if sys.platform == "darwin":
        return [_default_adapter_row("darwin")]
    return [_default_adapter_row(sys.platform)]


def format_adapter_report(
    adapters: list[dict[str, Any]],
    selected: list[dict[str, Any]] | None = None,
    platform: str | None = None,
) -> str:
    plat = platform or sys.platform
    if not adapters:
        return "No Bluetooth radios listed. Bleak will use the system default."
    selected_ids = {str(item.get("id") or item.get("name") or "") for item in (selected or [])}
    lines = ["Bluetooth radios:"]
    for item in adapters:
        ident = str(item.get("id") or item.get("name") or "")
        mark = "*" if ident in selected_ids else " "
        bits = [str(item.get("name") or item.get("id") or "radio")]
        if item.get("address"):
            bits.append(str(item["address"]))
        kind = item.get("kind") or adapter_kind(item)
        if kind and kind != "unknown":
            bits.append(str(kind))
        if item.get("default"):
            bits.append("DEFAULT")
        if item.get("state"):
            bits.append(str(item["state"]))
        lines.append(f"  {mark} {'  '.join(bits)}")
    if plat == "win32":
        lines.append("Windows Bleak listens on the DEFAULT radio only. A USB dongle is preferred over Intel built-in.")
        lines.append("Missing lights: python cinenode-hub.py --adapter all")
        lines.append("Or Device Manager -> Bluetooth -> disable the unused radio so the dongle is DEFAULT.")
    elif len(adapters) > 1:
        lines.append("Scanning every listed radio and merging advertisements (stronger RSSI wins).")
    return "\n".join(lines)


def windows_dual_radio_note() -> str:
    return (
        "Two (or more) Bluetooth radios: Windows can listen on only one at a time. "
        "The hub prefers a USB dongle (TP-Link VID 2357, etc.) over Intel built-in and tries to make it DEFAULT. "
        "If lights are still missing they may sit on the other radio. Run with --adapter all "
        "(scans each radio in turn while nothing is held), or disable the unused radio in Device Manager."
    )


def scanner_kwargs(callback: Any, adapter_id: Any, platform: str | None = None) -> list[dict[str, Any]]:
    plat = platform or sys.platform
    base: dict[str, Any] = {"detection_callback": callback}
    attempts: list[dict[str, Any]] = []
    usable = adapter_id not in (None, "", "default")
    if usable and plat not in ("win32", "darwin"):
        attempts.append({**base, "scanning_mode": "active", "adapter": adapter_id})
        attempts.append({**base, "scanning_mode": "active", "bluez": {"adapter": adapter_id}})
        attempts.append({**base, "adapter": adapter_id})
        attempts.append({**base, "bluez": {"adapter": adapter_id}})
    attempts.append({**base, "scanning_mode": "active"})
    attempts.append(dict(base))
    return attempts


def open_bleak_scanner(scanner_cls: Any, callback: Any, adapter_id: Any = None, platform: str | None = None) -> Any:
    last: Exception | None = None
    for kwargs in scanner_kwargs(callback, adapter_id, platform):
        try:
            return scanner_cls(**kwargs)
        except TypeError as exc:
            last = exc
            continue
    if last:
        raise last
    raise TypeError("BleakScanner rejected every argument set")


def stronger_rssi(new: Any, old: Any) -> bool:
    if new is None:
        return False
    if old is None:
        return True
    try:
        return float(new) > float(old)
    except (TypeError, ValueError):
        return False


def gatt_busy() -> bool:
    if any(getattr(client, "is_connected", False) for client in HUB.clients.values()):
        return True
    return any(item.get("connected") for item in HUB.snapshot()["lights"])


async def select_windows_radio(wanted: dict[str, Any], adapters: list[dict[str, Any]] | None = None) -> bool:
    if sys.platform != "win32":
        return False
    if not wanted:
        return False
    if gatt_busy():
        print("not switching Bluetooth radios while lights are held")
        return False
    ok = await _winrt_select_radio(wanted, adapters or [])
    if ok:
        print(f"Windows default radio -> {wanted.get('name') or wanted.get('id')}")
        return True
    return False


async def _winrt_select_radio(wanted: dict[str, Any], adapters: list[dict[str, Any]]) -> bool:
    radios_mod = None
    for name in ("winrt.windows.devices.radios", "winrt.Windows.Devices.Radios"):
        try:
            radios_mod = __import__(name, fromlist=["Radio", "RadioKind", "RadioState"])
            break
        except Exception:
            continue
    if radios_mod is None:
        return False
    Radio = getattr(radios_mod, "Radio", None)
    RadioKind = getattr(radios_mod, "RadioKind", None)
    RadioState = getattr(radios_mod, "RadioState", None)
    if Radio is None or RadioState is None:
        return False
    try:
        getter = Radio.get_radios_async()
        radios = await getter if hasattr(getter, "__await__") else getter.get()
    except Exception:
        return False
    wanted_blob = adapter_blob(wanted)
    bluetooth_kind = getattr(RadioKind, "BLUETOOTH", getattr(RadioKind, "Bluetooth", None)) if RadioKind else None
    on_state = getattr(RadioState, "ON", getattr(RadioState, "On", None))
    off_state = getattr(RadioState, "OFF", getattr(RadioState, "Off", None))
    matched = None
    others = []
    for radio in radios or []:
        kind = getattr(radio, "kind", None)
        if bluetooth_kind is not None and kind not in (bluetooth_kind, "Bluetooth", 4):
            continue
        label = str(getattr(radio, "name", "") or "").lower()
        if wanted_blob and any(token and token in label for token in (wanted.get("name") or "", wanted.get("id") or "").lower().split() if len(token) > 2):
            matched = radio
        else:
            others.append(radio)
    if matched is None:
        for radio in radios or []:
            label = str(getattr(radio, "name", "") or "").lower()
            if any(hint in label for hint in USB_HINTS) and ("tp-link" in wanted_blob or "usb" in wanted_blob or "2357" in wanted_blob):
                matched = radio
                others = [item for item in (radios or []) if item is not radio]
                break
    if matched is None or on_state is None:
        return False
    try:
        setter = matched.set_state_async(on_state)
        if hasattr(setter, "__await__"):
            await setter
        elif hasattr(setter, "get"):
            setter.get()
        for radio in others:
            if off_state is None:
                break
            try:
                off = radio.set_state_async(off_state)
                if hasattr(off, "__await__"):
                    await off
                elif hasattr(off, "get"):
                    off.get()
            except Exception:
                continue
        await asyncio.sleep(1.2)
        return True
    except Exception as extra:  # noqa: BLE001
        print("could not switch Windows radio:", extra, file=sys.stderr)
        return False


def _bootstrap_deps() -> None:
    if "--self-test" in sys.argv:
        return
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ensure-deps.py")
    if not os.path.isfile(helper):
        return
    try:
        import bleak  # noqa: F401
        return
    except ImportError:
        pass
    print("Missing bleak - downloading hub packages...", flush=True)
    if subprocess.call([sys.executable, helper]) != 0:
        print("Continue anyway: REST still runs. BLE needs bleak.", file=sys.stderr)


_bootstrap_deps()


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
        self.lights: list[dict[str, Any]] = []
        self.clients: dict[str, Any] = {}
        self.pending: dict[str, bytes] = {}
        self.revision = 1
        self.loop: asyncio.AbstractEventLoop | None = None
        self.mqtt_status = "disabled"
        self.on_change = lambda: None
        self.simulator = False
        self.scan_requested = True
        self.reconnect_macs: set[str] = set()
        self.api_key = ""
        self.scan_seconds: float | None = None
        self.last_seen: list[dict[str, Any]] = []
        self.devices: dict[str, Any] = {}
        self.known_macs: dict[str, dict[str, Any]] = {}
        self.scanning = False
        self.disconnect_macs: set[str] = set()
        self.probe = True
        self.max_connections = 8
        self.scan_adapters: list[Any] = []
        self.adapter_prefer = "auto"
        self.adapters_info: list[dict[str, Any]] = []
        self.device_adapters: dict[str, Any] = {}
        self.scan_mode = "single"

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "ok": True,
                "revision": self.revision,
                "mqtt": self.mqtt_status,
                "simulator": self.simulator,
                "lights": [dict(item) for item in self.lights],
                "seen": [dict(item) for item in self.last_seen],
                "adapters": [dict(item) for item in self.adapters_info],
                "adapter": self.adapter_prefer,
                "scanMode": self.scan_mode,
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

    def upsert_lights(self, incoming: list[dict[str, Any]]) -> None:
        if not incoming:
            return
        with self.lock:
            by_mac = {item.get("mac"): index for index, item in enumerate(self.lights) if item.get("mac")}
            by_id = {item["id"]: index for index, item in enumerate(self.lights)}
            for light in incoming:
                mac = light.get("mac")
                idx = by_mac.get(mac) if mac else by_id.get(light["id"])
                if idx is None:
                    self.lights.append(light)
                    if mac:
                        by_mac[mac] = len(self.lights) - 1
                    by_id[light["id"]] = len(self.lights) - 1
                else:
                    current = self.lights[idx]
                    for key in ("name", "model", "modelCode", "rssi", "mac"):
                        if light.get(key) not in (None, ""):
                            current[key] = light[key]
            self.revision += 1
        self.on_change()

    def request_scan(self, seconds: float | None = None) -> None:
        self.scan_requested = True
        if seconds:
            self.scan_seconds = float(seconds)

    def scan_blocking(self, seconds: float = 24.0) -> dict[str, Any]:
        loop = self.loop
        if loop is not None and loop.is_running():
            try:
                fut = asyncio.run_coroutine_threadsafe(scan_and_connect(seconds), loop)
                fut.result(timeout=max(45.0, seconds + 40.0))
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc), **self.snapshot()}
        else:
            self.request_scan(seconds)
        return self.snapshot()

    def find_light(self, ident: str) -> dict[str, Any] | None:
        token = str(ident or "").strip()
        if not token:
            return None
        mac_n = normalize_mac(token)
        with self.lock:
            for item in self.lights:
                if item["id"] == token:
                    return dict(item)
                if mac_n and normalize_mac(item.get("mac") or "") == mac_n:
                    return dict(item)
        return None

    def request_reconnect(self, light_id: str) -> dict[str, Any] | None:
        light = self.find_light(light_id)
        mac = ""
        if light:
            mac = str(light.get("mac") or "")
        elif normalize_mac(light_id):
            mac = normalize_mac(light_id)
            remember_mac(self.known_macs, mac)
        if not mac:
            return None
        self.reconnect_macs.add(mac)
        self.disconnect_macs.discard(mac)
        return light or {"id": stable_id(mac, "", 0), "mac": mac}

    def request_disconnect(self, light_id: str) -> dict[str, Any] | None:
        light = self.find_light(light_id)
        if not light:
            return None
        mac = str(light.get("mac") or "")
        if mac:
            self.disconnect_macs.add(mac)
            self.reconnect_macs.discard(mac)
        return light

    def authorize(self, header_key: str) -> bool:
        if not self.api_key:
            return True
        return header_key == self.api_key

    def mark(self, mac: str, **fields: Any) -> None:
        with self.lock:
            for light in self.lights:
                if light.get("mac") == mac:
                    light.update(fields)
                    light["lastSeen"] = int(time.time() * 1000)
            self.revision += 1


HUB = Hub()


def mcp_tools_spec() -> list[dict[str, Any]]:
    props = {
        "power": {"type": "boolean", "description": "True = on, False = off"},
        "brightness": {"type": "number", "minimum": 0, "maximum": 100},
        "hue": {"type": "number", "minimum": 0, "maximum": 360, "description": "HSI hue"},
        "saturation": {"type": "number", "minimum": 0, "maximum": 100},
        "kelvin": {"type": "number", "description": "CCT in kelvin"},
        "mode": {"type": "string", "enum": ["cct", "hsi", "scene"]},
        "sceneId": {"type": "integer", "minimum": 1, "maximum": 17},
        "effect": {"type": "string", "description": "Scene name such as Party or Candlelight"},
    }
    return [
        {
            "name": "list_lights",
            "description": "List fixtures the hub currently knows, including disconnected ones the radio could not hold.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_seen",
            "description": "Last BLE scan: every advertisement with mac, name, rssi, and match reason. Use when more lights exist than the connected count.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "scan_lights",
            "description": "Scan for Neewer lights, GATT-probe unnamed nearby devices, wait, then return the updated list.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "number", "minimum": 4, "maximum": 60},
                    "adapter": {"type": "string", "description": "hci1, USB, name substring, or all"},
                },
            },
        },
        {
            "name": "connect_light",
            "description": "Hold one fixture (id from list_lights, or a MAC). Use to swap when the adapter is full.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Fixture id from list_lights"},
                    "mac": {"type": "string", "description": "Bluetooth MAC if id is unknown"},
                },
            },
        },
        {
            "name": "disconnect_light",
            "description": "Drop a GATT session to free a radio slot.",
            "inputSchema": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}},
            },
        },
        {
            "name": "set_light",
            "description": "Set one fixture by id from list_lights.",
            "inputSchema": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string", "description": "Fixture id from list_lights"}, **props},
            },
        },
        {
            "name": "set_all",
            "description": "Apply the same patch to every held fixture.",
            "inputSchema": {"type": "object", "properties": props},
        },
        {
            "name": "hub_health",
            "description": "Hub health: connected count, mqtt status, revision, radios.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_adapters",
            "description": "Bluetooth radios the hub can see. Windows only scans the default radio unless --adapter all.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


def mcp_prompts_spec() -> list[dict[str, Any]]:
    return [
        {
            "name": "lighting_gaffer",
            "description": "System prompt that makes an agent a full CineNode gaffer.",
            "arguments": [],
        }
    ]


def mcp_call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments or {}
    if name == "list_lights":
        return HUB.snapshot()
    if name == "list_seen":
        snap = HUB.snapshot()
        return {"ok": True, "seen": snap.get("seen") or [], "lights": snap.get("lights") or []}
    if name == "hub_health":
        snap = HUB.snapshot()
        return {
            "ok": True,
            "name": "cinenode",
            "revision": snap["revision"],
            "mqtt": snap["mqtt"],
            "connected": sum(1 for item in snap["lights"] if item.get("connected")),
            "lights": len(snap["lights"]),
            "seen": len(snap.get("seen") or []),
            "adapter": snap.get("adapter") or HUB.adapter_prefer,
            "adapters": snap.get("adapters") or [],
        }
    if name == "list_adapters":
        if not HUB.adapters_info:
            HUB.adapters_info = list_ble_adapters()
        plan, mode = scan_plan(HUB.adapter_prefer, HUB.adapters_info, sum(1 for item in HUB.snapshot()["lights"] if item.get("connected")), sys.platform)
        return {
            "ok": True,
            "platform": sys.platform,
            "prefer": HUB.adapter_prefer,
            "mode": mode,
            "adapters": HUB.adapters_info,
            "scan": plan,
            "note": windows_dual_radio_note() if sys.platform == "win32" else "",
        }
    if name == "scan_lights":
        if args.get("adapter"):
            HUB.adapter_prefer = str(args.get("adapter") or "auto")
        seconds = float(args.get("seconds") or 24)
        return {"ok": True, "scan": True, **HUB.scan_blocking(seconds)}
    if name == "connect_light":
        ident = str(args.get("id") or args.get("mac") or "")
        light = HUB.request_reconnect(ident)
        if light is None:
            return {"ok": False, "error": "id or mac is required"}
        return {"ok": True, "reconnect": light.get("id") or ident, **HUB.snapshot()}
    if name == "disconnect_light":
        light = HUB.request_disconnect(str(args.get("id") or ""))
        if light is None:
            return {"ok": False, "error": "unknown light"}
        return {"ok": True, "disconnect": light["id"], **HUB.snapshot()}
    if name in ("set_light", "set_all"):
        light_id = "all" if name == "set_all" else str(args.get("id") or "")
        if not light_id:
            return {"ok": False, "error": "id is required"}
        body = {k: v for k, v in args.items() if k != "id"}
        updated = HUB.patch(light_id, body)
        if updated is None:
            return {"ok": False, "error": f"unknown light {light_id}"}
        return {"ok": True, "light": updated, **HUB.snapshot()}
    return {"ok": False, "error": f"unknown tool {name}"}


def mcp_dispatch(message: dict[str, Any]) -> dict[str, Any] | None:
    method = str(message.get("method") or "")
    req_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method.startswith("notifications/") or req_id is None:
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
                "serverInfo": {"name": "cinenode", "version": "1.2.0"},
                "instructions": AGENT_PROMPT,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": mcp_tools_spec()}}
    if method == "tools/call":
        name = str(params.get("name") or "")
        result = mcp_call_tool(name, params.get("arguments") if isinstance(params.get("arguments"), dict) else {})
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=True)}], "isError": not result.get("ok", True)},
        }
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": mcp_prompts_spec()}}
    if method == "prompts/get":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "description": "CineNode lighting gaffer",
                "messages": [{"role": "user", "content": {"type": "text", "text": AGENT_PROMPT}}],
            },
        }
    if method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "resources": [
                    {"uri": "cinenode://lights", "name": "lights", "mimeType": "application/json"},
                    {"uri": "cinenode://health", "name": "health", "mimeType": "application/json"},
                    {"uri": "cinenode://agent", "name": "agent prompt", "mimeType": "text/markdown"},
                ]
            },
        }
    if method == "resources/read":
        uri = str(params.get("uri") or "")
        if uri.endswith("lights"):
            body = json.dumps(HUB.snapshot())
            mime = "application/json"
        elif uri.endswith("health"):
            body = json.dumps(mcp_call_tool("hub_health", {}))
            mime = "application/json"
        else:
            body = AGENT_PROMPT
            mime = "text/markdown"
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"contents": [{"uri": uri or "cinenode://agent", "mimeType": mime, "text": body}]},
        }
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _read_mcp_message(buf) -> dict[str, Any] | None:
    header = b""
    while True:
        line = buf.readline()
        if not line:
            return None
        stripped = line.lstrip()
        if stripped.startswith(b"{") or stripped.startswith(b"["):
            return json.loads(line)
        if line in (b"\r\n", b"\n"):
            break
        header += line
    length = 0
    for raw in header.split(b"\n"):
        if raw.lower().startswith(b"content-length:"):
            length = int(raw.split(b":", 1)[1].strip() or 0)
    body = buf.read(length) if length else b""
    if not body:
        return None
    return json.loads(body)


def _write_mcp_message(buf, msg: dict[str, Any]) -> None:
    data = json.dumps(msg, ensure_ascii=True).encode()
    buf.write(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
    buf.flush()


def run_mcp_stdio(out=None) -> None:
    stdin = sys.stdin.buffer
    stdout = out.buffer if hasattr(out, "buffer") else (out or sys.__stdout__.buffer)
    while True:
        try:
            message = _read_mcp_message(stdin)
        except json.JSONDecodeError:
            continue
        if message is None:
            return
        if isinstance(message, list):
            for item in message:
                if isinstance(item, dict):
                    resp = mcp_dispatch(item)
                    if resp is not None:
                        _write_mcp_message(stdout, resp)
            continue
        if not isinstance(message, dict):
            continue
        resp = mcp_dispatch(message)
        if resp is not None:
            _write_mcp_message(stdout, resp)


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
            print("paho-mqtt not installed - REST only (pip install paho-mqtt)", file=sys.stderr)
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
        print("MQTT connected - color commands on cinenode/+/set")

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

    def _authorized(self) -> bool:
        return HUB.authorize(self.headers.get("X-CineNode-Key") or "")

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
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, b"")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        origin = self._origin()
        snap = HUB.snapshot()
        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        if path in ("/agent.md", "/llms.txt", "/agent.txt"):
            self._send(200, AGENT_PROMPT.encode(), "text/markdown; charset=utf-8")
            return
        if path in ("/mcp", "/mcp/"):
            self._send(
                200,
                json.dumps(
                    {
                        "ok": True,
                        "name": "cinenode",
                        "protocol": "mcp",
                        "transport": "POST JSON-RPC to /mcp, or python cinenode-hub.py --mcp",
                        "tools": [item["name"] for item in mcp_tools_spec()],
                    }
                ).encode(),
            )
            return
        if path in ("/", "/studio", "/index.html"):
            html = studio_html()
            if html:
                self._send(200, html, "text/html; charset=utf-8")
                return
            if path != "/":
                self._send(404, b'{"error":"not found"}')
                return
            path = "/api/health"
        if path in ("/api/health", "/health"):
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
                        "seen": len(snap.get("seen") or []),
                        "adapter": snap.get("adapter") or HUB.adapter_prefer,
                        "adapters": snap.get("adapters") or [],
                    }
                ).encode(),
            )
            return
        if path == "/api/lights":
            self._send(200, json.dumps(snap).encode())
            return
        if path == "/api/seen":
            self._send(200, json.dumps({"ok": True, "seen": snap.get("seen") or [], "lights": snap.get("lights") or []}).encode())
            return
        if path == "/api/adapters":
            if not HUB.adapters_info:
                HUB.adapters_info = list_ble_adapters()
            plan, mode = scan_plan(
                HUB.adapter_prefer,
                HUB.adapters_info,
                sum(1 for item in snap["lights"] if item.get("connected")),
                sys.platform,
            )
            self._send(
                200,
                json.dumps(
                    {
                        "ok": True,
                        "platform": sys.platform,
                        "prefer": HUB.adapter_prefer,
                        "mode": mode,
                        "adapters": HUB.adapters_info,
                        "scan": plan,
                        "note": windows_dual_radio_note() if sys.platform == "win32" else "",
                    }
                ).encode(),
            )
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
        if not self._authorized():
            self._send(401, b'{"error":"unauthorized"}')
            return
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            body = {}
        if path in ("/mcp", "/mcp/"):
            if isinstance(body, list):
                replies = [mcp_dispatch(item) for item in body if isinstance(item, dict)]
                payload = [item for item in replies if item is not None]
                self._send(200, json.dumps(payload).encode())
                return
            if not isinstance(body, dict):
                body = {}
            reply = mcp_dispatch(body)
            self._send(200, json.dumps(reply or {"jsonrpc": "2.0", "result": None}).encode())
            return
        if path == "/api/scan":
            seconds = body.get("seconds") if isinstance(body, dict) else None
            if isinstance(body, dict) and body.get("adapter"):
                HUB.adapter_prefer = str(body.get("adapter") or "auto")
            HUB.request_scan(float(seconds) if seconds else None)
            self._send(200, json.dumps({"ok": True, "scan": True, **HUB.snapshot()}).encode())
            return
        if path == "/api/adapters":
            prefer = str((body or {}).get("adapter") or (body or {}).get("prefer") or "")
            if prefer:
                HUB.adapter_prefer = prefer
            if not HUB.adapters_info:
                HUB.adapters_info = list_ble_adapters()
            plan, mode = scan_plan(HUB.adapter_prefer, HUB.adapters_info, sum(1 for item in HUB.snapshot()["lights"] if item.get("connected")), sys.platform)
            self._send(200, json.dumps({"ok": True, "prefer": HUB.adapter_prefer, "mode": mode, "adapters": HUB.adapters_info, "scan": plan}).encode())
            return
        if path.startswith("/api/reconnect/"):
            light_id = path.rsplit("/", 1)[-1]
            light = HUB.request_reconnect(light_id)
            if not light:
                self._send(404, b'{"error":"not found"}')
                return
            self._send(200, json.dumps({"ok": True, "reconnect": light["id"]}).encode())
            return
        if path.startswith("/api/disconnect/"):
            light_id = path.rsplit("/", 1)[-1]
            light = HUB.request_disconnect(light_id)
            if not light:
                self._send(404, b'{"error":"not found"}')
                return
            self._send(200, json.dumps({"ok": True, "disconnect": light["id"]}).encode())
            return
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


def looks_like_neewer(device: Any, adv: Any, known: dict[str, Any] | set[str] | None = None) -> bool:
    return bool(match_reason(device, adv, known if known is not None else HUB.known_macs))


def _ble_target(mac: str) -> Any:
    return HUB.devices.get(mac) or mac


async def _client_has_neewer(client: Any) -> bool:
    services = getattr(client, "services", None)
    getter = getattr(client, "get_services", None)
    empty = services is None or not list(services or [])
    if empty and callable(getter):
        try:
            services = await getter()
        except Exception:
            services = getattr(client, "services", None)
    if not services:
        return False
    uuids = [str(getattr(svc, "uuid", svc)).lower() for svc in services]
    if SERVICE.lower() in uuids:
        return True
    for svc in services:
        chars = getattr(svc, "characteristics", None) or []
        for char in chars:
            uuid = str(getattr(char, "uuid", "")).lower()
            if uuid in (WRITE.lower(), NOTIFY.lower()):
                return True
    return False


def _current_adapters() -> list[dict[str, Any]]:
    if HUB.adapters_info:
        return list(HUB.adapters_info)
    listed = list_ble_adapters()
    HUB.adapters_info = listed
    return listed


def _scan_targets(held: int) -> tuple[list[dict[str, Any]], str]:
    listed = _current_adapters()
    if HUB.scan_adapters:
        plan: list[dict[str, Any]] = []
        for aid in HUB.scan_adapters:
            hit = next((item for item in listed if str(item.get("id")) == str(aid) or str(item.get("name")) == str(aid)), None)
            plan.append(hit or {"id": aid, "name": str(aid or "default")})
        mode = "parallel" if len(plan) > 1 and sys.platform not in ("win32", "darwin") else ("sequential" if len(plan) > 1 else "single")
        return plan, mode
    return scan_plan(HUB.adapter_prefer, listed, held, sys.platform)


async def _run_scanner(seconds: float, adapter: dict[str, Any], callback: Any) -> Exception | None:
    from bleak import BleakScanner

    adapter_id = adapter.get("id") if isinstance(adapter, dict) else adapter
    label = str((adapter or {}).get("name") or adapter_id or "default")
    try:
        scanner = open_bleak_scanner(BleakScanner, callback, adapter_id, sys.platform)
        await scanner.start()
        await asyncio.sleep(seconds)
        await scanner.stop()
        return None
    except Exception as extra:  # noqa: BLE001
        print(f"BLE scan failed on {label}:", extra, file=sys.stderr)
        return extra


async def scan_neewer(seconds: float = 24.0) -> dict[str, Any]:
    found: dict[str, Any] = {}
    probe: dict[str, Any] = {}
    rows: dict[str, dict[str, Any]] = {}
    printed: set[str] = set()
    held = sum(1 for item in HUB.snapshot()["lights"] if item.get("connected"))
    plan, mode = _scan_targets(held)
    HUB.scan_mode = mode
    if mode == "sequential" and held > 0:
        print("not switching Bluetooth radios while lights are held; scanning the current default")
        plan, mode = scan_plan(HUB.adapter_prefer, _current_adapters(), held, sys.platform)
        HUB.scan_mode = mode

    def _cb_for(adapter_id: Any):
        label = str(adapter_id or "")

        def _cb(device: Any, adv: Any) -> None:
            mac = getattr(device, "address", "") or ""
            if not mac:
                return
            name = (getattr(device, "name", None) or getattr(adv, "local_name", None) or "").strip()
            rssi = getattr(adv, "rssi", None)
            reason = match_reason(device, adv, HUB.known_macs)
            prev = rows.get(mac) or {}
            prev_reason = str(prev.get("reason") or "")
            keep_device = stronger_rssi(rssi, prev.get("rssi")) or mac not in HUB.devices
            if keep_device:
                HUB.devices[mac] = device
                if label:
                    HUB.device_adapters[mac] = label
            merged_name = name or ("" if prev.get("name") in (None, "", "(no name)") else str(prev.get("name")))
            merged_rssi = rssi if stronger_rssi(rssi, prev.get("rssi")) or prev.get("rssi") is None else prev.get("rssi")
            merged_reason = reason or prev_reason
            if REASON_RANK.get(prev_reason, 0) > REASON_RANK.get(merged_reason, 0):
                merged_reason = prev_reason
            if not merged_reason:
                merged_reason = "probe" if is_probe_candidate(device, adv, HUB.known_macs) else "skip"
            elif merged_reason == "skip" and is_probe_candidate(device, adv, HUB.known_macs):
                merged_reason = "probe"
            merged_adapter = label if keep_device else (prev.get("adapter") or label)
            row = {
                "mac": mac,
                "name": merged_name or "(no name)",
                "rssi": merged_rssi,
                "reason": merged_reason,
                "adapter": merged_adapter or None,
            }
            rows[mac] = row
            keep_found = keep_device or mac not in found
            if merged_reason in ("service", "name", "mfg", "known"):
                if keep_found:
                    found[mac] = HUB.devices.get(mac) or device
                probe.pop(mac, None)
            elif merged_reason == "probe":
                if keep_found:
                    probe[mac] = HUB.devices.get(mac) or device
            if mac not in printed or REASON_RANK.get(merged_reason, 0) > REASON_RANK.get(prev_reason, 0) or keep_device:
                printed.add(mac)
                kind = "MATCH" if merged_reason in ("service", "name", "mfg", "known") else merged_reason
                radio = f"  {merged_adapter}" if merged_adapter else ""
                print(f"  saw {mac}  {(row['name']):22}  rssi={merged_rssi}  {kind}{radio}" + (f" ({reason})" if reason else ""))

        return _cb

    n = max(1, len(plan))
    per = float(seconds)
    if mode == "sequential" and n > 1:
        per = max(12.0, float(seconds) / n)
    labels = ", ".join(str(item.get("name") or item.get("id") or "default") for item in plan) or "default"
    print(f"scanning {int(per)}s x {n} radio(s) [{mode}: {labels}] for advertisements...")
    failures: list[Exception] = []
    if mode == "parallel" and len(plan) > 1:
        results = await asyncio.gather(*[_run_scanner(per, item, _cb_for(item.get("id"))) for item in plan])
        failures.extend(item for item in results if item is not None)
    elif mode == "sequential" and len(plan) > 1:
        for item in plan:
            await select_windows_radio(item, _current_adapters())
            err = await _run_scanner(per, item, _cb_for(item.get("id")))
            if err is not None:
                failures.append(err)
        preferred = prefer_windows_adapter(_current_adapters())
        if preferred:
            await select_windows_radio(preferred, _current_adapters())
    else:
        item = plan[0] if plan else _default_adapter_row()
        if sys.platform == "win32":
            await select_windows_radio(item, _current_adapters())
        err = await _run_scanner(per, item, _cb_for(item.get("id")))
        if err is not None:
            failures.append(err)
    if not rows and failures:
        print("On Windows use native Python (not WSL). Close the Neewer app.", file=sys.stderr)
        if sys.platform == "win32" and len(_current_adapters()) > 1:
            print(windows_dual_radio_note(), file=sys.stderr)
    HUB.last_seen = sorted(rows.values(), key=lambda item: (item.get("rssi") is None, -(item.get("rssi") or 0)))
    print(f"scan finished: {len(rows)} advertisements, {len(found)} matched, {len(probe)} unnamed/nearby to probe")
    if HUB.probe and probe:
        held = sum(1 for item in HUB.snapshot()["lights"] if item.get("connected"))
        if held >= int(HUB.max_connections):
            print("radio already full - skipping GATT probe; unnamed lights stay on /api/seen")
        else:
            confirmed = await probe_unknown(probe, already_matched=found)
            found.update(confirmed)
    return found


async def probe_unknown(candidates: dict[str, Any], already_matched: dict[str, Any] | None = None) -> dict[str, Any]:
    from bleak import BleakClient

    by_rssi = {row["mac"]: row.get("rssi") for row in HUB.last_seen}
    matched_rssi = [
        by_rssi.get(mac)
        for mac in (already_matched or {})
        if isinstance(by_rssi.get(mac), (int, float))
    ]
    cluster = (sum(matched_rssi) / len(matched_rssi)) if matched_rssi else None

    def _score(item: tuple[str, Any]) -> tuple[float, float]:
        mac, _device = item
        rssi = by_rssi.get(mac)
        row = next((entry for entry in HUB.last_seen if entry.get("mac") == mac), {})
        unnamed = 0.0 if (row.get("name") in (None, "", "(no name)")) else 1.0
        near = abs((rssi if isinstance(rssi, (int, float)) else -80) - cluster) if cluster is not None else 40.0
        strength = -(rssi if isinstance(rssi, (int, float)) else -999)
        return (unnamed, near, strength)

    ranked = sorted(candidates.items(), key=_score)
    confirmed: dict[str, Any] = {}
    budget = 24
    timeout = 8.0 if sys.platform == "win32" else 5.0
    print(f"probing up to {min(budget, len(ranked))} unnamed nearby device(s) for the Neewer GATT service...")
    for mac, device in ranked[:budget]:
        label = next((row.get("name") for row in HUB.last_seen if row.get("mac") == mac), "(no name)")
        print(f"  probe {mac}  {label}")
        client = None
        try:
            try:
                client = BleakClient(_ble_target(mac), timeout=timeout)
            except TypeError:
                client = BleakClient(_ble_target(mac))
            await client.connect()
            if await _client_has_neewer(client):
                confirmed[mac] = device
                remember_mac(HUB.known_macs, mac, "" if label == "(no name)" else str(label))
                print(f"  probe {mac}  NEEWER service yes")
                for row in HUB.last_seen:
                    if row.get("mac") == mac:
                        row["reason"] = "probe"
            else:
                print(f"  probe {mac}  not Neewer")
        except Exception as extra:  # noqa: BLE001
            print(f"  probe {mac}  failed ({extra})", file=sys.stderr)
            if RADIO_FULL.search(str(extra)):
                print("adapter out of GATT slots while probing - remaining unnamed stay on /api/seen")
                break
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
        await asyncio.sleep(0.2 if sys.platform != "win32" else 0.4)
    if confirmed:
        try:
            save_known(HUB.known_macs)
        except Exception:
            pass
    print(f"probe finished: {len(confirmed)} extra Neewer light(s)")
    return confirmed


async def connect_found(found: dict[str, Any]) -> None:
    from bleak import BleakClient

    snap = HUB.snapshot()
    existing_macs = {item.get("mac") for item in snap["lights"] if item.get("mac")}
    incoming = []
    index = len(snap["lights"])
    for mac, device in found.items():
        name = getattr(device, "name", None) or (HUB.known_macs.get(normalize_mac(mac), {}) or {}).get("name") or ""
        if not name:
            name = next((str(row.get("name") or "") for row in HUB.last_seen if row.get("mac") == mac and row.get("name") not in (None, "", "(no name)")), "")
        if mac in existing_macs:
            if name:
                HUB.mark(mac, name=name)
            continue
        index += 1
        incoming.append(
            new_light(
                id=stable_id(mac, name, index),
                name=name or f"Light {index}",
                model=name or "Neewer",
                modelCode=name or "Neewer",
                mac=mac,
                connected=False,
                power=True,
                brightness=50,
            )
        )
        remember_mac(HUB.known_macs, mac, name)
    if incoming:
        HUB.upsert_lights(incoming)
        print(f"queued {len(incoming)} new fixture(s)")
        try:
            save_known(HUB.known_macs)
        except Exception:
            pass

    held = sum(1 for item in HUB.snapshot()["lights"] if item.get("connected"))
    targets = []
    seen: set[str] = set()
    ordered = list(found.keys()) + [item.get("mac") or "" for item in HUB.snapshot()["lights"]]
    for mac in ordered:
        if not mac or mac in seen:
            continue
        seen.add(mac)
        client = HUB.clients.get(mac)
        if client is not None and getattr(client, "is_connected", False):
            continue
        targets.append(mac)

    if not targets:
        print(f"holding {held} connected light(s); nothing new to connect")
        return

    slots = max(0, int(HUB.max_connections) - held)
    if slots <= 0:
        print(f"radio full at {held} connection(s). {len(targets)} more stay in the list offline - disconnect some, then Scan.")
        return
    if len(targets) > slots:
        print(f"adapter has about {HUB.max_connections} slots; connecting {slots} of {len(targets)}")
        targets = targets[:slots]

    async def _one(mac: str) -> str:
        try:
            client = HUB.clients.get(mac) or BleakClient(_ble_target(mac))
            await client.connect()
            HUB.clients[mac] = client
            HUB.mark(mac, connected=True)
            light = next((item for item in HUB.snapshot()["lights"] if item.get("mac") == mac), None)
            print("connected", (light or {}).get("name") or mac, mac)
            return "ok"
        except Exception as extra:  # noqa: BLE001
            print("connect failed", mac, extra, file=sys.stderr)
            HUB.mark(mac, connected=False)
            return str(extra)

    radio_full = False
    for mac in targets:
        result = await _one(mac)
        if result != "ok" and RADIO_FULL.search(result or ""):
            radio_full = True
            print("this Bluetooth adapter refused more connections - remaining lights stay listed as offline")
            break
        await asyncio.sleep(0.35)
    snap = HUB.snapshot()
    held = sum(1 for item in snap["lights"] if item.get("connected"))
    extra = len(snap["lights"]) - held
    note = " A PC radio often tops out around 3-8 at once."
    if radio_full or extra:
        note = f" {extra} known but not held. disconnect_light then connect_light to swap."
    print(f"holding {held}/{len(snap['lights'])} lights.{note}")
    HUB.on_change()


async def scan_and_connect(seconds: float = 24.0) -> dict[str, Any]:
    if HUB.scanning:
        while HUB.scanning:
            await asyncio.sleep(0.2)
        return {row["mac"]: HUB.devices.get(row["mac"]) for row in HUB.last_seen if row.get("reason") not in ("skip", None, "")}
    HUB.scanning = True
    try:
        found = await scan_neewer(seconds)
        held = sum(1 for item in HUB.snapshot()["lights"] if item.get("connected"))
        if found:
            await connect_found(found)
        elif held:
            print(f"no new advertisements ({held} already held; connected lights stop broadcasting)")
        else:
            seen_n = len(HUB.last_seen)
            if seen_n:
                print(f"saw {seen_n} BLE device(s) but none looked like Neewer yet - close the official app and leave this window open")
            else:
                print("no BLE advertisements yet - leave this window open, scanning again soon")
        return found
    finally:
        HUB.scanning = False


async def ble_worker() -> None:
    HUB.loop = asyncio.get_running_loop()
    try:
        from bleak import BleakClient
    except ImportError:
        print("bleak not installed - REST only (pip install bleak)", file=sys.stderr)
        while True:
            await asyncio.sleep(2)
        return

    last_scan = -1e9
    first = True
    while True:
        now = time.monotonic()
        snap = HUB.snapshot()
        connected = any(item.get("connected") for item in snap["lights"])
        need = HUB.scan_requested or first or (not connected and now - last_scan > 12)
        if need:
            first = False
            HUB.scan_requested = False
            last_scan = now
            seconds = 32.0 if sys.platform == "win32" else 24.0
            if connected:
                seconds = 20.0 if sys.platform == "win32" else 16.0
            if HUB.scan_seconds:
                seconds = float(HUB.scan_seconds)
                HUB.scan_seconds = None
            await scan_and_connect(seconds)

        for mac in list(HUB.disconnect_macs):
            HUB.disconnect_macs.discard(mac)
            client = HUB.clients.pop(mac, None)
            try:
                if client is not None:
                    await client.disconnect()
            except Exception as extra:  # noqa: BLE001
                print("disconnect failed", mac, extra, file=sys.stderr)
            HUB.mark(mac, connected=False)
            print("disconnected", mac)

        for mac in list(HUB.reconnect_macs):
            HUB.reconnect_macs.discard(mac)
            try:
                client = HUB.clients.get(mac) or BleakClient(_ble_target(mac))
                await client.connect()
                HUB.clients[mac] = client
                HUB.mark(mac, connected=True)
                print("reconnected", mac)
            except Exception as extra:  # noqa: BLE001
                print("reconnect failed", mac, extra, file=sys.stderr)
                HUB.mark(mac, connected=False)

        for mac, client in list(HUB.clients.items()):
            try:
                if not getattr(client, "is_connected", False):
                    await client.connect()
                    HUB.mark(mac, connected=True)
            except Exception as extra:  # noqa: BLE001
                print("reconnect failed", mac, extra, file=sys.stderr)
                HUB.mark(mac, connected=False)

        for mac, pkt in HUB.drain_writes():
            client = HUB.clients.get(mac)
            if client is None:
                continue
            try:
                if not getattr(client, "is_connected", True):
                    await client.connect()
                    HUB.mark(mac, connected=True)
                await client.write_gatt_char(WRITE, pkt, response=False)
            except Exception as extra:  # noqa: BLE001
                print("write failed", mac, extra, file=sys.stderr)
                HUB.mark(mac, connected=False)
        await asyncio.sleep(0.04)


def bind_http(host: str, port: int) -> tuple[ThreadingHTTPServer, int]:
    class ReuseServer(ThreadingHTTPServer):
        allow_reuse_address = True

    last: OSError | None = None
    for candidate in range(port, port + 8):
        try:
            server = ReuseServer((host, candidate), Handler)
            return server, candidate
        except OSError as exc:
            last = exc
            print(f"port {candidate} busy, trying next...", file=sys.stderr)
    raise OSError(str(last) if last else "could not bind HTTP port")


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


def studio_html() -> bytes | None:
    here = os.path.dirname(os.path.abspath(__file__))
    for rel in ("studio.html", os.path.join("downloads", "studio.html")):
        path = os.path.join(here, rel)
        if os.path.isfile(path):
            try:
                with open(path, "rb") as handle:
                    return handle.read()
            except OSError:
                return None
    return None


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
    html = studio_html()
    check("studio page", bool(html and b"CineNode" in html))
    check("rgb660 name", looks_like_neewer(type("D", (), {"name": "RGB660 PRO"})(), type("A", (), {"local_name": "", "service_uuids": []})()))
    check("rgb1 name", looks_like_neewer(type("D", (), {"name": "RGB1"})(), type("A", (), {"local_name": "", "service_uuids": []})()))
    check(
        "model code name",
        looks_like_neewer(type("D", (), {"name": "NW-20240014&A7E00100"})(), type("A", (), {"local_name": "", "service_uuids": []})()),
    )
    mfg_adv = type("A", (), {"local_name": "", "service_uuids": [], "manufacturer_data": {0xFFFF: b"NEEWER-RGB480"}, "rssi": -50})()
    mfg_dev = type("D", (), {"name": None, "address": "AA:BB:CC:DD:EE:11"})()
    check("mfg payload", match_reason(mfg_dev, mfg_adv, {}) == "mfg")
    apple_adv = type("A", (), {"local_name": "", "service_uuids": [], "manufacturer_data": {0x004C: b"\x02\x15hello"}, "rssi": -40})()
    apple_dev = type("D", (), {"name": None, "address": "AA:BB:CC:DD:EE:22"})()
    check("skip apple mfg", not is_probe_candidate(apple_dev, apple_adv, {}))
    banner = ready_banner(8787, "10.1.10.202", "0.0.0.0")
    check("banner one url", "Open exactly ONE URL" in banner and "http://10.1.10.202:8787" in banner)
    check("banner if this computer", "IF the browser is on THIS computer" in banner)
    known = remember_mac({}, "c5:02:f5:0d:ca:ba", "Key")
    check("known mac", "C5:02:F5:0D:CA:BA" in known)
    skip_adv = type("A", (), {"local_name": "AirPods", "service_uuids": [], "rssi": -40})()
    skip_dev = type("D", (), {"name": "AirPods", "address": "AA:BB:CC:DD:EE:FF"})()
    check("skip airpods", not is_probe_candidate(skip_dev, skip_adv, {}))
    unnamed = type("D", (), {"name": None, "address": "C5:02:F5:0D:CA:BA"})()
    unnamed_adv = type("A", (), {"local_name": "", "service_uuids": [], "rssi": -55})()
    check("probe unnamed", is_probe_candidate(unnamed, unnamed_adv, {}))
    weak_adv = type("A", (), {"local_name": "", "service_uuids": [], "rssi": -110})()
    check("probe weak rssi", is_probe_candidate(unnamed, weak_adv, {}))
    payload = json.dumps(
        [
            {"FriendlyName": "Intel Wireless Bluetooth", "InstanceId": r"BTH\INTEL", "Status": "OK"},
            {"FriendlyName": "TP-Link Bluetooth 5.4 USB", "InstanceId": r"USB\VID_2357&PID_0604\0001", "Status": "OK"},
        ]
    )
    pnp = parse_windows_pnp_json(payload)
    check("pnp parse", len(pnp) == 2)
    preferred = prefer_windows_adapter(pnp) or {}
    check("tplink preferred", "TP-Link" in str(preferred.get("name") or ""))
    _plan, win_mode = scan_plan("auto", pnp, 0, "win32")
    check("win sequential first scan", win_mode == "sequential")
    _plan2, win_held = scan_plan("auto", pnp, 2, "win32")
    check("win single while held", win_held == "single")
    linux_plan, linux_mode = scan_plan("auto", [{"id": "hci0", "name": "hci0"}, {"id": "hci1", "name": "hci1"}], 0, "linux")
    check("linux parallel", linux_mode == "parallel" and len(linux_plan) == 2)
    kw = scanner_kwargs(lambda *_a: None, "hci1", "linux")
    check("scanner adapter kw", any(item.get("adapter") == "hci1" for item in kw))
    check("stronger rssi", stronger_rssi(-40, -70) and not stronger_rssi(-90, -40))
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
    parser.add_argument("--api-key", default=str(cfg.get("apiKey") or os.environ.get("CINENODE_KEY") or ""))
    parser.add_argument("--mcp", action="store_true", help="Speak MCP on stdin/stdout (starts the hub too)")
    parser.add_argument("--mac", action="append", default=[], help="Treat this MAC as a known Neewer light (repeatable)")
    parser.add_argument("--no-probe", action="store_true", help="Do not GATT-probe unnamed nearby devices")
    parser.add_argument("--max-connections", type=int, default=int(cfg.get("maxConnections") or 8), help="Stop connecting after this many GATT sessions")
    parser.add_argument("--adapter", default=str(cfg.get("adapter") or "auto"), help="Bluetooth adapter id (hci1), USB, name substring, or all")
    parser.add_argument("--list-adapters", action="store_true", help="Print Bluetooth radios and exit")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(self_test())

    mcp_out = None
    if args.mcp:
        mcp_out = sys.stdout
        sys.stdout = sys.stderr

    Handler.prefix = args.discovery_prefix
    HUB.api_key = args.api_key
    HUB.probe = not args.no_probe
    HUB.max_connections = max(1, int(args.max_connections))
    HUB.adapter_prefer = str(args.adapter or "auto")
    HUB.adapters_info = list_ble_adapters()
    if args.list_adapters:
        held = 0
        plan, _mode = scan_plan(HUB.adapter_prefer, HUB.adapters_info, held, sys.platform)
        print(format_adapter_report(HUB.adapters_info, plan, sys.platform))
        raise SystemExit(0)
    HUB.known_macs = load_known(os.path.join(here, "cinenode-known.json"))
    for mac in args.mac:
        remember_mac(HUB.known_macs, mac, "pinned")
    if HUB.known_macs:
        print(f"remembered {len(HUB.known_macs)} Neewer MAC(s) from previous scans")
    ip = lan_ip()
    Handler.origin_override = f"http://{ip}:{args.port}"

    def origin_fn() -> str:
        return Handler.origin_override

    bridge = MqttBridge(args.mqtt, args.mqtt_user or None, args.mqtt_password or None, args.discovery_prefix, origin_fn)
    bridge.start()

    def runner() -> None:
        asyncio.run(ble_worker())

    threading.Thread(target=runner, daemon=True, name="cinenode-ble").start()
    try:
        httpd, bound = bind_http(args.host, args.port)
    except OSError as exc:
        print("could not bind HTTP:", exc, file=sys.stderr)
        raise SystemExit(1) from exc
    args.port = bound
    Handler.origin_override = f"http://{ip}:{args.port}"
    print(ready_banner(args.port, ip, args.host))
    print("Close the official Neewer app so Bluetooth is free.")
    print("Unnamed lights are probed for the Neewer service. Cheap adapters often stop at 3 connections.")
    plan, mode = scan_plan(HUB.adapter_prefer, HUB.adapters_info, 0, sys.platform)
    print(format_adapter_report(HUB.adapters_info, plan, sys.platform))
    if sys.platform == "win32" and len(HUB.adapters_info) > 1:
        print(windows_dual_radio_note())
    if mode != "single":
        print(f"Discovery mode: {mode}")
    print("Agents: python cinenode-hub.py --mcp   or POST JSON-RPC to /mcp   or GET /agent.md")
    if args.mqtt:
        print(f"MQTT (optional) {args.mqtt}")
    else:
        print("MQTT off. Add --mqtt only if you use Home Assistant.")
    if args.api_key:
        print("API key is on. Send header X-CineNode-Key on writes.")
    if mcp_out is not None:
        print("MCP stdio is live. Logs stay on this stream.", file=sys.stderr)
        run_mcp_stdio(mcp_out)
        return
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")


if __name__ == "__main__":
    main()
