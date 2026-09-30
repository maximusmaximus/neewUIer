CineNode hub for Windows
========================

Run this on native Windows, not WSL. WSL cannot see the Bluetooth radio.

1. Unzip this folder somewhere permanent.
2. Close the official Neewer app.
3. Double-click Start-CineNode.bat
   First run creates a local .venv and downloads bleak if it is missing
   (Python itself is offered via winget when needed).
4. Leave the window open. It prints TWO addresses for the SAME studio, for example:
     IF the browser is on this computer:
         http://127.0.0.1:8787
     IF the browser is on a phone or another computer on Wi-Fi:
         http://192.168.1.20:8787
   Open exactly one. You do not need both.
5. That page is the local studio. Color, power, and scan go over HTTP.
   Home Assistant is not required.
   If only a few lights connect, that is often the PC Bluetooth limit (3-8).
   The hub still lists extras and probes unnamed devices. Tap Scan again.
   Weak advertisements are kept - there is no RSSI cutoff.

   Two Bluetooth radios (Intel built-in + a USB dongle, e.g. TP-Link VID 2357):
   Windows Bleak can listen on only the DEFAULT radio. The hub lists both,
   prefers the USB dongle, and tries to make it the default. If five lights
   are missing, they may sit on the other radio.

     python cinenode-hub.py --list-adapters
     python cinenode-hub.py --adapter all

   --adapter all scans each radio in turn (only while no lights are held).
   If Windows will not switch the default: Device Manager -> Bluetooth ->
   disable "Intel Wireless Bluetooth", leave the USB dongle enabled, then Scan.
   You can also put  "adapter": "all"  or  "adapter": "TP-Link"  in cinenode.json.

6. Optional: in the CineNode website Hub tab, turn on "Use LAN hub URL"
   and paste the address you opened (HTTP pages only).

Agents
------
Same helper, extra flag:

  .venv\Scripts\python.exe cinenode-hub.py --mcp

Or POST JSON-RPC to /mcp. Gaffer prompt: GET /agent.md  (also AGENT.md here)

Tools: list_lights, list_seen, scan_lights, connect_light, disconnect_light,
       set_light, set_all, hub_health, list_adapters

Optional Home Assistant
-----------------------
Only if you already run Mosquitto. Edit cinenode.json (copied from the
example on first run):

  "mqtt": "mqtt://homeassistant.local:1883",
  "mqttUser": "homeassistant",
  "mqttPassword": "your-broker-password"

Or:

  Start-CineNode.bat --mqtt mqtt://homeassistant.local:1883 --mqtt-user homeassistant --mqtt-password secret

HA publishes JSON to  cinenode/<light-id>/set
The hub publishes state to  cinenode/<light-id>/state
If HA lives in WSL or Docker, still run this hub on Windows.
