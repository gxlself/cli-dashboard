import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import claude_hook
import install_local_hooks as installer


class HookInstallerTests(unittest.TestCase):
    def test_existing_hooks_settings_and_statusline_are_preserved(self):
        settings = {"model": "existing", "hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "existing-integration"}
        ]}]}, "statusLine": {"type": "command", "command": "existing-statusline"}}
        updated, added = installer.configure(settings)
        self.assertEqual(updated["hooks"]["Stop"][0], settings["hooks"]["Stop"][0])
        self.assertEqual(updated["statusLine"], settings["statusLine"])
        self.assertEqual(updated["model"], "existing")
        self.assertNotIn("statusLine", added)
        self.assertEqual(len(settings["hooks"]["Stop"]), 1)

    def test_repeated_installs_are_idempotent(self):
        first, _ = installer.configure({})
        second, added = installer.configure(first)
        self.assertEqual(second, first)
        self.assertEqual(added, [])

    def test_paths_with_spaces_are_shell_quoted(self):
        updated, _ = installer.configure({}, Path("/tmp/my project"), "/tmp/python bin")
        import shlex
        command = updated["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        self.assertEqual(shlex.split(command),
                         ["/tmp/python bin", "/tmp/my project/claude_hook.py", "start"])

    def test_apply_creates_exact_backup_and_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original = b'{"model": "existing"}\n'
            path.write_bytes(original)
            added, backup = installer.install(path)
            self.assertTrue(added)
            self.assertIsNone(backup)
            self.assertEqual(path.read_bytes(), original)
            _, backup = installer.install(path, apply=True)
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(json.loads(path.read_bytes())["model"], "existing")
            self.assertEqual(installer.install(path, apply=True), ([], None))

    def test_hook_payload_does_not_dump_raw_stop_transcript(self):
        raw = json.dumps({"session_id": "s", "transcript_path": "private-path"})
        with patch.object(claude_hook.sys, "argv", ["claude_hook.py", "stop"]), \
                patch.object(claude_hook.sys, "stdin", io.StringIO(raw)), \
                patch.object(claude_hook.urllib.request, "urlopen") as request, \
                patch("builtins.open", side_effect=AssertionError("raw debug dump")):
            with self.assertRaises(SystemExit):
                claude_hook.main()
            payload = json.loads(request.call_args.args[0].data)
            self.assertEqual(payload, {"cli": "claude", "session": "s", "type": "stop"})
