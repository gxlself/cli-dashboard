#!/usr/bin/env python3
"""Claude Code hook -> CLI hub bridge.

Registered for SessionStart / UserPromptSubmit / Stop / SessionEnd.
Usage in settings.json hook command:  python3 claude_hook.py <type>
  <type> = start | prompt | stop | end
Reads the hook JSON on stdin, POSTs a compact event to the local hub.
Always exits 0 (never blocks Claude Code).
"""
import json
import sys
import urllib.request

HUB = "http://127.0.0.1:8722/event"


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
    if typ == "stop":   # capture raw payload to learn the cancel-vs-complete signal
        try:
            with open("/tmp/claude_stop_raw.jsonl", "a") as fdbg:
                fdbg.write(json.dumps(data) + "\n")
        except Exception:
            pass
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
