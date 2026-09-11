CineNode hub for Windows
========================

Run this on native Windows, not WSL. WSL cannot see the Bluetooth radio,
so Home Assistant would only drive a simulator.

1. Unzip this folder somewhere permanent.
2. Close the official Neewer app.
3. Double-click Start-CineNode.bat
   (first run installs Python packages; it may offer to install Python via winget)
4. Leave the window open. It prints the hub address, for example:
     http://192.168.1.20:8787
5. In CineNode Studio, Hub tab: turn on "Use LAN hub URL" and paste that address.
6. In Home Assistant: enable MQTT (Mosquitto add-on is fine), then restart HA.
   Fixtures appear as lights with a color wheel, color temperature, brightness,
   and scene effects. Dragging color in HA writes HSI to the Neewer GATT characteristic.

MQTT
----
Edit cinenode.json (copied from the example on first run):

  "mqtt": "mqtt://homeassistant.local:1883",
  "mqttUser": "homeassistant",
  "mqttPassword": "your-broker-password"

Or pass flags:

  Start-CineNode.bat --mqtt mqtt://homeassistant.local:1883 --mqtt-user homeassistant --mqtt-password secret

HA publishes JSON to  cinenode/<light-id>/set
The hub publishes state to  cinenode/<light-id>/state
Discovery is retained under homeassistant/light/cinenode_<id>/config

Home Assistant and this PC must be on the same LAN.
If you run HA in WSL or Docker, still run this hub on Windows.
