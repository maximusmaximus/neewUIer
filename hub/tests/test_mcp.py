from __future__ import annotations

import json


def test_mcp_initialize_lists_tools_and_prompt(hub, isolated_hub) -> None:
    init = hub.mcp_dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init["result"]["serverInfo"]["name"] == "cinenode"
    assert "gaffer" in init["result"]["instructions"].lower()
    tools = hub.mcp_dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {item["name"] for item in tools["result"]["tools"]}
    assert names == {
        "list_lights",
        "list_seen",
        "scan_lights",
        "connect_light",
        "disconnect_light",
        "set_light",
        "set_all",
        "hub_health",
        "list_adapters",
    }
    prompt = hub.mcp_dispatch({"jsonrpc": "2.0", "id": 3, "method": "prompts/get", "params": {"name": "lighting_gaffer"}})
    assert "exactly ONE" in prompt["result"]["messages"][0]["content"]["text"]
    assert hub.mcp_dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_mcp_set_light_and_list(hub, isolated_hub) -> None:
    isolated_hub.lights = [hub.new_light(id="key", name="Key", mac="AA:BB:CC:DD:EE:FF", connected=True, power=False)]
    called = hub.mcp_dispatch(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "set_light", "arguments": {"id": "key", "power": True, "hue": 200, "saturation": 80, "brightness": 40, "mode": "hsi"}},
        }
    )
    payload = json.loads(called["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["light"]["mode"] == "hsi"
    assert payload["light"]["hue"] == 200
    listed = hub.mcp_call_tool("list_lights", {})
    assert listed["lights"][0]["power"] is True
    health = hub.mcp_call_tool("hub_health", {})
    assert health["name"] == "cinenode"
    missing = hub.mcp_call_tool("set_light", {"id": "nope", "power": True})
    assert missing["ok"] is False
    seen = hub.mcp_call_tool("list_seen", {})
    assert seen["ok"] is True
    isolated_hub.last_seen = [{"mac": "C5:02:F5:0D:CA:BA", "name": "(no name)", "reason": "probe", "rssi": -52}]
    seen = hub.mcp_call_tool("list_seen", {})
    assert seen["seen"][0]["mac"].startswith("C5")
    dropped = hub.mcp_call_tool("disconnect_light", {"id": "key"})
    assert dropped["ok"] is True
    assert "AA:BB:CC:DD:EE:FF" in isolated_hub.disconnect_macs
    queued = hub.mcp_call_tool("connect_light", {"id": "key"})
    assert queued["ok"] is True
    assert "AA:BB:CC:DD:EE:FF" in isolated_hub.reconnect_macs
    missing_connect = hub.mcp_call_tool("connect_light", {})
    assert missing_connect["ok"] is False
    isolated_hub.adapters_info = [{"id": "hci0", "name": "hci0", "default": True}]
    radios = hub.mcp_call_tool("list_adapters", {})
    assert radios["ok"] is True
    assert radios["adapters"][0]["name"] == "hci0"
