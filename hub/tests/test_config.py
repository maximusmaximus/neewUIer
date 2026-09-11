from __future__ import annotations

import json


def test_load_config_missing(hub, tmp_path) -> None:
    assert hub.load_config(str(tmp_path / "nope.json")) == {}


def test_load_config_valid(hub, tmp_path) -> None:
    path = tmp_path / "cinenode.json"
    path.write_text(json.dumps({"mqtt": "mqtt://ha.local:1883", "port": 9000}), encoding="utf-8")
    data = hub.load_config(str(path))
    assert data["mqtt"] == "mqtt://ha.local:1883"
    assert data["port"] == 9000


def test_load_config_invalid_json(hub, tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert hub.load_config(str(path)) == {}


def test_load_config_non_object(hub, tmp_path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[1, 2]", encoding="utf-8")
    assert hub.load_config(str(path)) == {}


def test_lan_ip_returns_a_dotted_address(hub) -> None:
    ip = hub.lan_ip()
    parts = ip.split(".")
    assert len(parts) == 4
    assert all(p.isdigit() for p in parts)
