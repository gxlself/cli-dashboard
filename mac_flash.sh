#!/bin/bash
# Flash the dashboard firmware to the board from the Mac (no Windows needed).
# Pauses the serial forwarder so the upload can grab the port, then resumes it.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
A="$SCRIPT_DIR/acli/arduino-cli"
FQBN="esp32:esp32:esp32c6:CDCOnBoot=cdc"
SKETCH="$SCRIPT_DIR"
PLIST="${CLI_SERIAL_PLIST:-$HOME/Library/LaunchAgents/com.cli-dashboard.serial.plist}"
if [ ! -f "$PLIST" ] && [ -f "$HOME/Library/LaunchAgents/com.zeron.cliserial.plist" ]; then
  PLIST="$HOME/Library/LaunchAgents/com.zeron.cliserial.plist"
fi

PORT=$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)
if [ -z "$PORT" ]; then echo "no board on the Mac (no /dev/cu.usbmodem*)"; exit 1; fi

echo "compiling..."
"$A" compile --fqbn "$FQBN" "$SKETCH"

RESUME=0
resume_forwarder() {
  if [ "$RESUME" = 1 ]; then
    echo "resuming serial forwarder..."
    launchctl load "$PLIST"
  fi
}
trap resume_forwarder EXIT
if [ -f "$PLIST" ]; then
  LABEL=$(/usr/libexec/PlistBuddy -c 'Print :Label' "$PLIST")
  if launchctl list "$LABEL" >/dev/null 2>&1; then
    echo "pausing serial forwarder..."
    launchctl unload "$PLIST"
    RESUME=1
    sleep 1
  fi
fi
if lsof -t "$PORT" >/dev/null 2>&1; then
  echo "serial port is busy; stop its owner before flashing: $PORT"
  exit 1
fi
echo "uploading to $PORT..."
"$A" upload -p "$PORT" --fqbn "$FQBN" "$SKETCH"

echo "done."
