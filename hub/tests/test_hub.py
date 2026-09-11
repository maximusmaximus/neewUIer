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


def test_parse_broker(hub) -> None:
    host, port, tls, user, password = hub.parse_broker("mqtts://user:secret@ha.local:8883")
    assert host == "ha.local"
    assert port == 8883
    assert tls is True
    assert user == "user"
    assert password == "secret"


def test_effect_and_rgb_helpers(hub) -> None:
    assert hub.effect_to_scene("Party") == 5
    assert hub.effect_to_scene("scene 3") == 3
    h, s = hub.rgb_to_hs(255, 0, 0)
    assert h < 1 or h > 359
    assert s > 99


def test_ha_state_payload(hub) -> None:
    light = hub.new_light(connected=True, power=True, mode="cct", brightness=72, kelvin=5600)
    payload = hub.ha_state(light)
    assert payload["state"] == "ON"
    assert payload["brightness"] == 72
    assert payload["color_mode"] == "color_temp"


def test_hub_patch_hsi_and_broadcast(hub) -> None:
    node = hub.Hub()
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


def test_stable_id(hub) -> None:
    assert hub.stable_id("AA:BB:CC:DD:EE:FF", "Key", 1) == "nddeeff"
    assert hub.stable_id("", "Fill Light", 2).startswith("fillligh")
