CineNode hub for macOS / Linux
==============================

1. Unzip, then:

     chmod +x start-cinenode.sh
     ./start-cinenode.sh --mqtt mqtt://homeassistant.local:1883

2. Close the official Neewer app so the hub can hold the GATT session.
3. macOS will ask for Bluetooth permission — allow it.
   Linux needs BlueZ; add your user to the bluetooth group if scan fails.
4. Point CineNode Studio (Hub tab) at the printed address.
5. Home Assistant on the same LAN gets JSON lights with a color wheel via MQTT.

Edit cinenode.json to store the broker URL, user, and password.

WSL: Bluetooth is not available. Use the Windows zip on the host instead.
Home Assistant inside WSL can still control lights by talking to the Windows hub.
