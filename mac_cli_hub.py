#!/usr/bin/env python3
"""AI CLI dashboard hub.

Collects hook/notify events from Claude Code / Codex / Cursor / Qoder and serves
an aggregated state JSON to the ESP32-C6 LCD gadget.

Endpoints
  POST /event   body JSON: {cli, session, type, title?, usage?}
                  type = start | prompt | stop | end
  GET  /state   -> aggregated state JSON for the device (see build_state)
  GET  /health  -> "ok"

Run:  python3 mac_cli_hub.py [port]      (default 8722)
"""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8722

# fixed channel order + display names (BOOT cycles through these)
CHANNELS = [("claude", "Claude"), ("codex", "Codex"),
            ("cursor", "Cursor"), ("qoder", "Qoder")]

SESSION_TTL = 1800      # forget a session idle longer than this (s)
DONE_WINDOW = 8         # seconds a channel stays "done" after a stop event
WINDOW_FRESH = 300      # a session counts as an open window if seen within this (s)

LOCK = threading.Lock()
# per-cli: sessions {sid: {title, running, ts}}, usage string, last_done ts
STATE = {cid: {"sessions": {}, "usage": "", "last_done": 0.0} for cid, _ in CHANNELS}
FLASH = 0               # global completion counter; device flashes LED when it grows
LAST_DONE_CLI = ""      # which channel most recently completed

# persist usage strings so quota stays displayed when idle / across restarts
PERSIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".hub_usage.json")


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


# open-window counts from process scan (catches idle windows that don't post).
PROC = {cid: 0 for cid, _ in CHANNELS}
PROC_BASENAME = {"claude": "claude", "cursor": "cursor-agent", "codex": "codex"}


def scan_windows():
    try:
        out = subprocess.run(["ps", "-axo", "tty=,command="],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return
    counts = {cid: 0 for cid, _ in CHANNELS}
    for line in out.splitlines():
        p = line.strip().split(None, 1)
        if len(p) < 2:
            continue
        tty, cmd = p[0], p[1]
        # drop the desktop app, our own helpers, and codex computer-use noise
        if any(s in cmd for s in ("/Applications/", "cli_dashboard", "_hook",
                                  "_notify", "mac_cli_hub", "Computer Use",
                                  "computer-use", "extension-host", "codex login")):
            continue
        base = cmd.split()[0].split("/")[-1]
        for cid, want in PROC_BASENAME.items():
            if base != want:
                continue
            # claude/cursor have no no-tty noise -> count headless (bot-spawned)
            # too; codex still has helper noise so require a real terminal.
            if cid == "codex" and tty == "??":
                continue
            counts[cid] += 1
    with LOCK:
        PROC.update(counts)


def _scan_loop():
    while True:
        scan_windows()
        time.sleep(4)


def _prune(now):
    for cid in STATE:
        s = STATE[cid]["sessions"]
        for sid in [k for k, v in s.items() if now - v["ts"] > SESSION_TTL]:
            del s[sid]


def handle_event(ev):
    global FLASH
    cli = str(ev.get("cli", "")).lower()
    if cli not in STATE:
        return
    sid = str(ev.get("session", "default"))
    typ = str(ev.get("type", ""))
    now = time.time()
    with LOCK:
        st = STATE[cli]
        sess = st["sessions"]
        if typ in ("start", "prompt"):
            cur = sess.get(sid, {"title": "", "running": False, "ts": now})
            if ev.get("title"):
                cur["title"] = str(ev["title"])[:60]
            cur["running"] = True
            cur["ts"] = now
            sess[sid] = cur
        elif typ == "stop":
            global LAST_DONE_CLI
            if sid in sess:
                sess[sid]["running"] = False
                sess[sid]["done_until"] = now + DONE_WINDOW   # per-session celebrate
                sess[sid]["ts"] = now
            st["last_done"] = now
            LAST_DONE_CLI = cli
            FLASH += 1
        elif typ == "end":
            sess.pop(sid, None)
        elif typ == "usage":
            # every open window's statusline posts usage -> register/refresh it
            # so the window count reflects all open sessions (title optional).
            cur = sess.get(sid, {"title": "", "running": False, "ts": now})
            if ev.get("title"):
                cur["title"] = str(ev["title"])[:60]
            cur["ts"] = now
            cur["last_usage"] = now      # statusline streams while generating
            sess[sid] = cur
        if ev.get("usage"):
            st["usage"] = str(ev["usage"])[:48]
            _save_usage()
        _prune(now)


def build_state():
    now = time.time()
    with LOCK:
        chans = []
        for cid, name in CHANNELS:
            st = STATE[cid]
            sess = st["sessions"]
            live = sorted((v for v in sess.values() if now - v["ts"] < WINDOW_FRESH),
                          key=lambda v: -v["ts"])
            tasks = [v["title"] for v in live if v.get("title")][:5]
            running = any(v["running"] for v in live)
            if running:
                status = "running"
            elif now - st["last_done"] < DONE_WINDOW:
                status = "done"
            else:
                status = "idle"

            def sstat(v):
                if now < v.get("done_until", 0):
                    return "done"
                # hook flag OR actively streaming statusline updates -> working
                if v.get("running") or now - v.get("last_usage", 0) < 4:
                    return "running"
                return "idle"
            wcount = max(PROC.get(cid, 0), len(live))
            pets = [sstat(v) for v in live]          # one per known session
            while len(pets) < wcount:                # pad open-but-unhooked windows
                pets.append("idle")
            pets = pets[:8]
            chans.append({
                "id": cid, "name": name,
                "windows": wcount,
                "usage": st["usage"],
                "status": status,
                "tasks": tasks,
                "pets": pets,
            })
        return {"flash": FLASH, "done_cli": LAST_DONE_CLI, "channels": chans}


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
            self._send(200, json.dumps(build_state()))
        elif self.path.startswith("/health"):
            self._send(200, "ok", "text/plain")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        if not self.path.startswith("/event"):
            self._send(404, "not found", "text/plain")
            return
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n else b"{}"
        try:
            ev = json.loads(raw or b"{}")
            handle_event(ev)
            print(time.strftime("%H:%M:%S"), "event", ev)
            self._send(200, "ok", "text/plain")
        except Exception as e:
            print("bad event:", e, raw[:200])
            self._send(400, "bad", "text/plain")

    def log_message(self, *a):
        pass  # we log events ourselves


if __name__ == "__main__":
    _load_usage()
    threading.Thread(target=_scan_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print(f"CLI hub on http://0.0.0.0:{PORT}/  (/event POST, /state GET)")
    srv.serve_forever()
