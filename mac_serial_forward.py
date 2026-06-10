#!/usr/bin/env python3
"""Forward the CLI hub /state JSON to the ESP32 over USB serial (no WiFi, no deps).

Plug the board into the Mac; this polls the local hub and writes one JSON line
per refresh to the board's serial device. Pure stdlib (no pyserial). Keeps the
fd open so the board only resets once on connect; reconnects if unplugged.

Run:  python3 mac_serial_forward.py
"""
import ctypes
import ctypes.util
import glob
import os
import time
import urllib.request

HUB = "http://127.0.0.1:8722/state"
INTERVAL = 2.0


def _load_cg():
    try:
        lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
        lib.CGMainDisplayID.restype = ctypes.c_uint32
        lib.CGDisplayIsAsleep.restype = ctypes.c_int32
        lib.CGDisplayIsAsleep.argtypes = [ctypes.c_uint32]
        return lib
    except Exception:
        return None


_CG = _load_cg()


def is_display_asleep():
    if _CG is None:
        return False
    try:
        return bool(_CG.CGDisplayIsAsleep(_CG.CGMainDisplayID()))
    except Exception:
        return False


def find_port():
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    return ports[0] if ports else None


def main():
    fd = None
    while True:
        if fd is None:
            port = find_port()
            if not port:
                print("waiting for board... plug it into the Mac")
                time.sleep(2)
                continue
            try:
                fd = os.open(port, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
                print("connected:", port)
            except Exception as e:
                print("open failed:", e)
                time.sleep(2)
                continue
        if is_display_asleep():
            data = b'{"sleep":true}'
        else:
            try:
                data = urllib.request.urlopen(HUB, timeout=3).read().strip()
            except Exception as e:
                print("hub error:", e)
                time.sleep(1)
                continue
        # The board's USB-CDC RX buffer is small (~256B); send in small paced
        # chunks so the firmware drains it each loop and never overflows.
        payload = data + b"\n"
        try:
            for i in range(0, len(payload), 96):
                chunk = payload[i:i + 96]
                while chunk:
                    try:
                        n = os.write(fd, chunk)
                        chunk = chunk[n:]
                    except BlockingIOError:
                        time.sleep(0.01)
                time.sleep(0.02)
        except OSError as e:
            print("write error (unplugged/reset?):", e)
            try:
                os.close(fd)
            except Exception:
                pass
            fd = None
            time.sleep(1)
            continue
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
