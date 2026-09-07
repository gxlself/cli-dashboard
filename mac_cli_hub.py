#!/usr/bin/env python3
"""AI CLI dashboard hub.

Collects hook/notify events from Claude Code / Codex / Cursor / Qoder and serves
an aggregated state JSON to the ESP32-C6 LCD gadget.

Endpoints
  POST /event   body JSON: {cli, session, type, title?, usage?}
                  type = start | prompt | stop | end | usage | focus
  GET  /state   -> aggregated state JSON for the device (see build_state)
  GET  /health  -> "ok"

Run:  python3 mac_cli_hub.py [port]      (default 8722)
"""
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from codex_rollout import CodexRolloutMonitor, RUNNING_TTL

PORT = 8722

# fixed channel order + display names (BOOT cycles through these)
CHANNELS = [("claude", "Claude"), ("codex", "Codex"),
            ("cursor", "Cursor"), ("qoder", "Qoder")]

SESSION_TTL = 1800      # forget a session idle longer than this (s)
DONE_WINDOW = 8         # seconds a channel stays "done" after a stop event
WINDOW_FRESH = 300      # a session counts as an open window if seen within this (s)

LOCK = threading.Lock()
# per-cli: sessions {sid: {title, running, ts}}, usage string, last_done ts
STATE = {cid: {"sessions": {}, "usage": "", "last_done": 0.0} for cid, _ in CHANNELS}
ROLLOUTS = {}
TERMINALS = {}          # bounded session+turn deduplication shared with notify hooks
FLASH = 0               # global completion counter; device flashes LED when it grows
LAST_DONE_CLI = ""      # which channel most recently completed
FOCUS_CLI = os.environ.get("CLI_DASHBOARD_FOCUS", "").lower()
FOCUS_REV = 0

# persist usage strings so quota stays displayed when idle / across restarts
PERSIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".hub_usage.json")
FOCUS_PERSIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".hub_focus.json")


def _save_usage():
    try:
        with open(PERSIST, "w") as f:
            json.dump({cid: STATE[cid]["usage"] for cid in STATE}, f)
    except Exception:
        pass


def _load_usage():
    try:
        with open(PERSIST) as f:
            for cid, u in json.load(f).items():
                if cid in STATE:
                    STATE[cid]["usage"] = u
    except Exception:
        pass


def _save_focus():
    try:
        with open(FOCUS_PERSIST, "w") as f:
            json.dump({"cli": FOCUS_CLI, "revision": FOCUS_REV}, f)
    except Exception:
        pass


def _load_focus():
    global FOCUS_CLI, FOCUS_REV
    try:
        with open(FOCUS_PERSIST) as f:
            saved = json.load(f)
            cid = str(saved.get("cli", "")).lower()
            FOCUS_REV = int(saved.get("revision", 0)) & 0xFFFFFFFF
            if FOCUS_CLI not in STATE and cid in STATE:
                FOCUS_CLI = cid
    except Exception:
        pass


# Presence only. Processes with no lifecycle hooks never imply "running".
PROC = {cid: 0 for cid, _ in CHANNELS}
PROC_BASENAME = {"claude": "claude", "cursor": "cursor-agent"}


def scan_windows():
    try:
        result = subprocess.run(["ps", "-axo", "stat=,command="],
                                capture_output=True, text=True, timeout=5, check=True)
    except Exception:
        return
    counts = {cid: 0 for cid, _ in CHANNELS}
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or "Z" in fields[0]:
            continue
        try:
            args = shlex.split(fields[1])
        except ValueError:
            continue
        if not args:
            continue
        base = os.path.basename(args[0])
        subcommand = args[1] if len(args) > 1 else ""
        if subcommand.startswith("bg-") or subcommand in (
                "login", "update", "--version", "--help", "--chrome-native-host", "mcp"):
            continue
        for cid, want in PROC_BASENAME.items():
            if base == want:
                counts[cid] += 1
    with LOCK:
        PROC.update(counts)


def _scan_loop():
    while True:
        scan_windows()
        time.sleep(4)


def _terminal(cli, sid, turn, now, notify):
    global FLASH, LAST_DONE_CLI
    key = (cli, sid, turn)
    if key in TERMINALS:
        return
    TERMINALS[key] = now
    while len(TERMINALS) > 2048:
        del TERMINALS[next(iter(TERMINALS))]
    if notify:
        FLASH += 1
        LAST_DONE_CLI = cli
        STATE[cli]["last_done"] = time.time()


def sync_rollouts(snapshots, transitions):
    with LOCK:
        ROLLOUTS.clear()
        ROLLOUTS.update(snapshots)
        for event in transitions:
            _terminal("codex", event["session"], event["turn"], event["at"], event["notify"])
        if snapshots:
            recent = max(snapshots.values(), key=lambda s: s["usage_at"])
            st = STATE["codex"]
            if recent["usage"] and recent["usage_at"] > st.get("usage_at", 0):
                st["usage"], st["usage_at"] = recent["usage"][:48], recent["usage_at"]
                _save_usage()


def _rollout_loop():
    monitor = CodexRolloutMonitor()
    while True:
        try:
            sync_rollouts(*monitor.poll())
        except Exception as error:
            # Rollout schemas may change; do not leak transcript contents.
            print("rollout scan error:", type(error).__name__, flush=True)
        time.sleep(1)


def _prune(now):
    for cid in STATE:
        s = STATE[cid]["sessions"]
        for sid in [k for k, v in s.items() if now - v["ts"] > SESSION_TTL]:
            del s[sid]


