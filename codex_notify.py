#!/usr/bin/env python3
"""Codex notify -> CLI hub bridge (and pass-through to the existing notifier).

Codex calls:  codex_notify.py <json-event>
Codex fires notify on agent-turn-complete, so we treat it as a completion
event for the Codex channel (sets task title + flashes the LED), then forward
the same event to the original computer-use notifier so nothing breaks.
"""
import glob
import json
import os
import subprocess
import sys
import urllib.request

HUB = "http://127.0.0.1:8722/event"


def codex_usage():
    """Parse the newest Codex session rollout for token usage + rate limits."""
    try:
        files = glob.glob(os.path.expanduser("~/.codex/sessions/**/*.jsonl"), recursive=True)
        if not files:
            return ""
        newest = max(files, key=os.path.getmtime)
        tot = prim = sec = None
        with open(newest) as f:
            for line in f:
                if '"token_count"' not in line:
                    continue
                try:
                    p = json.loads(line).get("payload", {})
                except Exception:
                    continue
                info = p.get("info") or {}
                if info.get("total_token_usage"):
                    tot = info["total_token_usage"]
                rl = p.get("rate_limits") or {}
                if rl.get("primary"):
                    prim = rl["primary"]
                if rl.get("secondary"):
                    sec = rl["secondary"]
        parts = []
        for label, win in (("5h", prim), ("wk", sec)):
            if win:
                pct = win.get("used_percent", win.get("used_percentage"))
                if pct is not None:
                    parts.append("%s %d%%" % (label, round(pct)))
        if tot:
            tk = (tot.get("input_tokens", 0) or 0) + (tot.get("output_tokens", 0) or 0)
            if tk:
                parts.append("%dk tok" % round(tk / 1000))
        return " | ".join(parts)
    except Exception:
        return ""
# original notifier that was configured before we wrapped it
ORIG = "/Users/gaoxiaolong/.codex/computer-use/Codex Computer Use.app/Contents/SharedSupport/SkyComputerUseClient.app/Contents/MacOS/SkyComputerUseClient"
ORIG_LEADING_ARGS = ["turn-ended"]


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
    try:
        ev = json.loads(raw)
    except Exception:
        ev = {}

    # Codex notify fires only on completion with no stable session id, so we use
    # a single presence bucket (windows = 1 when recently active, prunes to 0).
    session = "codex"
    title = ""
    msgs = ev.get("input-messages") or ev.get("input_messages") or []
    if isinstance(msgs, list) and msgs:
        title = str(msgs[-1]).strip().replace("\n", " ")[:60]

    # agent-turn-complete -> register the task then mark done (flash)
    if title:
        _post({"cli": "codex", "session": session, "type": "prompt", "title": title})
    stop = {"cli": "codex", "session": session, "type": "stop"}
    usage = codex_usage()
    if usage:
        stop["usage"] = usage
    _post(stop)

    # pass through to the original notifier (preserve computer-use)
    try:
        subprocess.run([ORIG] + ORIG_LEADING_ARGS + [raw], timeout=10)
    except Exception:
        pass
    sys.exit(0)


def _post(payload):
    try:
        req = urllib.request.Request(
            HUB, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass


if __name__ == "__main__":
    main()
