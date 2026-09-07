#!/usr/bin/env python3
"""Add this checkout's Claude hooks without overwriting existing integrations."""
import argparse
import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
HOOKS = (("SessionStart", "start"), ("UserPromptSubmit", "prompt"),
         ("Stop", "stop"), ("SessionEnd", "end"))


def configure(settings, root=ROOT, python=sys.executable):
    updated = copy.deepcopy(settings)
    added = []
    hooks = updated.setdefault("hooks", {})
    helper = str(root / "claude_hook.py")
    for event, kind in HOOKS:
        groups = hooks.setdefault(event, [])
        present = False
        for group in groups:
            for hook in group.get("hooks", []):
                try:
                    args = shlex.split(hook.get("command", ""))
                except ValueError:
                    continue
                if helper in args and kind in args:
                    present = True
        if not present:
            groups.append({"hooks": [{"type": "command",
                                      "command": shlex.join([python, helper, kind]), "timeout": 10}]})
            added.append(event)
    if "statusLine" not in updated:
        updated["statusLine"] = {
            "type": "command",
            "command": shlex.join([python, str(root / "claude_statusline.py")]), "padding": 0,
        }
        added.append("statusLine")
    return updated, added


def install(path, apply=False):
    path = path.expanduser().resolve()
    original = path.read_bytes() if path.exists() else None
    settings = json.loads(original) if original is not None else {}
    updated, added = configure(settings)
    if not added or not apply:
        return added, None
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if original is not None:
        fd, name = tempfile.mkstemp(prefix=path.name + ".dashboard-backup-", dir=path.parent)
        os.close(fd)
        backup = Path(name)
        shutil.copy2(path, backup)
    fd, name = tempfile.mkstemp(prefix=".dashboard-settings-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(updated, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        current = path.read_bytes() if path.exists() else None
        if current != original:
            raise RuntimeError("Settings changed during installation; rerun to merge the newer file")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return added, backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path.home() / ".claude/settings.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    added, backup = install(args.settings, args.apply)
    print(("Added: " if args.apply else "Would add: ") + (", ".join(added) or "nothing"))
    if backup:
        print(f"Original settings backed up: {backup}")


if __name__ == "__main__":
    main()
