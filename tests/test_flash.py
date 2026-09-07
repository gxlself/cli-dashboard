import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "darwin", "LaunchAgent script targets macOS")
class FlashScriptTests(unittest.TestCase):
    def run_flash(self, **options):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copy(Path(__file__).resolve().parents[1] / "mac_flash.sh", root)
            (root / "acli").mkdir()
            (root / "bin").mkdir()
            plist = root / "serial.plist"
            plist.write_bytes(plistlib.dumps({"Label": "dashboard-test-only"}))
            log = root / "calls.log"
            programs = {
                root / "acli/arduino-cli": """
echo "$1" >> "$CALL_LOG"
if [ "$1" = compile ]; then exit "${COMPILE_EXIT:-0}"; fi
exit "${UPLOAD_EXIT:-0}"
""",
                root / "bin/ls": 'echo /dev/mock-board',
                root / "bin/lsof": 'exit 1',
                root / "bin/sleep": 'exit 0',
                root / "bin/launchctl": """
if [ "$1" = list ]; then exit "${LIST_EXIT:-0}"; fi
echo "$1" >> "$CALL_LOG"
""",
            }
            for path, body in programs.items():
                path.write_text("#!/bin/bash\n" + body + "\n")
                path.chmod(0o755)
            environment = {**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
                           "CLI_SERIAL_PLIST": str(plist), "CALL_LOG": str(log),
                           **{key: str(value) for key, value in options.items()}}
            result = subprocess.run(["bash", str(root / "mac_flash.sh")], env=environment,
                                    capture_output=True, text=True, timeout=10)
            return result.returncode, log.read_text().splitlines()

    def test_compile_failure_does_not_stop_forwarder(self):
        status, calls = self.run_flash(COMPILE_EXIT=1)
        self.assertNotEqual(status, 0)
        self.assertEqual(calls, ["compile"])

    def test_upload_failure_restores_forwarder(self):
        status, calls = self.run_flash(UPLOAD_EXIT=1)
        self.assertNotEqual(status, 0)
        self.assertEqual(calls, ["compile", "unload", "upload", "load"])

    def test_success_restores_forwarder(self):
        status, calls = self.run_flash()
        self.assertEqual(status, 0)
        self.assertEqual(calls, ["compile", "unload", "upload", "load"])

    def test_unloaded_service_remains_unloaded(self):
        status, calls = self.run_flash(LIST_EXIT=1)
        self.assertEqual(status, 0)
        self.assertEqual(calls, ["compile", "upload"])
