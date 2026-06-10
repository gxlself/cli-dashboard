#!/usr/bin/env bash
# Install CLI dashboard hooks on a remote machine.
# Usage:  bash install_remote_hooks.sh <MAC_IP>
# Example: bash install_remote_hooks.sh 192.168.1.100
#
# What it does:
#   1. Writes claude_hook.py and claude_statusline.py to ~/.claude/cli_dashboard/
#   2. Patches ~/.claude/settings.json to register the hooks + statusLine
#   3. Points all hooks at the Mac hub (HUB_IP:8722)

set -euo pipefail

HUB_IP="${1:-}"
if [[ -z "$HUB_IP" ]]; then
  echo "Usage: bash install_remote_hooks.sh <MAC_IP>"
  echo "Example: bash install_remote_hooks.sh 192.168.1.100"
  exit 1
fi

HUB_URL="http://${HUB_IP}:8722"
INSTALL_DIR="$HOME/.claude/cli_dashboard"
SETTINGS="$HOME/.claude/settings.json"
PYTHON="$(command -v python3 || echo python3)"

echo "==> Hub: $HUB_URL"
echo "==> Install dir: $INSTALL_DIR"
echo "==> Python: $PYTHON"

mkdir -p "$INSTALL_DIR"

# ── claude_hook.py ────────────────────────────────────────────────────────────
cat > "$INSTALL_DIR/claude_hook.py" << PYEOF
#!/usr/bin/env python3
"""Claude Code hook -> CLI hub bridge (remote machine edition)."""
import json, sys, urllib.request, os

HUB = os.environ.get("CLI_HUB", "${HUB_URL}") + "/event"

def main():
    typ = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    payload = {"cli": "claude", "session": data.get("session_id", "default"), "type": typ}
    if typ == "prompt":
        title = (data.get("prompt") or "").strip().replace("\n", " ")
        if title:
            payload["title"] = title[:60]
    try:
        req = urllib.request.Request(
            HUB, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass
    sys.exit(0)

if __name__ == "__main__":
    main()
PYEOF

# ── claude_statusline.py ──────────────────────────────────────────────────────
cat > "$INSTALL_DIR/claude_statusline.py" << PYEOF
#!/usr/bin/env python3
"""Claude Code statusLine -> CLI hub bridge (remote machine edition)."""
import json, sys, urllib.request, os

HUB = os.environ.get("CLI_HUB", "${HUB_URL}") + "/event"

def g(d, *path):
    for k in path:
        if not isinstance(d, dict): return None
        d = d.get(k)
    return d

def main():
    try:
        d = json.load(sys.stdin)
    except Exception:
        d = {}
    session = d.get("session_id", "default")
    fh  = g(d, "rate_limits", "five_hour",  "used_percentage")
    ctx = g(d, "context_window", "used_percentage")
    sname = d.get("session_name") or ""
    parts = []
    if fh  is not None: parts.append("5h %d%%" % round(fh))
    if ctx is not None: parts.append("ctx %d%%" % round(ctx))
    usage = "  ".join(parts)
    if usage or sname:
        payload = {"cli": "claude", "session": session, "type": "usage"}
        if usage:  payload["usage"] = usage
        if sname:  payload["title"] = sname
        try:
            req = urllib.request.Request(
                HUB, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2).read()
        except Exception:
            pass
    model = g(d, "model", "display_name") or ""
    line = (model + "  " + usage).strip()
    print(line if line else "claude")

if __name__ == "__main__":
    main()
PYEOF

chmod +x "$INSTALL_DIR/claude_hook.py" "$INSTALL_DIR/claude_statusline.py"
echo "==> Hook files written."

# ── Patch settings.json ───────────────────────────────────────────────────────
# If settings.json doesn't exist, create a minimal one first.
if [[ ! -f "$SETTINGS" ]]; then
  echo '{}' > "$SETTINGS"
fi

# Use Python to merge hooks into existing settings (preserves all other keys).
"$PYTHON" - "$SETTINGS" "$INSTALL_DIR" "$PYTHON" << 'PYEOF'
import json, sys, os

settings_path = sys.argv[1]
install_dir   = sys.argv[2]
python_bin    = sys.argv[3]

hook_cmd = lambda t: f"{python_bin} {install_dir}/claude_hook.py {t}"
status_cmd = f"{python_bin} {install_dir}/claude_statusline.py"

with open(settings_path) as f:
    s = json.load(f)

hooks = s.setdefault("hooks", {})
for event, arg in [("SessionStart","start"),("UserPromptSubmit","prompt"),
                   ("Stop","stop"),("SessionEnd","end")]:
    hooks[event] = [{"hooks": [{"type": "command",
                                "command": hook_cmd(arg),
                                "timeout": 10}]}]

s["statusLine"] = {"type": "command", "command": status_cmd, "padding": 0}

with open(settings_path, "w") as f:
    json.dump(s, f, indent=2)
print("settings.json updated.")
PYEOF

# ── Quick connectivity test ───────────────────────────────────────────────────
echo "==> Testing connection to hub at ${HUB_URL}/health ..."
if "$PYTHON" -c "import urllib.request; urllib.request.urlopen('${HUB_URL}/health', timeout=3)" 2>/dev/null; then
  echo "    Hub reachable — all done!"
else
  echo "    Hub not reachable yet (is mac_cli_hub.py running on ${HUB_IP}?)."
  echo "    Run on the Mac:  python3 /Volumes/Mac/develop/cli_dashboard/mac_cli_hub.py"
fi

echo ""
echo "Done. Restart Claude Code for hooks to take effect."
PYEOF
