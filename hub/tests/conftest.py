from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest


def _hub_path() -> Path:
    env = os.environ.get("HUB_PATH")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / "cinenode-hub.py",
        here.parents[2] / "public" / "cinenode-hub.py",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("cinenode-hub.py not found; set HUB_PATH")


@pytest.fixture(scope="session")
def hub_path() -> Path:
    return _hub_path()


@pytest.fixture(scope="session")
def hub(hub_path: Path):
    spec = importlib.util.spec_from_file_location("cinenode_hub", hub_path)
    if spec is None or spec.loader is None:
        raise ImportError(hub_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cinenode_hub"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def isolated_hub(hub):
    """Restore the process-wide Hub singleton after a test mutates it."""
    original = [dict(item) for item in hub.HUB.lights]
    orig_sim = hub.HUB.simulator
    orig_rev = hub.HUB.revision
    orig_pending = dict(hub.HUB.pending)
    orig_mqtt = hub.HUB.mqtt_status
    orig_on_change = hub.HUB.on_change
    orig_key = hub.HUB.api_key
    orig_scan = hub.HUB.scan_requested
    orig_reconnect = set(hub.HUB.reconnect_macs)
    orig_scan_seconds = hub.HUB.scan_seconds
    orig_seen = list(hub.HUB.last_seen)
    orig_known = dict(hub.HUB.known_macs)
    orig_probe = hub.HUB.probe
    orig_disconnect = set(hub.HUB.disconnect_macs)
    orig_scanning = hub.HUB.scanning
    orig_max = hub.HUB.max_connections
    orig_scan_adapters = list(hub.HUB.scan_adapters)
    orig_prefer = hub.HUB.adapter_prefer
    orig_info = list(hub.HUB.adapters_info)
    orig_dev_adp = dict(hub.HUB.device_adapters)
    orig_scan_mode = hub.HUB.scan_mode
    try:
        yield hub.HUB
    finally:
        hub.HUB.lights = original
        hub.HUB.simulator = orig_sim
        hub.HUB.revision = orig_rev
        hub.HUB.pending = orig_pending
        hub.HUB.mqtt_status = orig_mqtt
        hub.HUB.on_change = orig_on_change
        hub.HUB.clients = {}
        hub.HUB.api_key = orig_key
        hub.HUB.scan_requested = orig_scan
        hub.HUB.reconnect_macs = orig_reconnect
        hub.HUB.scan_seconds = orig_scan_seconds
        hub.HUB.last_seen = orig_seen
        hub.HUB.known_macs = orig_known
        hub.HUB.probe = orig_probe
        hub.HUB.disconnect_macs = orig_disconnect
        hub.HUB.scanning = orig_scanning
        hub.HUB.max_connections = orig_max
        hub.HUB.devices = {}
        hub.HUB.scan_adapters = orig_scan_adapters
        hub.HUB.adapter_prefer = orig_prefer
        hub.HUB.adapters_info = orig_info
        hub.HUB.device_adapters = orig_dev_adp
        hub.HUB.scan_mode = orig_scan_mode
