#!/usr/bin/env python3
"""Read the actual LCD framebuffer over USB. Requires Pillow for PNG output."""
import argparse
from contextlib import contextmanager
import glob
import json
import os
from pathlib import Path
import select
import shlex
import signal
import struct
import subprocess
import termios
import time
import tty

from PIL import Image

ROOT = Path(__file__).resolve().parent
FRAME_HEADER = b"FRAME 320 172 RGB565LE"
FRAME_BYTES = 320 * 172 * 2


@contextmanager
def pause_forwarder():
    """Suspend only this checkout's forwarder; launchd must not respawn it."""
    result = subprocess.run(["ps", "-axo", "pid=,stat=,command="],
                            capture_output=True, text=True, check=True)
    paused = []
    try:
        for line in result.stdout.splitlines():
            fields = line.split(None, 2)
            if len(fields) != 3:
                continue
            try:
                args = shlex.split(fields[2])
            except ValueError:
                continue
            if str(ROOT / "mac_serial_forward.py") not in args[1:]:
                continue
            if "T" in fields[1]:
                continue
            pid = int(fields[0])
            os.kill(pid, signal.SIGSTOP)
            paused.append(pid)
        yield
    finally:
        for pid in paused:
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass


class ScreenCapture:
    def __init__(self, port=None):
        ports = sorted(glob.glob("/dev/cu.usbmodem*"))
        if not port and len(ports) != 1:
            raise RuntimeError("Connect one board, or specify --port")
        self.port = port or ports[0]
        self.fd = None
        self.received = bytearray()

    def __enter__(self):
        self.fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            self.settings = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)
            termios.tcflush(self.fd, termios.TCIFLUSH)
            self.send_bytes(b"\n")  # discard any packet suspended midway through a write
        except BaseException:
            try:
                if hasattr(self, "settings"):
                    termios.tcsetattr(self.fd, termios.TCSANOW, self.settings)
            finally:
                os.close(self.fd)
                self.fd = None
            raise
        return self

    def __exit__(self, *exc):
        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.settings)
        finally:
            os.close(self.fd)
            self.fd = None

    def send(self, packet):
        payload = json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        self.send_bytes(payload)

    def send_bytes(self, payload):
        deadline = time.monotonic() + 5
        for offset in range(0, len(payload), 96):
            chunk = payload[offset:offset + 96]
            while chunk:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Serial write timed out")
                if not select.select([], [self.fd], [], 0.2)[1]:
                    continue
                try:
                    written = os.write(self.fd, chunk)
                except BlockingIOError:
                    continue
                if not written:
                    raise OSError("Serial device disconnected")
                chunk = chunk[written:]
            time.sleep(0.02)

    def _read(self, size, deadline):
        while len(self.received) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("No complete frame; flash firmware with capture support first")
            if not select.select([self.fd], [], [], remaining)[0]:
                continue
            chunk = os.read(self.fd, 65536)
            if not chunk:
                raise OSError("Serial device disconnected")
            self.received.extend(chunk)
        result = bytes(self.received[:size])
        del self.received[:size]
        return result

    def capture(self):
        self.send({"capture": True})
        deadline = time.monotonic() + 8
        header = bytearray()
        while True:
            byte = self._read(1, deadline)
            if byte == b"\n":
                if header.startswith(FRAME_HEADER):
                    break
                header.clear()
            else:
                header.extend(byte)
            if len(header) > 4096:
                raise ValueError("Unexpected serial response")
        raw = self._read(FRAME_BYTES, deadline)
        image = decode_frame(raw)
        fields = header.split()
        if len(fields) == 5:
            image.info["view"] = int(fields[4])
        return image


def decode_frame(raw):
    if len(raw) != FRAME_BYTES:
        raise ValueError("Incomplete RGB565 framebuffer")
    pixels = []
    for (pixel,) in struct.iter_unpack("<H", raw):
        r, g, b = (pixel >> 11) & 31, (pixel >> 5) & 63, pixel & 31
        pixels.append(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)))
    image = Image.new("RGB", (320, 172))
    image.putdata(pixels)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--port")
    args = parser.parse_args()
    with pause_forwarder(), ScreenCapture(args.port) as board:
        image = board.capture()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.resize((640, 344), Image.Resampling.NEAREST).save(args.output)
    print(f"Captured actual LCD framebuffer: {args.output}")


if __name__ == "__main__":
    main()
