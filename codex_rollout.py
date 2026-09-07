"""Read local Codex lifecycle records without replaying historical completions.

Rollouts are a local, version-dependent format, not a public subscription API.
Unknown records never imply running or completed. No prompt/tool bodies leave
this reader; the display title is only the workspace directory's basename.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import time

ID_PATTERN = re.compile(r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl$")
READ_BYTES = 1024 * 1024
MAX_LINE_BYTES = 2 * 1024 * 1024
DISCOVERY_INTERVAL = 10
IDLE_TTL = 300
RUNNING_TTL = 1800
DONE_WINDOW = 8
NOTIFY_MAX_AGE = 60  # new files may be discovered after the display's done window


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp()
    except (ValueError, OverflowError):
        return None


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    return None


def format_usage(payload):
    parts = []
    limits = payload.get("rate_limits")
    if isinstance(limits, dict):
        for label, key in (("5h", "primary"), ("wk", "secondary")):
            window = limits.get(key)
            if isinstance(window, dict):
                used = number(window.get("used_percent", window.get("used_percentage")))
                if used is not None and 0 <= used <= 100:
                    parts.append(f"{label} {round(used)}%")
    info = payload.get("info")
    total = info.get("total_token_usage") if isinstance(info, dict) else None
    if isinstance(total, dict):
        tokens = number(total.get("total_tokens"))
        if tokens is None:
            tokens = (number(total.get("input_tokens")) or 0) + (number(total.get("output_tokens")) or 0)
        if tokens > 0:
            parts.append(f"{round(tokens / 1000)}k tok")
    return " | ".join(parts)


def is_subagent(metadata):
    for key in ("source", "thread_source"):
        value = metadata.get(key)
        if isinstance(value, dict) and any(k in value for k in ("subagent", "sub_agent")):
            return True
        if isinstance(value, str) and value.lower().startswith(("subagent", "sub_agent")):
            return True
    return False


@dataclass
class Rollout:
    path: Path
    identity: tuple
    session: str
    offset: int = 0
    pending: bytes = b""
    dropping_line: bool = False
    caught_up: bool = False
    hidden: bool = False
    have_metadata: bool = False
    status: str = "idle"
    outcome: str = ""
    turn: str = ""
    title: str = "Codex session"
    usage: str = ""
    state_at: float = 0
    seen_at: float = 0
    usage_at: float = 0
    done_until: float = 0
    finished: dict = field(default_factory=dict)

    def consume(self, record, now):
        if not isinstance(record, dict):
            return None
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return None
        at = timestamp(record.get("timestamp"))
        if at is None:
            return None
        at = min(at, now)
        self.seen_at = max(self.seen_at, at)
        kind = record.get("type")
        if kind in ("session_meta", "turn_context"):
            if kind == "session_meta":
                self.have_metadata = True
                self.hidden = is_subagent(payload)
                sid = payload.get("id") or payload.get("session_id")
                if isinstance(sid, str) and sid:
                    self.session = sid
            cwd = payload.get("cwd")
            if isinstance(cwd, str) and cwd:
                self.title = Path(cwd).name[:60] or "Codex session"
            return None
        if kind != "event_msg":
            return None
        event = payload.get("type")
        if event == "token_count":
            usage = format_usage(payload)
            if usage:
                self.usage, self.usage_at = usage, at
            return None
        starts = ("task_started", "turn_started")
        completes = ("task_complete", "task_completed", "turn_complete", "turn_completed")
        cancels = ("turn_aborted", "task_aborted")
        failures = ("turn_failed", "task_failed")
        if event not in starts + completes + cancels + failures or at < self.state_at:
            return None
        turn = payload.get("turn_id")
        turn = turn if isinstance(turn, str) else ""
        if event in starts:
            turn = turn or f"start:{at}"
            if turn in self.finished:
                return None
            self.turn, self.status, self.outcome = turn, "running", ""
            self.state_at = at
            self.done_until = 0
            return None
        # A delayed terminal record from turn A must not finish the newer turn B.
        if turn and self.turn and turn != self.turn and self.status == "running":
            return None
        turn = turn or self.turn or f"end:{at}"
        if turn in self.finished:
            return None
        result = str(payload.get("status", "")).lower()
        if event in cancels or result in ("cancelled", "canceled", "interrupted", "aborted"):
            outcome = "cancelled"
        elif event in failures or payload.get("error") or result in ("failed", "error"):
            outcome = "failed"
        else:
            outcome = "completed"
        self.finished[turn] = outcome
        while len(self.finished) > 64:
            del self.finished[next(iter(self.finished))]
        self.turn, self.outcome, self.status, self.state_at = turn, outcome, "idle", at
        self.done_until = at + DONE_WINDOW if outcome == "completed" else 0
        return {"session": self.session, "turn": turn, "at": at, "outcome": outcome}

    def read(self, now):
        transitions = []
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            data = stream.read(READ_BYTES)
            self.offset += len(data)
            self.caught_up = self.offset >= os.fstat(stream.fileno()).st_size
        for index, segment in enumerate(data.split(b"\n")):
            if index:
                if not self.dropping_line and self.pending:
                    try:
                        record = json.loads(self.pending)
                    except (ValueError, UnicodeError):
                        record = None
                    transition = self.consume(record, now)
                    if transition:
                        transitions.append(transition)
                self.pending = b""
                self.dropping_line = False
            if not self.dropping_line:
                if len(self.pending) + len(segment) > MAX_LINE_BYTES:
                    self.pending = b""
                    self.dropping_line = True
                else:
                    self.pending += segment
        return transitions

    def snapshot(self, now):
        if not self.caught_up or not self.have_metadata or self.hidden or not self.state_at:
            return None
        active = self.status == "running"
        age = now - (self.seen_at if active else self.state_at)
        if age >= (RUNNING_TTL if active else IDLE_TTL):
            return None
        done = self.outcome == "completed" and now < self.done_until
        return {
            "title": self.title, "status": "running" if active else "done" if done else "idle",
            "running": active, "outcome": self.outcome, "turn": self.turn,
            "ts": self.seen_at, "state_at": self.state_at, "usage": self.usage,
            "usage_at": self.usage_at, "source": "rollout",
            "done_until": self.done_until if done else 0,
        }


class CodexRolloutMonitor:
    def __init__(self, root=None, now=None):
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        self.root = Path(root) if root is not None else home / "sessions"
        self.started_at = time.time() if now is None else now
        self.discovered_at = None
        self.files = {}
        self.errors = 0

    def poll(self, now=None):
        now = time.time() if now is None else now
        if self.discovered_at is None or now - self.discovered_at >= DISCOVERY_INTERVAL:
            self.discovered_at = now
            try:
                for path in self.root.rglob("rollout-*.jsonl"):
                    if path in self.files or path.is_symlink():
                        continue
                    stat = path.stat()
                    match = ID_PATTERN.search(path.name)
                    if match and now - stat.st_mtime < RUNNING_TTL:
                        self.files[path] = Rollout(path, (stat.st_dev, stat.st_ino), match[1])
            except OSError:
                self.errors += 1
        transitions = []
        for path, file in list(self.files.items()):
            try:
                stat = path.stat()
                if now - stat.st_mtime >= RUNNING_TTL:
                    del self.files[path]
                    continue
                identity = (stat.st_dev, stat.st_ino)
                if file.identity != identity or stat.st_size < file.offset:
                    file = self.files[path] = Rollout(path, identity, file.session)
                if stat.st_size > file.offset:
                    for event in file.read(now):
                        if file.have_metadata and not file.hidden:
                            event["notify"] = (event["outcome"] == "completed"
                                               and self.started_at < event["at"] <= now
                                               and now - event["at"] < NOTIFY_MAX_AGE)
                            if event["notify"] and file.turn == event["turn"]:
                                file.done_until = now + DONE_WINDOW
                            transitions.append(event)
            except FileNotFoundError:
                del self.files[path]
            except OSError:
                self.errors += 1
        snapshots = {}
        for file in self.files.values():
            snapshot = file.snapshot(now)
            if snapshot and (file.session not in snapshots
                             or snapshot["state_at"] > snapshots[file.session]["state_at"]):
                snapshots[file.session] = snapshot
        return snapshots, transitions
