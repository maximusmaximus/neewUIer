from __future__ import annotations

import json
from types import SimpleNamespace


class _Msg:
    def __init__(self, topic: str, payload: str | bytes) -> None:
        self.topic = topic
        self.payload = payload.encode() if isinstance(payload, str) else payload


def test_mqtt_docs_json_schema(hub, isolated_hub) -> None:
    isolated_hub.lights = [hub.new_light(id="key", name="Key", rgb=True, connected=True)]
    docs = hub.mqtt_docs("http://studio.local:8787", "homeassistant")
    assert len(docs) == 1
    payload = docs[0]["payload"]
    assert payload["schema"] == "json"
    assert payload["command_topic"] == "cinenode/key/set"
    assert payload["brightness_scale"] == 100
    assert payload["supported_color_modes"] == ["hs", "color_temp"]
    assert docs[0]["topic"] == "homeassistant/light/cinenode_key/config"


def test_mqtt_on_message_applies_ha_color(hub, isolated_hub) -> None:
    isolated_hub.lights = [hub.new_light(id="key", connected=True, power=False, mode="cct")]
    bridge = hub.MqttBridge("mqtt://ha.local", None, None, "homeassistant", lambda: "http://x")
    bridge._on_message(
        None,
        None,
        _Msg(
            "cinenode/key/set",
            json.dumps({"state": "ON", "color": {"h": 12, "s": 90}, "brightness": 55}),
        ),
    )
    light = isolated_hub.lights[0]
    assert light["power"] is True
    assert light["mode"] == "hsi"
    assert light["hue"] == 12
    assert light["brightness"] == 55


def test_mqtt_on_message_plain_on_off(hub, isolated_hub) -> None:
    isolated_hub.lights = [hub.new_light(id="key", connected=True, power=False)]
    bridge = hub.MqttBridge("mqtt://ha.local", None, None, "homeassistant", lambda: "http://x")
    bridge._on_message(None, None, _Msg("cinenode/key/set", "ON"))
    assert isolated_hub.lights[0]["power"] is True
    bridge._on_message(None, None, _Msg("cinenode/key/set", "OFF"))
    assert isolated_hub.lights[0]["power"] is False


def test_mqtt_on_message_ignores_unknown_light_and_bad_json(hub, isolated_hub) -> None:
    isolated_hub.lights = [hub.new_light(id="key", connected=True)]
    before = isolated_hub.revision
    bridge = hub.MqttBridge("mqtt://ha.local", None, None, "homeassistant", lambda: "http://x")
    bridge._on_message(None, None, _Msg("cinenode/missing/set", '{"state":"ON"}'))
    bridge._on_message(None, None, _Msg("cinenode/key/set", "{not-json"))
    bridge._on_message(None, None, _Msg("other/topic", "online"))
    assert isolated_hub.revision == before


def test_mqtt_status_online_republishes(hub, isolated_hub) -> None:
    published: list[tuple[str, str]] = []

    class FakeClient:
        def publish(self, topic: str, payload: str, retain: bool = False, qos: int = 0) -> None:
            published.append((topic, payload))

    isolated_hub.lights = [hub.new_light(id="key", connected=True, power=True, mode="cct")]
    bridge = hub.MqttBridge("mqtt://ha.local", None, None, "homeassistant", lambda: "http://studio.local")
    bridge.client = FakeClient()
    bridge._on_message(None, None, _Msg("homeassistant/status", "online"))
    topics = [item[0] for item in published]
    assert "cinenode/hub/availability" in topics
    assert "homeassistant/light/cinenode_key/config" in topics
    assert "cinenode/key/state" in topics


def test_mqtt_connect_subscribes(hub, isolated_hub) -> None:
    calls: list[tuple] = []

    class FakeClient:
        def subscribe(self, topic: str, qos: int = 0) -> None:
            calls.append(("sub", topic, qos))

        def publish(self, topic: str, payload: str, retain: bool = False, qos: int = 0) -> None:
            calls.append(("pub", topic, payload))

    client = FakeClient()
    bridge = hub.MqttBridge("mqtt://ha.local", None, None, "homeassistant", lambda: "http://x")
    bridge.client = client
    isolated_hub.mqtt_status = "connecting"
    isolated_hub.lights = [hub.new_light(id="key", connected=True)]
    bridge._on_connect(client, None, None, SimpleNamespace(value=0))
    assert isolated_hub.mqtt_status == "connected"
    subs = [c[1] for c in calls if c[0] == "sub"]
    assert "cinenode/+/set" in subs
    assert "cinenode/hub/set" in subs
