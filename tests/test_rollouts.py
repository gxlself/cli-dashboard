from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

import codex_notify
import codex_rollout as rollout
import mac_cli_hub as hub
from test_dashboard import HubFixture

SID = "11111111-1111-1111-1111-111111111111"
OTHER_SID = "22222222-2222-2222-2222-222222222222"
BASE = 1700000000


def record(kind, payload, seconds=0):
    return {"timestamp": datetime.fromtimestamp(BASE + seconds, timezone.utc).isoformat(),
            "type": kind, "payload": payload}


def event(kind, turn="turn-1", seconds=0, **fields):
    return record("event_msg", {"type": kind, "turn_id": turn, **fields}, seconds)


def metadata(sid=SID, source="cli"):
    return record("session_meta", {"id": sid, "source": source, "cwd": "/private/project"})


class RolloutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / f"rollout-2026-09-07T01-00-00-{SID}.jsonl"
        self.monitor = rollout.CodexRolloutMonitor(self.root, BASE + 1)

    def write(self, records, seconds=2, append=False, raw=None, path=None):
        path = path or self.path
        data = raw if raw is not None else b"".join(json.dumps(r).encode() + b"\n" for r in records)
        with path.open("ab" if append else "wb") as stream:
            stream.write(data)
        os.utime(path, (BASE + seconds, BASE + seconds))

    def poll(self, seconds=2):
        return self.monitor.poll(BASE + seconds)

    def test_started_completed_and_trailing_noise(self):
        self.write([metadata(), event("task_started", seconds=2)])
        snapshots, _ = self.poll()
        self.assertTrue(snapshots[SID]["running"])
        self.write([event("task_complete", seconds=3),
                    event("token_count", seconds=3),
                    record("response_item", {"type": "message", "role": "assistant"}, 3)],
                   seconds=3, append=True)
        snapshots, events = self.poll(3)
        self.assertEqual(snapshots[SID]["status"], "done")
        self.assertFalse(snapshots[SID]["running"])
        self.assertEqual(sum(e["notify"] for e in events), 1)
        snapshots, events = self.poll(12)
        self.assertEqual(snapshots[SID]["status"], "idle")
        self.assertEqual(events, [])

    def test_bootstrap_does_not_celebrate_history(self):
        self.write([metadata(), event("task_started", seconds=-2), event("task_complete")])
        snapshots, events = self.poll()
        self.assertIn(SID, snapshots)
        self.assertFalse(any(e["notify"] for e in events))

    def test_new_short_session_discovered_after_completion_still_notifies(self):
        self.poll()
        self.write([metadata(), event("task_started", seconds=9),
                    event("task_complete", seconds=11)], seconds=11)
        snapshots, events = self.poll(12)
        self.assertIn(SID, snapshots)
        self.assertTrue(events[0]["notify"])

    def test_discovery_delay_does_not_lose_short_completion(self):
        self.poll()
        self.write([metadata(), event("task_started", seconds=3),
                    event("task_complete", seconds=4)], seconds=4)
        snapshots, events = self.poll(13)
        self.assertTrue(events[0]["notify"])
        self.assertEqual(snapshots[SID]["status"], "done")

    def test_complete_record_without_start_is_allowed(self):
        self.write([metadata(), event("task_complete", seconds=2)])
        snapshots, events = self.poll()
        self.assertFalse(snapshots[SID]["running"])
        self.assertTrue(events[0]["notify"])

    def test_cancellation_and_terminal_error_do_not_celebrate(self):
        for kind, extra in [("turn_aborted", {}), ("turn_failed", {}),
                            ("task_complete", {"error": "failed"}),
                            ("turn_completed", {"status": "interrupted"})]:
            with self.subTest(kind=kind, extra=extra):
                self.monitor = rollout.CodexRolloutMonitor(self.root, BASE + 1)
                self.write([metadata(), event("task_started", seconds=2),
                            event(kind, seconds=3, **extra)], seconds=3)
                snapshots, events = self.poll(3)
                self.assertFalse(snapshots[SID]["running"])
                self.assertNotEqual(snapshots[SID]["outcome"], "completed")
                self.assertFalse(any(e["notify"] for e in events))

    def test_retry_error_is_not_a_terminal_record(self):
        self.write([metadata(), event("task_started", seconds=2),
                    event("error", seconds=3, will_retry=True)], seconds=3)
        snapshots, _ = self.poll(3)
        self.assertTrue(snapshots[SID]["running"])

    def test_duplicate_and_late_terminal_do_not_end_new_turn(self):
        self.write([metadata(), event("task_started", seconds=2), event("task_complete", seconds=3),
                    event("task_started", seconds=4),  # duplicate start of already finished turn
                    event("task_started", turn="turn-2", seconds=5),
                    event("task_complete", seconds=6)], seconds=6)
        snapshots, events = self.poll(6)
        self.assertEqual(snapshots[SID]["turn"], "turn-2")
        self.assertTrue(snapshots[SID]["running"])
        self.assertEqual(len(events), 1)

    def test_metadata_and_usage_never_start_session(self):
        self.write([metadata(), event("token_count", seconds=2),
                    record("response_item", {"type": "message", "role": "user"}, 2)])
        self.assertEqual(self.poll(), ({}, []))

    def test_subagents_are_not_user_windows(self):
        for source in [{"subagent": {"thread_spawn": {}}}, "subagent"]:
            self.monitor = rollout.CodexRolloutMonitor(self.root, BASE + 1)
            self.write([metadata(source=source), event("task_started", seconds=2),
                        event("task_complete", seconds=3)], seconds=3)
            self.assertEqual(self.poll(3), ({}, []))

    def test_cli_vscode_desktop_and_exec_sources_use_same_events(self):
        for source in ["cli", "vscode", "app-server", "exec"]:
            self.monitor = rollout.CodexRolloutMonitor(self.root, BASE + 1)
            self.write([metadata(source=source), event("task_started", seconds=2)])
            self.assertTrue(self.poll()[0][SID]["running"], source)

    def test_prompt_contents_never_become_title(self):
        self.write([metadata(), event("task_started", seconds=2),
                    event("user_message", seconds=2, message="secret credentials")])
        snapshots, _ = self.poll()
        self.assertEqual(snapshots[SID]["title"], "project")
        self.assertNotIn("secret", json.dumps(snapshots))

    def test_partial_json_waits_for_newline(self):
        self.write([metadata(), event("task_started", seconds=2)])
        self.poll()
        data = json.dumps(event("task_complete", seconds=3)).encode() + b"\n"
        self.write([], raw=data[:30], append=True, seconds=3)
        self.assertTrue(self.poll(3)[0][SID]["running"])
        self.write([], raw=data[30:], append=True, seconds=4)
        snapshots, events = self.poll(4)
        self.assertFalse(snapshots[SID]["running"])
        self.assertEqual(len(events), 1)

    def test_invalid_and_oversized_line_recovers(self):
        self.write([metadata(), event("task_started", seconds=2)])
        self.poll()
        self.write([], raw=b"not json\n" + b"x" * (rollout.MAX_LINE_BYTES + 20) + b"\n",
                   append=True, seconds=3)
        self.write([event("task_complete", seconds=3)], append=True, seconds=3)
        events = []
        for _ in range(4):
            snapshots, new = self.poll(3)
            events.extend(new)
        self.assertEqual(snapshots[SID]["status"], "done")
        self.assertEqual(len(events), 1)

    def test_unchanged_files_are_not_reread(self):
        self.write([metadata(), event("task_started", seconds=2)])
        self.poll()
        with patch.object(Path, "open", side_effect=AssertionError("must not reread")):
            self.assertTrue(self.poll(3)[0][SID]["running"])

    def test_file_replacement_and_truncation_reset_offsets(self):
        self.write([metadata(), event("task_started", seconds=2)])
        self.poll()
        self.path.unlink()
        self.write([metadata(), event("task_complete", turn="new", seconds=3)], seconds=3)
        snapshots, _ = self.poll(3)
        self.assertEqual(snapshots[SID]["turn"], "new")
        self.write([metadata()], seconds=4)
        self.assertEqual(self.poll(4)[0], {})

    def test_deleted_file_removes_presence(self):
        self.write([metadata(), event("task_started", seconds=2)])
        self.poll()
        self.path.unlink()
        self.assertEqual(self.poll(3)[0], {})

    def test_long_turn_survives_idle_window_then_expires_without_heartbeat(self):
        self.write([metadata(), event("task_started", seconds=2)])
        self.poll()
        self.assertTrue(self.poll(600)[0][SID]["running"])
        self.assertEqual(self.poll(1803)[0], {})

    def test_trailing_metadata_does_not_resurrect_old_completed_session(self):
        self.write([metadata(), event("task_complete", seconds=2)])
        self.poll()
        self.write([event("token_count", seconds=600)], append=True, seconds=600)
        self.assertEqual(self.poll(600)[0], {})

    def test_custom_codex_home(self):
        with patch.dict(os.environ, {"CODEX_HOME": str(self.root)}):
            self.assertEqual(rollout.CodexRolloutMonitor().root, self.root / "sessions")

    def test_unknown_schema_is_ignored(self):
        self.write([record("future_record", {"type": "task_started"}, 2)])
        self.assertEqual(self.poll(), ({}, []))

    def test_usage_belongs_to_its_thread(self):
        payload = {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 12000}},
                   "rate_limits": {"primary": {"used_percent": 42}}}
        self.write([metadata(), event("task_started", seconds=2), record("event_msg", payload, 2)])
        snapshots, _ = self.poll()
        self.assertEqual(snapshots[SID]["usage"], "5h 42% | 12k tok")


