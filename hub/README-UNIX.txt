CineNode hub for macOS / Linux
==============================

1. Unzip, then:

     chmod +x start-cinenode.sh
     ./start-cinenode.sh

   First run creates a local .venv and downloads bleak if it is missing.

2. Close the official Neewer app so the hub can hold the GATT session.
3. macOS will ask for Bluetooth permission - allow it.
   Linux needs BlueZ; add your user to the bluetooth group if scan fails.
4. The helper prints TWO addresses for the SAME studio. Open exactly one:
     IF the browser is on this computer  ->  http://127.0.0.1:<port>
     IF the browser is on a phone / another computer  ->  the LAN address
   You do not need both. Do not open both.
5. That page is the local studio. Home Assistant is not required.
   Connected lights stop advertising. Unnamed nearby devices are probed.
   A PC radio often stops at 3-8 connections; extras stay listed offline.
   Two Bluetooth adapters: the hub scans every hci* radio in parallel and
   keeps the stronger RSSI copy of each MAC. Pin one with --adapter hci1
   or scan both with --adapter all. List them with --list-adapters.


Agents: python3 cinenode-hub.py --mcp
Prompt: GET /agent.md   (also AGENT.md in this folder)


Home Assistant is optional. To enable MQTT later:

     ./start-cinenode.sh --mqtt mqtt://homeassistant.local:1883

WSL: Bluetooth is not available. Use the Windows zip on the host instead.