def handle_event(ev):
    global FOCUS_CLI, FOCUS_REV
    if not isinstance(ev, dict):
        raise ValueError("Event must be an object")
    cli = str(ev.get("cli", "")).lower()
    if cli not in STATE:
        return
    sid = str(ev.get("session", "default"))
    typ = str(ev.get("type", ""))
    now = time.time()
    with LOCK:
        st = STATE[cli]
        sess = st["sessions"]
        if typ == "focus":
            FOCUS_CLI = cli
            FOCUS_REV = (FOCUS_REV + 1) & 0xFFFFFFFF
            _save_focus()
            return
        if typ not in ("start", "prompt", "stop", "cancel", "error", "end", "usage"):
            return
        if typ == "end":
            sess.pop(sid, None)
            return
        cur = sess.get(sid, {"title": "", "running": False, "status": "unknown",
                            "ts": now, "state_at": 0, "turn": "", "source": "hook"})
        turn = str(ev.get("turn") or "")
        if typ in ("start", "prompt"):
            if turn and (cli, sid, turn) in TERMINALS:
                return
            if ev.get("title"):
                cur["title"] = str(ev["title"])[:60]
            if typ == "prompt":
                cur.update(running=True, status="running", state_at=now, done_until=0,
                           outcome="", turn=turn or f"hook:{time.time_ns()}")
            elif cur["status"] == "unknown":
                cur.update(status="idle", state_at=now)
            # SessionStart is presence, not the beginning of an assistant turn.
        elif typ in ("stop", "cancel", "error"):
            turn = turn or cur["turn"]
            if turn and cur["turn"] and turn != cur["turn"] and cur["running"]:
                return
            if (cli, sid, turn) in TERMINALS:
                return
            _terminal(cli, sid, turn, now, typ == "stop")
            cur.update(running=False, status="idle", state_at=now, turn=turn,
                       outcome={"stop": "completed", "cancel": "cancelled", "error": "failed"}[typ],
                       done_until=now + DONE_WINDOW if typ == "stop" else 0)
            if ev.get("title"):
                cur["title"] = str(ev["title"])[:60]
        elif typ == "usage":
            if ev.get("title"):
                cur["title"] = str(ev["title"])[:60]
        cur["ts"] = now
        sess[sid] = cur
        if ev.get("usage"):
            st["usage"] = str(ev["usage"])[:48]
            st["usage_at"] = now
            _save_usage()
        _prune(now)


def build_state():
    now = time.time()
    with LOCK:
        _prune(now)
        chans = []
        for cid, name in CHANNELS:
            st = STATE[cid]
            sess = dict(st["sessions"])
            if cid == "codex":
                for sid, rollout in ROLLOUTS.items():
                    hook = sess.get(sid)
                    if hook is None or rollout["state_at"] >= hook["state_at"]:
                        sess[sid] = rollout

            def sstat(v):
                if v.get("status") == "unknown":
                    return "unknown"
                if now < v.get("done_until", 0):
                    return "done"
                return "running" if v.get("running") else "idle"

            live = sorted(
                (v for v in sess.values() if now - v["ts"] <
                 (RUNNING_TTL if v.get("running") else WINDOW_FRESH)),
                key=lambda v: ({"running": 0, "done": 1, "idle": 2, "unknown": 3}[sstat(v)], -v["state_at"]))
            tasks = [v["title"] for v in live if v.get("title")][:5]
            wcount = max(PROC.get(cid, 0), len(live)) if cid != "codex" else len(live)
            observed = sum(sstat(v) != "unknown" for v in live)
            running = any(v["running"] for v in live)
            if running:
                status = "running"
            elif any(sstat(v) == "done" for v in live) or now - st["last_done"] < DONE_WINDOW:
                status = "done"
            elif wcount > observed:
                status = "unknown"
            else:
                status = "idle"

            pets = [sstat(v) for v in live]          # one per known session
            while len(pets) < min(wcount, 8):        # pad open-but-unhooked windows
                pets.append("unknown")
            pets = pets[:8]
            chans.append({
                "id": cid, "name": name,
                "windows": wcount,
                "usage": st["usage"],
                "status": status,
                "tasks": tasks,
                "pets": pets,
                "observed": observed, "untracked": wcount - observed,
            })
        body = {"flash": FLASH, "done_cli": LAST_DONE_CLI, "channels": chans}
        for idx, (cid, _) in enumerate(CHANNELS):
            if cid == FOCUS_CLI:
                body["view"] = idx
                body["focus_rev"] = FOCUS_REV
                break
        return body


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/state"):
            self._send(200, json.dumps(build_state(), ensure_ascii=False, separators=(",", ":")))
        elif self.path.startswith("/health"):
            self._send(200, "ok", "text/plain")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        if not self.path.startswith("/event"):
            self._send(404, "not found", "text/plain")
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            if not 0 <= n <= 65536:
                self._send(413, "event too large", "text/plain")
                return
            raw = self.rfile.read(n) if n else b"{}"
            ev = json.loads(raw or b"{}")
            handle_event(ev)
            cli, typ = str(ev.get("cli", "")).lower(), str(ev.get("type", ""))
            if cli in STATE and typ in ("start", "prompt", "stop", "cancel", "error", "end", "usage", "focus"):
                print(time.strftime("%H:%M:%S"), "event", cli, typ)
            self._send(200, "ok", "text/plain")
        except Exception as e:
            print("bad event:", type(e).__name__)
            self._send(400, "bad", "text/plain")

    def log_message(self, *a):
        pass  # we log events ourselves


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    _load_usage()
    _load_focus()
    threading.Thread(target=_scan_loop, daemon=True).start()
    threading.Thread(target=_rollout_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print(f"CLI hub on http://0.0.0.0:{PORT}/  (/event POST, /state GET)")
    srv.serve_forever()
