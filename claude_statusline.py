#!/usr/bin/env python3
"""Claude Code statusLine -> CLI hub bridge (the only source of cost/quota).

settings.json statusLine.command:  python3 claude_statusline.py
Reads the rich statusline JSON on stdin, POSTs usage (5h / weekly / cost / ctx)
to the hub, and prints a short status string for the terminal.

Field names for cost/context/rate_limits are verified against the real JSON
which we also dump to DEBUG_RAW for inspection.
"""
import json
import sys
import urllib.request

HUB = "http://127.0.0.1:8722/event"
DEBUG_RAW = "/tmp/claude_statusline_raw.json"


def g(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def main():
    try:
        d = json.load(sys.stdin)
    except Exception:
        d = {}
    # dump latest raw JSON so we can confirm the real schema
    try:
        with open(DEBUG_RAW, "w") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass

    session = d.get("session_id", "default")
    cost = g(d, "cost", "total_cost_usd")
    ctx = g(d, "context_window", "used_percentage")
    fh = g(d, "rate_limits", "five_hour", "used_percentage")
    wk = g(d, "rate_limits", "seven_day", "used_percentage")

    # bottom line shows only 5h quota + context usage (per user preference)
    parts = []
    if fh is not None:
        parts.append("5h %d%%" % round(fh))
    if ctx is not None:
        parts.append("ctx %d%%" % round(ctx))
    usage = "  ".join(parts)

    sname = d.get("session_name") or ""   # Claude's auto-generated elegant title
    if usage or sname:
        payload = {"cli": "claude", "session": session, "type": "usage"}
        if usage:
            payload["usage"] = usage
        if sname:
            payload["title"] = sname
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
