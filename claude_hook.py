#!/usr/bin/env python3
"""Claude Code hook -> CLI hub bridge.

Registered for SessionStart / UserPromptSubmit / Stop / SessionEnd.
Usage in settings.json hook command:  python3 claude_hook.py <type>
  <type> = start | prompt | stop | end
Reads the hook JSON on stdin, POSTs a compact event to the local hub.
Always exits 0 (never blocks Claude Code).
"""
import json
import os
import sys
import urllib.request

HUB = os.environ.get("CLI_HUB", "http://127.0.0.1:8722").rstrip("/") + "/event"


def main():
    typ = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    payload = {"cli": "claude", "session": data.get("session_id", "default"), "type": typ}
    if typ == "prompt":
        prompt = data.get("prompt")
        title = prompt.strip().replace("\n", " ") if isinstance(prompt, str) else ""
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
