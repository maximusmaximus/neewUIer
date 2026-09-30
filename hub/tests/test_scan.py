from __future__ import annotations

import asyncio
import json
import sys
import types


class Device:
    def __init__(self, address: str, name: str | None = None) -> None:
        self.address = address
        self.name = name


class Adv:
    def __init__(self, local_name: str = "", uuids: list[str] | None = None, rssi: int | None = -40, manufacturer_data: dict | None = None) -> None:
        self.local_name = local_name
        self.service_uuids = uuids or []
        self.rssi = rssi
        self.manufacturer_data = manufacturer_data or {}


def _install_bleak(monkeypatch, ads, clients=None):
    captured: dict = {}

    class FakeScanner:
        def __init__(self, detection_callback=None, scanning_mode=None, adapter=None, bluez=None, **_kwargs) -> None:
            self.cb = detection_callback
            self.adapter = adapter or (bluez or {}).get("adapter")
            captured.setdefault("scanners", []).append({"adapter": self.adapter, "bluez": bluez, "mode": scanning_mode})
            captured["cb"] = detection_callback
            captured["mode"] = scanning_mode
            captured["adapter"] = self.adapter
            captured["bluez"] = bluez

        async def start(self) -> None:
            table = ads
            if isinstance(ads, dict):
                table = ads.get(self.adapter) or ads.get(str(self.adapter)) or []
            for device, adv in table:
                self.cb(device, adv)

        async def stop(self) -> None:
            return None

    class FakeClient:
        def __init__(self, target, timeout=None) -> None:
            self.target = target
            self.timeout = timeout
            self.services = []
            captured.setdefault("clients", []).append(self)

        async def connect(self) -> None:
            mac = getattr(self.target, "address", None) or str(self.target)
            table = clients or {}
            outcome = table.get(mac, "ok")
            if outcome == "fail":
                raise RuntimeError("failed")
            if outcome == "full":
                raise RuntimeError("connection limit")
            self.connected = True
            self._neewer = outcome == "neewer" or outcome == "ok"

        async def disconnect(self) -> None:
            self.connected = False

        @property
        def is_connected(self) -> bool:
            return bool(getattr(self, "connected", False))

        async def get_services(self):
            if getattr(self, "_neewer", False):
                svc = types.SimpleNamespace(uuid="69400001-b5a3-f393-e0a9-e50e24dcca99", characteristics=[])
                return [svc]
            return []

    mod = types.ModuleType("bleak")
    mod.BleakScanner = FakeScanner
    mod.BleakClient = FakeClient
    monkeypatch.setitem(sys.modules, "bleak", mod)
    return captured


def test_scan_classifies_name_unnamed_and_skip(hub, isolated_hub, monkeypatch) -> None:
    ads = [
        (Device("C5:02:F5:0D:CA:BA", "NEEWER RGB660"), Adv("NEEWER RGB660", rssi=-40)),
        (Device("AA:AA:AA:AA:AA:01", None), Adv("", rssi=-50)),
        (Device("AA:AA:AA:AA:AA:02", "AirPods"), Adv("AirPods", rssi=-30)),
        (Device("AA:AA:AA:AA:AA:03", None), Adv("", uuids=[hub.SERVICE], rssi=-45)),
    ]
    _install_bleak(monkeypatch, ads)
    isolated_hub.probe = False
    found = asyncio.run(hub.scan_neewer(0.01))
    assert "C5:02:F5:0D:CA:BA" in found
    assert "AA:AA:AA:AA:AA:03" in found
    reasons = {row["mac"]: row["reason"] for row in isolated_hub.last_seen}
    assert reasons["C5:02:F5:0D:CA:BA"] == "name"
    assert reasons["AA:AA:AA:AA:AA:03"] == "service"
    assert reasons["AA:AA:AA:AA:AA:01"] == "probe"
    assert reasons["AA:AA:AA:AA:AA:02"] == "skip"


def test_probe_keeps_neewer_service(hub, isolated_hub, monkeypatch) -> None:
    unnamed = Device("C5:02:F5:0D:CA:BA", None)
    ads = [(unnamed, Adv("", rssi=-42))]
    _install_bleak(monkeypatch, ads, clients={"C5:02:F5:0D:CA:BA": "neewer"})
    isolated_hub.probe = True
    isolated_hub.last_seen = [{"mac": "C5:02:F5:0D:CA:BA", "name": "(no name)", "rssi": -42, "reason": "probe"}]
    isolated_hub.devices["C5:02:F5:0D:CA:BA"] = unnamed
    confirmed = asyncio.run(hub.probe_unknown({"C5:02:F5:0D:CA:BA": unnamed}))
    assert "C5:02:F5:0D:CA:BA" in confirmed
    assert isolated_hub.last_seen[0]["reason"] == "probe"


