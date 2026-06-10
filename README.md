# CLI Dashboard

An ESP32-C6 LCD gadget that shows real-time activity of your AI CLI tools — Claude Code, Codex, Cursor, and Qoder — with an animated desk pet that reacts to what each tool is doing.

```
┌─────────────────────────────────────────┐
│  Claude  ●          x2                  │
│─────────────────────────────────────────│
│                                         │
│         (≧◡≦) typing...                │
│                                         │
│─────────────────────────────────────────│
│  5h 57%  ctx 17%              ● ○ ○ ○  │
└─────────────────────────────────────────┘
```

The pet bobs and types while a session is running, celebrates with confetti when it finishes, and snores `z z z` when everything is idle.

---

## Hardware

| Part | Notes |
|------|-------|
| [Waveshare ESP32-C6-LCD-1.47](https://www.waveshare.com/esp32-c6-lcd-1.47.htm) | ST7789 display, 320×172, onboard WS2812 RGB LED |
| USB-C cable | data-capable (not charge-only) |
| Mac with Python 3 | hub + serial forwarder run here |

---

## Architecture

```
Other machines                 Mac (hub machine)              ESP32-C6
─────────────                  ─────────────────              ────────
Claude Code                    Claude Code
  claude_hook.py ─────────┐      claude_hook.py ──────────►  
  claude_statusline.py     │      mac_cli_hub.py :8722        cli_dashboard.ino
                           └────► POST /event                 ▲
Cursor                           GET /state ◄───────────────  │
  cursor_hook.py ─────────────►                               │
                                 mac_serial_forward.py ───────┘
Codex                              (polls /state, writes
  codex_notify.py ───────────────►  JSON to USB serial)
```

`mac_cli_hub.py` is the central hub — it collects hook events from any machine on the network and serves an aggregated JSON state. `mac_serial_forward.py` polls that JSON every 2 s and pushes it to the ESP32 over USB serial (no WiFi required on the board).

---

## Setup

### 1. Flash the firmware

Install prerequisites (once):

```bash
# Download arduino-cli into the project folder
mkdir -p acli
curl -fsSL https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_macOS_ARM64.tar.gz | tar -xz -C acli

# Install the ESP32 core
./acli/arduino-cli core install esp32:esp32
```

Flash the board:

```bash
# Plug in the ESP32-C6 via USB-C, then:
bash mac_flash.sh
```

`mac_flash.sh` automatically finds the serial port, compiles, and uploads. It also pauses the serial forwarder while uploading and resumes it after.

### 2. Start the hub (Mac)

```bash
python3 mac_cli_hub.py
# Listening on http://0.0.0.0:8722/
```

The hub persists usage stats in `.hub_usage.json` so quota bars survive restarts.

### 3. Start the serial forwarder (Mac)

Run this in a second terminal (or as a LaunchAgent — see below):

```bash
python3 mac_serial_forward.py
```

It finds `/dev/cu.usbmodem*` automatically, reconnects if the board is unplugged, and sends a `{"sleep":true}` packet when the Mac display is off.

### 4. Register Claude Code hooks (this Mac)

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart":     [{"hooks": [{"type": "command", "command": "python3 /path/to/claude_hook.py start",  "timeout": 10}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python3 /path/to/claude_hook.py prompt", "timeout": 10}]}],
    "Stop":             [{"hooks": [{"type": "command", "command": "python3 /path/to/claude_hook.py stop",   "timeout": 10}]}],
    "SessionEnd":       [{"hooks": [{"type": "command", "command": "python3 /path/to/claude_hook.py end",    "timeout": 10}]}]
  },
  "statusLine": {
    "type": "command",
    "command": "python3 /path/to/claude_statusline.py",
    "padding": 0
  }
}
```

### 5. Connect from another machine

Run the installer on any remote machine, passing this Mac's IP:

```bash
bash install_remote_hooks.sh 192.168.x.x
```

The script:
- Writes `claude_hook.py` and `claude_statusline.py` to `~/.claude/cli_dashboard/`
- Patches `~/.claude/settings.json` automatically
- Tests connectivity to the hub

The hub URL can also be overridden per-machine without re-running the installer:

```bash
export CLI_HUB="http://192.168.x.x:8722"   # add to ~/.zshrc
```

---

## Run as a background service (optional)

To start hub + forwarder automatically on login, create two LaunchAgents:

**`~/Library/LaunchAgents/com.cli.hub.plist`**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cli.hub</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string>
    <string>/Volumes/Mac/develop/cli_dashboard/mac_cli_hub.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
```

**`~/Library/LaunchAgents/com.zeron.cliserial.plist`**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.zeron.cliserial</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string>
    <string>/Volumes/Mac/develop/cli_dashboard/mac_serial_forward.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
```

Load them:

```bash
launchctl load -w ~/Library/LaunchAgents/com.cli.hub.plist
launchctl load -w ~/Library/LaunchAgents/com.zeron.cliserial.plist
```

---

## File reference

| File | Purpose |
|------|---------|
| `cli_dashboard.ino` | ESP32-C6 firmware — LCD rendering, animations, serial JSON parser |
| `cjk_glyphs.h` | 1-bit bitmaps for "创意开发" (splash screen) |
| `welcome_glyphs.h` | 1-bit bitmaps for "主人欢迎回来" (wake animation) |
| `generate_glyphs.py` | Regenerates `cjk_glyphs.h` from font |
| `generate_welcome_glyphs.py` | Regenerates `welcome_glyphs.h` from font |
| `mac_cli_hub.py` | Hub server — aggregates events, serves `/state` JSON |
| `mac_serial_forward.py` | Polls hub, writes state to ESP32 over USB serial |
| `mac_flash.sh` | Compiles and uploads firmware via arduino-cli |
| `mac_stage_core.py` | One-off helper to stage ESP32 core via Espressif mirror |
| `claude_hook.py` | Claude Code hook → hub bridge |
| `claude_statusline.py` | Claude Code statusLine → hub bridge (usage/quota) |
| `cursor_hook.py` | Cursor hook → hub bridge |
| `codex_notify.py` | Codex notify → hub bridge |
| `install_remote_hooks.sh` | Installer for remote machines |

---

## Hub API

```
POST /event   { cli, session, type, title?, usage? }
              type: start | prompt | stop | end | usage

GET  /state   aggregated state JSON consumed by mac_serial_forward.py
GET  /health  "ok"
```

All hooks post to `/event`. The forwarder reads `/state`. Both endpoints are unauthenticated — intended for local network use only.

---

## Display

The BOOT button (GPIO9) cycles through the four channels: Claude → Codex → Cursor → Qoder.

| Pet state | Meaning |
|-----------|---------|
| Typing animation | Session is running |
| Confetti celebration | Just finished (2 s) |
| Snoring `z z z` | No active sessions |

When multiple sessions are active, a row of mini-pets is shown, one per session. The onboard WS2812 LED breathes green on each completion event.