class LifecycleHubTests(HubFixture, unittest.TestCase):
    def test_rollout_and_notify_through_real_http_server(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(hub.time, "time", return_value=BASE + 3):
            path = Path(directory) / f"rollout-2026-09-07T01-00-00-{SID}.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in [
                metadata(), event("task_started", seconds=2)]))
            os.utime(path, (BASE + 3, BASE + 3))
            monitor = rollout.CodexRolloutMonitor(directory, BASE + 1)
            hub.sync_rollouts(*monitor.poll(BASE + 3))
            server = hub.ThreadingHTTPServer(("127.0.0.1", 0), hub.H)
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}"

            def state():
                with urllib.request.urlopen(url + "/state", timeout=2) as response:
                    return json.load(response)

            try:
                running = state()
                self.assertEqual(running["channels"][1]["status"], "running")
                self.assertEqual(running["channels"][1]["observed"], 1)
                with path.open("a") as stream:
                    stream.write(json.dumps(event("task_complete", seconds=3)) + "\n")
                hub.sync_rollouts(*monitor.poll(BASE + 3))
                for _ in range(2):
                    packet = json.dumps({"cli": "codex", "session": SID, "type": "stop", "turn": "turn-1"})
                    with urllib.request.urlopen(url + "/event", packet.encode(), timeout=2) as response:
                        self.assertEqual(response.status, 200)
                complete = state()
                self.assertEqual(complete["flash"], 1)
                self.assertEqual(complete["channels"][1]["windows"], 1)
                self.assertEqual(complete["channels"][1]["pets"], ["done"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())

    def test_session_start_and_usage_only_do_not_run(self):
        hub.handle_event({"cli": "claude", "session": "one", "type": "start"})
        hub.handle_event({"cli": "claude", "session": "one", "type": "usage", "usage": "week 5%"})
        state = hub.build_state()["channels"][0]
        self.assertEqual(state["status"], "idle")
        self.assertEqual(state["pets"], ["idle"])

    def test_usage_without_lifecycle_does_not_claim_idle(self):
        hub.handle_event({"cli": "claude", "session": "one", "type": "usage", "usage": "week 5%"})
        state = hub.build_state()["channels"][0]
        self.assertEqual(state["status"], "unknown")
        self.assertEqual(state["pets"], ["unknown"])
        self.assertEqual(state["observed"], 0)
        self.assertEqual(state["untracked"], 1)

    def test_stop_does_not_get_reactivated_by_usage(self):
        for kind in ["prompt", "stop", "usage"]:
            hub.handle_event({"cli": "claude", "session": "one", "type": kind})
        state = hub.build_state()["channels"][0]
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["pets"], ["done"])
        self.assertEqual(hub.FLASH, 1)

    def test_duplicate_stop_does_not_replay_animation(self):
        for kind in ["prompt", "stop", "stop"]:
            hub.handle_event({"cli": "codex", "session": "one", "type": kind, "turn": "t1"})
        self.assertEqual(hub.FLASH, 1)

    def test_new_prompt_clears_previous_done_state(self):
        for kind in ["prompt", "stop", "prompt"]:
            hub.handle_event({"cli": "claude", "session": "one", "type": kind})
        state = hub.build_state()["channels"][0]
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["pets"], ["running"])

    def test_cancel_and_error_do_not_flash(self):
        for kind in ["prompt", "cancel", "prompt", "error"]:
            hub.handle_event({"cli": "claude", "session": "one", "type": kind})
        self.assertEqual(hub.FLASH, 0)
        self.assertEqual(hub.build_state()["channels"][0]["status"], "idle")

    def test_hook_and_rollout_completion_deduplicate_in_both_orders(self):
        for reverse in [True, False]:
            hub.TERMINALS.clear()
            hub.STATE["codex"]["sessions"].clear()
            hub.FLASH = 0
            notify = lambda: hub.handle_event({"cli": "codex", "session": SID, "type": "stop", "turn": "t"})
            sync = lambda: hub.sync_rollouts({}, [{"session": SID, "turn": "t", "notify": True, "at": 1}])
            for run in ([notify, sync] if reverse else [sync, notify]):
                run()
            self.assertEqual(hub.FLASH, 1)

    def test_bootstrap_then_notify_does_not_replay_old_completion(self):
        hub.sync_rollouts({}, [{"session": SID, "turn": "t", "notify": False, "at": 1}])
        hub.handle_event({"cli": "codex", "session": SID, "type": "stop", "turn": "t"})
        self.assertEqual(hub.FLASH, 0)

    def test_processes_only_add_untracked_presence(self):
        fake = type("Result", (), {"stdout": "R /tmp/claude\nS claude bg-pty-host\n"
                                  "S claude bg-spare\nR /tmp/codex app-server\n"
                                  "S cursor-agent\nZ claude\n"})()
        with patch.object(hub.subprocess, "run", return_value=fake):
            hub.scan_windows()
        state = hub.build_state()["channels"]
        self.assertEqual(state[0]["untracked"], 1)
        self.assertEqual(state[0]["status"], "unknown")
        self.assertEqual(state[0]["pets"], ["unknown"])
        self.assertEqual(state[1]["windows"], 0)
        self.assertEqual(state[2]["windows"], 1)

    def test_active_session_sorts_ahead_of_recent_presence(self):
        hub.handle_event({"cli": "codex", "session": "a", "type": "prompt", "title": "active"})
        hub.handle_event({"cli": "codex", "session": "b", "type": "usage", "title": "idle"})
        state = hub.build_state()["channels"][1]
        self.assertEqual(state["tasks"][0], "active")
        self.assertEqual(state["pets"], ["running", "unknown"])


