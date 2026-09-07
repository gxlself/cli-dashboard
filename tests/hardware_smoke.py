"""Opt-in physical-board regression: python3 tests/hardware_smoke.py."""
import copy
import json
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from capture_screen import ScreenCapture, pause_forwarder

OUTPUT = Path(__file__).resolve().parents[1] / "tmp/hardware-qa"


def live_state():
    with urllib.request.urlopen("http://127.0.0.1:8722/state", timeout=3) as response:
        return json.load(response)


def main():
    live = live_state()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with pause_forwarder(), ScreenCapture() as board:
        before = board.capture()
        original_view = before.info.get("view", live.get("view", 1))

        def snap(name):
            image = board.capture()
            assert len(image.getcolors(100000)) >= 3, name
            image.resize((640, 344), Image.Resampling.NEAREST).save(OUTPUT / f"{name}.png")
            print(f"PASS {name}: view={image.info.get('view')}", flush=True)
            return image

        state = {
            "flash": 0, "done_cli": "", "view": 1, "focus_rev": 900000,
            "channels": [
                {"id": cid, "name": name, "windows": 0, "usage": "",
                 "status": "idle", "tasks": [], "pets": []}
                for cid, name in [("claude", "Claude"), ("codex", "Codex"),
                                  ("cursor", "Cursor"), ("qoder", "Qoder")]
            ],
        }
        try:
            board.send(state)
            time.sleep(2.4)
            idle = snap("idle")
            assert idle.info["view"] == 1

            codex = state["channels"][1]
            codex.update(windows=1, status="running", pets=["running"],
                         usage="5h 42%  ctx 17%",
                         tasks=["\u4f18\u5316\u4eea\u8868\u76d8\u5e03\u5c40\u4e0e\u4e2d\u6587\u4efb\u52a1\u6807\u9898" * 4])
            board.send(state)
            first = snap("working")
            time.sleep(0.3)
            second = snap("working-next")
            assert first.crop((100, 40, 235, 115)).tobytes() != second.crop((100, 40, 235, 115)).tobytes()

            codex.update(windows=13, pets=["running", "done", "idle", "running"] + ["idle"] * 4)
            board.send(state)
            snap("multi")

            state["flash"] = 1
            state["done_cli"] = "claude"
            board.send(state)
            done = snap("done")
            assert done.info["view"] == 1
            time.sleep(2.4)
            restored = snap("after-done")
            assert restored.info["view"] == 1
            assert done.crop((0, 0, 320, 30)).tobytes() != restored.crop((0, 0, 320, 30)).tobytes()

            state["flash"] = 0
            board.send(state)
            state["flash"] = 1
            state["done_cli"] = "cursor"
            board.send(state)
            restarted = snap("done-after-hub-restart")
            assert restarted.getpixel((0, 0)) != restored.getpixel((0, 0))
            time.sleep(2.4)

            maximum = copy.deepcopy(state)
            for channel in maximum["channels"]:
                channel.update(windows=13, tasks=["\u6d4b" * 60] * 5,
                               usage="9" * 48, pets=["idle"] * 8)
            board.send(maximum)
            snap("maximum-payload")

            board.send_bytes(b"x" * 8200 + b"\n")
            board.send({"channels": []})
            board.send({"channels": [None] * 4})
            assert snap("invalid-packets-ignored").info["view"] == 1

            board.send({"sleep": True})
            time.sleep(0.2)
            sleeping = snap("sleep")
            board.send(state)
            time.sleep(2.4)
            awake = snap("awake")
            assert sleeping.tobytes() != awake.tobytes()

            time.sleep(12.3)
            offline = snap("offline")
            assert offline.crop((0, 0, 320, 30)).tobytes() != awake.crop((0, 0, 320, 30)).tobytes()
            board.send(state)
            recovered = snap("recovered")
            assert recovered.info["view"] == 1
        finally:
            current = live_state()
            board.send({**current, "view": original_view, "focus_rev": 900001})
            board.send(current)
            time.sleep(2.4)
            snap("live-restored")
    print(f"Hardware screenshots: {OUTPUT}")


if __name__ == "__main__":
    main()
