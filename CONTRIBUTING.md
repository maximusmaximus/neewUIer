# Contributing to neewUIer

Nothing reaches `main` untested. The same commands run on your machine (pre-push hook) and on GitHub Actions.

## One command

```bash
./scripts/check.sh
```

That is:

1. `python hub/cinenode-hub.py --self-test` — known BLE checksums + HA command parse
2. `pytest hub/tests` — protocol, MQTT/HA fixtures, REST round-trip
3. `npm test` — TypeScript protocol / engine / color / MQTT (shared fixtures with Python)
4. `npm run typecheck`

## Install the hook (once per clone)

```bash
git config core.hooksPath .githooks
```

`git push` then refuses unless `./scripts/check.sh` exits 0.

## Pull requests

1. Branch from `main`
2. Add or extend a test for the behaviour you change
   - BLE frames → `hub/tests/test_hub.py` and `src/lib/hub/protocol.test.ts`
   - Home Assistant JSON → `hub/tests/fixtures/ha-commands.json` (Python **and** TypeScript read this file)
3. Run `./scripts/check.sh`
4. Open a PR. The `ci` job must be green. `main` is protected.

## Layout

| Path | What |
| --- | --- |
| `hub/cinenode-hub.py` | BLE + REST + MQTT hub |
| `hub/tests/` | pytest |
| `src/lib/hub/` | TypeScript protocol used by the studio |
| `.github/workflows/ci.yml` | required checks |

Do not skip tests with empty `it()` / `pass`. If BLE hardware is unavailable, keep using the in-process hub and HTTP tests — they do not need a radio.
