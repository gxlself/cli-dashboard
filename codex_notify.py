#!/usr/bin/env python3
"""Codex notify -> CLI hub bridge (and pass-through to the existing notifier).

Codex calls:  codex_notify.py <json-event>
The hub deduplicates this fallback with local rollout events using thread and
turn IDs. Never synthesize a prompt or combine completions into one session.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
from codex_rollout import format_usage

HUB = os.environ.get("CLI_HUB", "http://127.0.0.1:8722").rstrip("/") + "/event"


def codex_usage(session):
    """Read only this thread's usage, never the newest unrelated transcript."""
    try:
        if not session or any(ch not in "0123456789abcdef-" for ch in session.lower()):
            return ""
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        files = list((home / "sessions").rglob(f"rollout-*-{session}.jsonl"))
        if not files:
            return ""
        path = max(files, key=lambda p: p.stat().st_mtime)
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 1024 * 1024))
            lines = stream.read().splitlines()
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(record, dict):
                continue
            payload = record.get("payload")
            if (record.get("type") == "event_msg" and isinstance(payload, dict)
                    and payload.get("type") == "token_count"):
                return format_usage(payload)
        return ""
    except Exception:
        return ""
# original Codex computer-use notifier — forward the event so that integration keeps working.
# set CODEX_NOTIFY_ORIG env var to override, or leave empty to skip the passthrough.
ORIG = os.environ.get(
    "CODEX_NOTIFY_ORIG",
    os.path.expanduser(
        "~/.codex/computer-use/Codex Computer Use.app"
        "/Contents/SharedSupport/SkyComputerUseClient.app"
        "/Contents/MacOS/SkyComputerUseClient"
    ),
)
ORIG_LEADING_ARGS = ["turn-ended"]


def completion_event(ev):
    if not isinstance(ev, dict) or ev.get("type") != "agent-turn-complete":
        return None
    session = ev.get("thread-id") or ev.get("thread_id")
    turn = ev.get("turn-id") or ev.get("turn_id")
    if not isinstance(session, str) or not session:
        return None
    # Without a turn ID the lifecycle reader handles completion safely.
    if not isinstance(turn, str) or not turn:
        return None
    stop = {"cli": "codex", "session": session, "turn": turn, "type": "stop"}
    cwd = ev.get("cwd")
    if isinstance(cwd, str) and cwd:
        stop["title"] = Path(cwd).name[:60]
    return stop


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
    try:
        ev = json.loads(raw)
    except Exception:
        ev = {}

    stop = completion_event(ev)
    if stop:
        usage = codex_usage(stop["session"])
        if usage:
            stop["usage"] = usage
        _post(stop)

    # pass through to the original notifier (preserve computer-use)
    try:
        if ORIG:
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
