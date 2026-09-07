import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capture_screen as capture
import generate_screenshots as shots
import mac_cli_hub as hub


class HubFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in {
            "STATE": {cid: {"sessions": {}, "usage": "", "last_done": 0} for cid, _ in hub.CHANNELS},
            "PROC": {cid: 0 for cid, _ in hub.CHANNELS},
            "ROLLOUTS": {}, "TERMINALS": {},
            "FLASH": 0, "LAST_DONE_CLI": "", "FOCUS_CLI": "", "FOCUS_REV": 0,
            "PERSIST": str(Path(self.tmp.name) / "usage.json"),
            "FOCUS_PERSIST": str(Path(self.tmp.name) / "focus.json"),
        }.items():
            self.enterContext(patch.object(hub, name, value))


class HubTests(HubFixture, unittest.TestCase):
    def test_default_focus_does_not_override_button(self):
        state = hub.build_state()
        self.assertNotIn("view", state)
        self.assertEqual(len(state["channels"]), 4)

    def test_focus_revision_changes_only_on_command(self):
        event = {"cli": "codex", "type": "focus"}
        hub.handle_event(event)
        state = hub.build_state()
        self.assertEqual((state["view"], state["focus_rev"]), (1, 1))
        self.assertEqual(hub.build_state(), state)
        hub.handle_event(event)
        self.assertEqual(hub.build_state()["focus_rev"], 2)

    def test_focus_survives_restart_and_honors_environment(self):
        hub.handle_event({"cli": "cursor", "type": "focus"})
        hub.FOCUS_CLI = ""
        hub.FOCUS_REV = 0
        hub._load_focus()
        self.assertEqual((hub.FOCUS_CLI, hub.FOCUS_REV), ("cursor", 1))
        hub.FOCUS_CLI = "qoder"
        hub._load_focus()
        self.assertEqual(hub.FOCUS_CLI, "qoder")

    def test_running_done_and_end(self):
        event = {"cli": "codex", "session": "one", "type": "prompt", "title": "check layout"}
        hub.handle_event(event)
        self.assertEqual(hub.build_state()["channels"][1]["status"], "running")
        hub.handle_event({**event, "type": "stop"})
        state = hub.build_state()
        self.assertEqual(state["flash"], 1)
        self.assertEqual(state["done_cli"], "codex")
        self.assertEqual(state["channels"][1]["pets"], ["done"])
        hub.handle_event({**event, "type": "end"})
        self.assertEqual(hub.build_state()["channels"][1]["windows"], 0)

    def test_maximum_unicode_payload_fits_device_buffer(self):
        for cid, _ in hub.CHANNELS:
            for i in range(8):
                hub.handle_event({"cli": cid, "session": str(i), "type": "prompt",
                                  "title": "\u6d4b" * 60, "usage": "9" * 48})
        payload = json.dumps(hub.build_state(), ensure_ascii=False,
                             separators=(",", ":")).encode()
        self.assertLess(len(payload), 8191)


class RenderTests(unittest.TestCase):
    def test_gallery_has_native_resolution_and_nonblank_content(self):
        for name, render, _ in shots.SHOTS:
            with self.subTest(name=name):
                image = render()
                self.assertEqual(image.size, (320, 172))
                self.assertGreaterEqual(len(image.getcolors(100000)), 3)

    def test_text_bounds_across_channels_and_session_counts(self):
        real_text = shots.text
        bounds = []

        def record(draw, x, y, value, color, fnt=shots.SZ2):
            bounds.append((x, y, x + shots.text_w(value, fnt), y + shots.text_h(fnt), value))
            return real_text(draw, x, y, value, color, fnt)

        with patch.object(shots, "text", side_effect=record):
            for view, name in enumerate(["Claude", "Codex", "Cursor", "Qoder"]):
                for count in [0, 1, 2, 3, 4, 5, 6, 8, 13, 105]:
                    pets = (["running", "done", "idle"] * 3)[:min(count, 8)]
                    shots.screen_channel(name, windows=count, pets=pets, view=view,
                                         usage="X" * 48, task="long title " * 8)
            shots.screen_done()
            shots.screen_offline()
            shots.screen_unknown()
            shots.screen_channel(status="unknown", pets=["unknown"], task="no lifecycle signal")
        for x1, y1, x2, y2, value in bounds:
            self.assertGreaterEqual(x1, 0, value)
            self.assertGreaterEqual(y1, 0, value)
            self.assertLessEqual(x2, 320, value)
            self.assertLessEqual(y2, 172, value)

    def test_long_usage_does_not_overwrite_navigation(self):
        short = shots.screen_channel(usage="5h 42%")
        long = shots.screen_channel(usage="9" * 48)
        self.assertEqual(short.crop((256, 144, 320, 172)).tobytes(),
                         long.crop((256, 144, 320, 172)).tobytes())

    def test_running_frames_move(self):
        a = shots.screen_channel(frame=3)
        b = shots.screen_channel(frame=12)
        self.assertNotEqual(a.crop((30, 40, 290, 125)).tobytes(),
                            b.crop((30, 40, 290, 125)).tobytes())


class CaptureTests(unittest.TestCase):
    def test_rgb565_byte_order(self):
        image = capture.decode_frame(struct.pack("<H", 0xF800) * (320 * 172))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))

    def test_short_frame_rejected(self):
        with self.assertRaises(ValueError):
            capture.decode_frame(b"\0")

    def test_forwarder_resumes_after_capture_failure(self):
        result = type("Result", (), {"stdout":
            f"321 S python3 {capture.ROOT}/mac_serial_forward.py\n"})()
        with patch.object(capture.subprocess, "run", return_value=result), \
                patch.object(capture.os, "kill") as kill:
            with self.assertRaises(TimeoutError):
                with capture.pause_forwarder():
                    raise TimeoutError()
            self.assertEqual(kill.call_args_list[0].args, (321, capture.signal.SIGSTOP))
            self.assertEqual(kill.call_args_list[-1].args, (321, capture.signal.SIGCONT))


if __name__ == "__main__":
    unittest.main()