def test_scan_and_connect_holds_named_light(hub, isolated_hub, monkeypatch) -> None:
    ads = [(Device("C5:02:F5:0D:CA:BA", "NW-RGB176"), Adv("NW-RGB176", rssi=-38))]
    _install_bleak(monkeypatch, ads, clients={"C5:02:F5:0D:CA:BA": "ok"})
    isolated_hub.probe = False
    asyncio.run(hub.scan_and_connect(0.01))
    assert any(item.get("mac") == "C5:02:F5:0D:CA:BA" and item.get("connected") for item in isolated_hub.lights)


def test_connect_found_stops_when_radio_full(hub, isolated_hub, monkeypatch) -> None:
    d1 = Device("C5:02:F5:0D:CA:BA", "NEEWER 1")
    d2 = Device("C4:47:A2:2F:B4:6A", "NEEWER 2")
    _install_bleak(
        monkeypatch,
        [],
        clients={"C5:02:F5:0D:CA:BA": "ok", "C4:47:A2:2F:B4:6A": "full"},
    )
    isolated_hub.devices = {"C5:02:F5:0D:CA:BA": d1, "C4:47:A2:2F:B4:6A": d2}
    asyncio.run(hub.connect_found({"C5:02:F5:0D:CA:BA": d1, "C4:47:A2:2F:B4:6A": d2}))
    held = [item for item in isolated_hub.lights if item.get("connected")]
    assert len(held) == 1


def test_client_has_neewer_helpers(hub) -> None:
    class Svc:
        uuid = hub.SERVICE
        characteristics = []

    class Client:
        services = [Svc()]

    assert asyncio.run(hub._client_has_neewer(Client())) is True

    class Empty:
        services = []

    assert asyncio.run(hub._client_has_neewer(Empty())) is False

    class Char:
        uuid = hub.WRITE

    class Other:
        uuid = "00001800-0000-1000-8000-00805f9b34fb"
        characteristics = [Char()]

    class ViaWrite:
        services = [Other()]

    assert asyncio.run(hub._client_has_neewer(ViaWrite())) is True


def test_scan_blocking_without_loop(hub, isolated_hub) -> None:
    isolated_hub.loop = None
    snap = isolated_hub.scan_blocking(8)
    assert snap["ok"] is True
    assert isolated_hub.scan_requested is True


def test_reconnect_raw_mac_and_missing(hub, isolated_hub) -> None:
    light = isolated_hub.request_reconnect("C5:02:F5:0D:CA:BA")
    assert light is not None
    assert "C5:02:F5:0D:CA:BA" in isolated_hub.reconnect_macs
    assert isolated_hub.request_reconnect("") is None
    assert isolated_hub.request_disconnect("missing") is None


