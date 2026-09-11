# neewUIer

[![CI](https://github.com/maximusmaximus/neewUIer/actions/workflows/ci.yml/badge.svg)](https://github.com/maximusmaximus/neewUIer/actions/workflows/ci.yml)

Local control for **Neewer** Bluetooth lights. No vendor app. A small hub on your LAN talks GATT, and any browser or Home Assistant on the same network can set power, CCT, HSI color, scenes, looks, and patterns.

Studio: CineNode in the browser. Radio: the Python hub in this repo.

**GitHub:** [github.com/maximusmaximus/neewUIer](https://github.com/maximusmaximus/neewUIer)

## Checks (required)

Nothing is merged to `main` unless this gate is green. Run it before every push:

```bash
./scripts/check.sh
```

Or `make check`. Enable the local pre-push hook once:

```bash
git config core.hooksPath .githooks
```

CI (GitHub Actions) runs the same Python self-test, pytest, Node unit tests, and `tsc` on every pull request. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Why


The official Neewer app holds the Bluetooth session and blocks other clients. These fixtures speak a documented BLE protocol (`0x78` frames on service `69400001-…`). This hub claims that session so you can automate them.

## Download helpers

From the studio, grab the pack for your OS (first screen, or Hub):

| OS | Run |
| --- | --- |
| **Windows** (native — not WSL) | `Start-CineNode.bat` |
| macOS | `./start-cinenode.sh` |
| Linux | `./start-cinenode.sh` |

Or from this repo:

```bash
python3 -m pip install bleak paho-mqtt
python3 hub/cinenode-hub.py --mqtt mqtt://homeassistant.local:1883
```

Close the Neewer app first. WSL cannot see the Windows Bluetooth adapter — run the Windows pack on the host.

## Home Assistant

The hub **subscribes** to `cinenode/<light-id>/set` (HA JSON light schema: HS color, color temperature, brightness, effects) and publishes state plus MQTT discovery.

```
python3 hub/cinenode-hub.py --mqtt mqtt://homeassistant.local:1883 --mqtt-user homeassistant --mqtt-password secret
```

Restart HA. Fixtures appear as lights. The color wheel writes HSI over BLE as you drag.

REST is also available for looks and patterns if you do not want MQTT.

## Protocol (short)

- Service `69400001-b5a3-f393-e0a9-e50e24dcca99`
- Write `69400002-…` / notify `69400003-…`
- Frame: `78 <cmd> <len> <payload…> <checksum>` where checksum is the low 8 bits of the sum

Examples:

- Power on `78 81 01 01 fb`
- HSI hue 88 sat 24 bri 100 `78 86 04 58 00 18 64 d6`
- CCT 100% 5600 K `78 87 02 64 38 9d`

## Simulator

The live studio does **not** pretend lights are connected. Open **Simulator** in the app to play with demo fixtures. That view never writes to a radio.

## License

MIT
