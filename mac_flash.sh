#!/bin/bash
# Flash the dashboard firmware to the board from the Mac (no Windows needed).
# Pauses the serial forwarder so the upload can grab the port, then resumes it.
set -e
A="/Volumes/Mac/develop/cli_dashboard/acli/arduino-cli"
FQBN="esp32:esp32:esp32c6:CDCOnBoot=cdc"
SKETCH="/Volumes/Mac/develop/cli_dashboard"
PLIST="$HOME/Library/LaunchAgents/com.zeron.cliserial.plist"

PORT=$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)
if [ -z "$PORT" ]; then echo "no board on the Mac (no /dev/cu.usbmodem*)"; exit 1; fi

echo "pausing serial forwarder..."
launchctl unload "$PLIST" 2>/dev/null || true
pkill -f mac_serial_forward.py 2>/dev/null || true
sleep 1

echo "compiling..."
"$A" compile --fqbn "$FQBN" "$SKETCH"
echo "uploading to $PORT..."
"$A" upload -p "$PORT" --fqbn "$FQBN" "$SKETCH"

echo "resuming serial forwarder..."
launchctl load -w "$PLIST" 2>/dev/null || true
echo "done."
