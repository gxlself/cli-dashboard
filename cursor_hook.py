#!/usr/bin/env python3
"""Cursor CLI hook -> CLI hub bridge.

Registered in ~/.cursor/hooks.json for sessionStart / beforeSubmitPrompt / stop / sessionEnd.
Usage:  cursor_hook.py <type>   (type = start | prompt | stop | end)
Reads the hook JSON on stdin, POSTs a compact event to the local hub.
Never blocks Cursor (exit 0, no blocking output).
"""
import json
import sys
import urllib.request

HUB = "http://127.0.0.1:8722/event"


def main():
    typ = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        d = json.load(sys.stdin)
    except Exception:
        d = {}
    session = str(d.get("session_id") or d.get("conversation_id")
                  or d.get("conversationId") or d.get("threadId")
                  or d.get("thread_id") or "default")
    payload = {"cli": "cursor", "session": session, "type": typ}
    if typ == "prompt":
        title = d.get("prompt") or d.get("text") or d.get("message") or ""
        if isinstance(title, str) and title.strip():
            payload["title"] = title.strip().replace("\n", " ")[:60]
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
