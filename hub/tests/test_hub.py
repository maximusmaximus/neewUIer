from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "ha-commands.json"


def test_known_ble_frames(hub) -> None:
    assert hub.power_frame(True).hex(" ") == "78 81 01 01 fb"
    assert hub.power_frame(False).hex(" ") == "78 81 01 02 fc"
    assert hub.hsi_frame(88, 24, 100).hex(" ") == "78 86 04 58 00 18 64 d6"
    assert hub.cct_frame(100, 5600).hex(" ") == "78 87 02 64 38 9d"
    assert hub.scene_frame(100, 1).hex(" ") == "78 88 02 64 01 67"


def test_hsi_hue_overflow_bit(hub) -> None:
    pkt = hub.hsi_frame(360, 100, 50)
    assert pkt[3] == 104
    assert pkt[4] == 1
    assert pkt[-1] == hub.checksum(pkt[:-1])


def test_checksum_is_low_8_bits(hub) -> None:
    assert hub.checksum(bytes([0x78, 0x81, 0x01, 0x01])) == 0xFB
    assert hub.checksum(bytes([255, 1])) == 0


def test_self_test_entry_point(hub) -> None:
    assert hub.self_test() == 0


@pytest.mark.parametrize("case", json.loads(FIXTURES.read_text(encoding="utf-8")))
def test_ha_command_fixtures(hub, case: dict) -> None:
    got = hub.parse_ha_command(case["in"])
    expected = case["out"]
    for key, value in expected.items():
        actual = got.get(key)
        if isinstance(value, (int, float)) and isinstance(actual, (int, float)):
            assert actual == pytest.approx(value, abs=1)
        else:
            assert actual == value, f"{case['name']}: {key}"
    if case["name"] == "OFF does not force mode":
        assert "mode" not in got
    if case["name"] == "rgb_color green":
        assert 100 < got["hue"] < 140
        assert got["saturation"] > 99
    if case["name"] == "empty body":
        assert got == {}


def test_parse_ha_command_rejects_non_objects(hub) -> None:
    assert hub.parse_ha_command(None) == {}
    assert hub.parse_ha_command("ON") == {}
    assert hub.parse_ha_command([1, 2]) == {}


def test_parse_broker(hub) -> None:
    host, port, tls, user, password = hub.parse_broker("mqtts://user:secret@ha.local:8883")
    assert host == "ha.local"
    assert port == 8883
    assert tls is True
    assert user == "user"
    assert password == "secret"


def test_parse_broker_defaults(hub) -> None:
    host, port, tls, user, password = hub.parse_broker("homeassistant.local")
    assert host == "homeassistant.local"
    assert port == 1883
    assert tls is False
    assert user is None
    assert password is None


def test_effect_and_rgb_helpers(hub) -> None:
    assert hub.effect_to_scene("Party") == 5
    assert hub.effect_to_scene("scene 3") == 3
    assert hub.effect_to_scene("") is None
    assert hub.effect_to_scene("scene 99") is None
    h, s = hub.rgb_to_hs(255, 0, 0)
    assert h < 1 or h > 359
    assert s > 99


def test_ha_state_payload(hub) -> None:
    light = hub.new_light(connected=True, power=True, mode="cct", brightness=72, kelvin=5600)
    payload = hub.ha_state(light)
    assert payload["state"] == "ON"
    assert payload["brightness"] == 72
    assert payload["color_mode"] == "color_temp"
    assert payload["color_temp_kelvin"] == 5600


def test_ha_state_hsi_and_scene_and_offline(hub) -> None:
    hsi = hub.ha_state(hub.new_light(connected=True, power=True, mode="hsi", hue=210, saturation=70, brightness=40))
    assert hsi["state"] == "ON"
    assert hsi["color_mode"] == "hs"
    assert hsi["color"] == {"h": 210, "s": 70}
    scene = hub.ha_state(hub.new_light(connected=True, power=True, mode="scene", sceneId=5, hue=0, saturation=0))
    assert scene["effect"] == "Party"
    offline = hub.ha_state(hub.new_light(connected=False, power=True, mode="cct"))
    assert offline["state"] == "OFF"


def test_hub_patch_hsi_and_broadcast(hub, isolated_hub) -> None:
    node = isolated_hub
    updated = node.patch("key", {"state": "ON", "color": {"h": 210, "s": 70}, "brightness": 80})
    assert updated is not None
    assert updated["mode"] == "hsi"
    assert updated["hue"] == 210
    assert updated["brightness"] == 80
    all_on = node.patch("all", {"state": "OFF"})
    assert all_on is not None
    assert all_on["power"] is False
    missing = node.patch("does-not-exist", {"state": "ON"})
    assert missing is None


def test_hub_packet_and_pending_queue(hub, isolated_hub) -> None:
    node = isolated_hub
    node.lights = [hub.new_light(id="key", mac="AA:BB:CC:DD:EE:FF", power=True, mode="hsi", hue=10, saturation=20, brightness=30)]
    node.patch("key", {"brightness": 40, "mode": "hsi", "hue": 10, "saturation": 20, "power": True})
    writes = node.drain_writes()
    assert len(writes) == 1
    assert writes[0][0] == "AA:BB:CC:DD:EE:FF"
    assert writes[0][1] == hub.hsi_frame(10, 20, 40)
    assert node.drain_writes() == []
    off = node._packet({"power": False})
    assert off == hub.power_frame(False)
    cct = node._packet({"power": True, "mode": "cct", "brightness": 100, "kelvin": 5600})
    assert cct == hub.cct_frame(100, 5600)
    scene = node._packet({"power": True, "mode": "scene", "brightness": 80, "sceneId": 1})
    assert scene == hub.scene_frame(80, 1)


def test_stable_id(hub) -> None:
    assert hub.stable_id("AA:BB:CC:DD:EE:FF", "Key", 1) == "nddeeff"
    assert hub.stable_id("", "Fill Light", 2).startswith("fillligh")


def test_looks_like_neewer(hub) -> None:
    class Device:
        def __init__(self, name: str | None) -> None:
            self.name = name

    class Adv:
        def __init__(self, local_name: str = "", uuids: list[str] | None = None) -> None:
            self.local_name = local_name
            self.service_uuids = uuids or []

    assert hub.looks_like_neewer(Device("NEEWER RGB660"), Adv()) is True
    assert hub.looks_like_neewer(Device("NW-RGB176"), Adv()) is True
    assert hub.looks_like_neewer(Device("SL90"), Adv()) is True
    assert hub.looks_like_neewer(Device(None), Adv(uuids=[hub.SERVICE])) is True
    assert hub.looks_like_neewer(Device("Philips Hue"), Adv()) is False