def test_mcp_resources_and_unknown_tool(hub, isolated_hub) -> None:
    listed = hub.mcp_dispatch({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    uris = {item["uri"] for item in listed["result"]["resources"]}
    assert "cinenode://agent" in uris
    read = hub.mcp_dispatch({"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": "cinenode://agent"}})
    assert "exactly ONE" in read["result"]["contents"][0]["text"]
    health = hub.mcp_dispatch({"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "cinenode://health"}})
    assert "cinenode" in health["result"]["contents"][0]["text"]
    bogus = hub.mcp_call_tool("nope", {})
    assert bogus["ok"] is False
    ping = hub.mcp_dispatch({"jsonrpc": "2.0", "id": 4, "method": "ping"})
    assert ping["result"] == {}


def test_manufacturer_payload_matches_without_local_name(hub) -> None:
    device = Device("AA:BB:CC:DD:EE:11", None)
    adv = Adv("", manufacturer_data={0xFFFF: b"NEEWER-RGB480"}, rssi=-48)
    assert hub.match_reason(device, adv, {}) == "mfg"


def test_apple_manufacturer_is_not_probed(hub) -> None:
    device = Device("AA:BB:CC:DD:EE:22", None)
    adv = Adv("", manufacturer_data={0x004C: b"\x02\x15\x00"}, rssi=-30)
    assert hub.is_probe_candidate(device, adv, {}) is False


def test_model_code_and_rgb1_match_by_name(hub) -> None:
    assert hub.match_reason(Device("AA:00:00:00:00:01", "NW-20240014&A7E00100"), Adv("NW-20240014&A7E00100"), {}) == "name"
    assert hub.match_reason(Device("AA:00:00:00:00:02", "RGB1"), Adv("RGB1"), {}) == "name"
    assert hub.match_reason(Device("AA:00:00:00:00:03", "NEEWER-RGB960"), Adv("NEEWER-RGB960"), {}) == "name"


def test_empty_services_uses_get_services(hub) -> None:
    class Svc:
        uuid = hub.SERVICE
        characteristics = []

    class Client:
        services = []

        async def get_services(self):
            return [Svc()]

    assert asyncio.run(hub._client_has_neewer(Client())) is True


def test_weak_rssi_is_still_probed(hub) -> None:
    device = Device("AA:BB:CC:DD:EE:FF", None)
    assert hub.is_probe_candidate(device, Adv("", rssi=-92), {}) is True
    assert hub.is_probe_candidate(device, Adv("", rssi=-110), {}) is True


def test_scan_plan_windows_and_linux(hub) -> None:
    radios = [
        {"id": "intel", "name": "Intel Wireless Bluetooth", "kind": "builtin", "default": True, "state": "OK"},
        {
            "id": r"USB\VID_2357&PID_0604",
            "name": "TP-Link Bluetooth 5.4 USB",
            "instance": r"USB\VID_2357&PID_0604",
            "kind": "usb",
            "state": "OK",
        },
    ]
    plan, mode = hub.scan_plan("auto", radios, held=0, platform="win32")
    assert mode == "sequential"
    assert len(plan) == 2
    _, held_mode = hub.scan_plan("auto", radios, held=3, platform="win32")
    assert held_mode == "single"
    one, one_mode = hub.scan_plan("TP-Link", radios, held=0, platform="win32")
    assert one_mode == "single"
    assert len(one) == 1
    assert "TP-Link" in one[0]["name"]
    preferred = hub.prefer_windows_adapter(radios)
    assert preferred is not None
    assert "TP-Link" in preferred["name"]
    linux, linux_mode = hub.scan_plan("auto", [{"id": "hci0", "name": "hci0"}, {"id": "hci1", "name": "hci1"}], 0, "linux")
    assert linux_mode == "parallel"
    assert [item["id"] for item in linux] == ["hci0", "hci1"]


def test_parse_windows_pnp_prefers_usb(hub) -> None:
    payload = json.dumps(
        [
            {"FriendlyName": "Intel Wireless Bluetooth", "InstanceId": r"BTH\INTEL", "Status": "OK"},
            {"FriendlyName": "TP-Link Bluetooth 5.4 USB", "InstanceId": r"USB\VID_2357&PID_0604\0001", "Status": "OK"},
            {"FriendlyName": "Microsoft Bluetooth Enumerator", "InstanceId": r"BTH\ENUM", "Status": "OK"},
        ]
    )
    parsed = hub.parse_windows_pnp_json(payload)
    names = [item["name"] for item in parsed]
    assert "TP-Link Bluetooth 5.4 USB" in names
    assert "Intel Wireless Bluetooth" in names
    assert all("Enumerator" not in name for name in names)
    assert "TP-Link" in hub.prefer_windows_adapter(parsed)["name"]


def test_list_linux_adapters_from_sysfs(hub, tmp_path) -> None:
    hci0 = tmp_path / "hci0"
    hci1 = tmp_path / "hci1"
    hci0.mkdir()
    hci1.mkdir()
    (hci0 / "address").write_text("aa:bb:cc:dd:ee:00\n")
    (hci1 / "address").write_text("11:22:33:44:55:66\n")
    listed = hub.list_linux_adapters(str(tmp_path))
    ids = [item["id"] for item in listed]
    assert ids == ["hci0", "hci1"]
    assert listed[0]["address"] == "AA:BB:CC:DD:EE:00"


def test_scanner_kwargs_include_adapter_on_linux(hub) -> None:
    attempts = hub.scanner_kwargs(lambda *_a: None, "hci1", "linux")
    assert any(item.get("adapter") == "hci1" for item in attempts)
    win = hub.scanner_kwargs(lambda *_a: None, "hci1", "win32")
    assert all("adapter" not in item for item in win)


def test_parallel_scan_merges_stronger_rssi_device(hub, isolated_hub, monkeypatch) -> None:
    weak = Device("AA:AA:AA:AA:AA:01", "NEEWER RGB660")
    strong = Device("AA:AA:AA:AA:AA:01", "NEEWER RGB660")
    extra = Device("BB:BB:BB:BB:BB:02", "NEEWER RGB960")
    ads = {
        "hci0": [(weak, Adv("NEEWER RGB660", rssi=-80))],
        "hci1": [(strong, Adv("NEEWER RGB660", rssi=-40)), (extra, Adv("NEEWER RGB960", rssi=-55))],
    }
    captured = _install_bleak(monkeypatch, ads)
    isolated_hub.probe = False
    isolated_hub.scan_adapters = ["hci0", "hci1"]
    isolated_hub.adapters_info = [{"id": "hci0", "name": "hci0"}, {"id": "hci1", "name": "hci1"}]
    found = asyncio.run(hub.scan_neewer(0.01))
    assert "AA:AA:AA:AA:AA:01" in found
    assert "BB:BB:BB:BB:BB:02" in found
    assert found["AA:AA:AA:AA:AA:01"] is strong
    by_mac = {row["mac"]: row for row in isolated_hub.last_seen}
    assert by_mac["AA:AA:AA:AA:AA:01"]["rssi"] == -40
    assert by_mac["AA:AA:AA:AA:AA:01"]["adapter"] == "hci1"
    adapters = [item.get("adapter") for item in captured["scanners"]]
    assert "hci0" in adapters
    assert "hci1" in adapters


def test_open_bleak_scanner_passes_adapter(hub) -> None:
    seen = []

    class Scanner:
        def __init__(self, **kwargs) -> None:
            seen.append(kwargs)

    hub.open_bleak_scanner(Scanner, lambda *_a: None, "hci1", "linux")
    assert seen[0]["adapter"] == "hci1"
    assert seen[0]["scanning_mode"] == "active"