class NotifyTests(unittest.TestCase):
    def test_uses_stable_ids_without_prompt_content(self):
        event = codex_notify.completion_event({"type": "agent-turn-complete", "thread-id": SID,
                                              "turn-id": "turn", "input-messages": ["private prompt"],
                                              "cwd": "/private/workspace"})
        self.assertEqual(event, {"cli": "codex", "type": "stop", "session": SID, "turn": "turn",
                                 "title": "workspace"})

    def test_unrelated_or_idless_notification_is_ignored(self):
        for event in [None, [], {}, {"type": "approval-needed", "thread-id": SID, "turn-id": "t"},
                      {"type": "agent-turn-complete"}, {"type": "agent-turn-complete", "thread-id": SID}]:
            self.assertIsNone(codex_notify.completion_event(event))

    def test_passthrough_preserved_for_ignored_event(self):
        raw = '{"type":"unrelated"}'
        with patch.object(codex_notify.sys, "argv", ["codex_notify.py", raw]), \
                patch.object(codex_notify, "ORIG", "/tmp/original-notifier"), \
                patch.object(codex_notify, "_post") as post, \
                patch.object(codex_notify.subprocess, "run") as run:
            with self.assertRaises(SystemExit):
                codex_notify.main()
            post.assert_not_called()
            run.assert_called_once_with(["/tmp/original-notifier", "turn-ended", raw], timeout=10)
