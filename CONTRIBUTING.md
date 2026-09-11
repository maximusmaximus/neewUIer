# Contributing to neewUIer

Nothing reaches `main` untested. Pull requests are required. The same commands run on your machine (pre-push hook) and on GitHub Actions.

## One command

```bash
./scripts/check.sh
```

That is:

1. `python -m compileall` — hub script is valid Python
2. `ruff check` — lint the hub and tests
3. `python hub/cinenode-hub.py --self-test` — known BLE checksums + HA command parse
4. `pytest hub/tests --cov` — protocol, MQTT/HA fixtures, REST round-trip, MQTT subscribe. Coverage must stay above the floor in `pyproject.toml`
5. `npm test` — TypeScript protocol / engine / color / MQTT / catalog (shared HA fixtures with Python)
6. `npm run typecheck`

## Install the hook (once per clone)

```bash
git config core.hooksPath .githooks
```

`git push` then refuses unless `./scripts/check.sh` exits 0.

## Pull requests

1. Branch from `main` — direct pushes to `main` are blocked
2. Add or extend a test for the behaviour you change
   - BLE frames → `hub/tests/test_hub.py` and `src/lib/hub/protocol.test.ts`
   - Home Assistant JSON → `hub/tests/fixtures/ha-commands.json` (Python **and** TypeScript read this file)
   - MQTT subscribe / REST → `hub/tests/test_mqtt.py` / `hub/tests/test_http.py`
3. Run `./scripts/check.sh`
4. Open a PR. The aggregate `ci` job must be green (Python 3.10 + 3.12, Node 22, ruff, coverage). `main` is protected.

## Layout

| Path | What |
| --- | --- |
| `hub/cinenode-hub.py` | BLE + REST + MQTT hub |
| `hub/tests/` | pytest |
| `src/lib/hub/` | TypeScript protocol used by the studio |
| `.github/workflows/ci.yml` | required checks |
| `pyproject.toml` | pytest, ruff, coverage floor |

Do not skip tests with empty `it()` / `pass`. If BLE hardware is unavailable, keep using the in-process hub and HTTP tests — they do not need a radio.
