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
