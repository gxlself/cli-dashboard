#!/usr/bin/env python3
"""Stage esp32:esp32@3.3.8 tool archives for macOS-arm64 via the dl.espressif.cn
github_assets mirror (corp net blocks GitHub), then install the core.
"""
import json
import os
import subprocess

DATA = os.path.expanduser("~/Library/Arduino15")
IDX = os.path.join(DATA, "package_index.json")
STAGING = os.path.join(DATA, "staging", "packages")
ACLI = os.path.expanduser("~/cli_dashboard/acli/arduino-cli")
TARGET = "3.3.8"
HOSTS = ["arm64-apple-darwin", "x86_64-apple-darwin"]
os.makedirs(STAGING, exist_ok=True)

j = json.load(open(IDX))
pkg = next(p for p in j["packages"] if p["name"] == "esp32")
plat = next(p for p in pkg["platforms"] if p["version"] == TARGET)
print("target esp32", plat["version"])


def mirror(url):
    pre = "https://github.com/"
    return ("https://dl.espressif.cn/github_assets/" + url[len(pre):]) if url and url.startswith(pre) else url


def expected_size(u):
    r = subprocess.run(["curl", "-sIL", "--max-time", "20", u], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.lower().startswith("content-length:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except Exception:
                pass
    return 0


def robust(url, fname):
    if not url or not fname:
        return
    if not url.startswith("https://github.com/"):
        print("  skip non-github:", fname)
        return
    mir = mirror(url)
    dest = os.path.join(STAGING, fname)
    exp = expected_size(mir)
    for i in range(60):
        cur = os.path.getsize(dest) if os.path.exists(dest) else 0
        if exp > 0 and cur >= exp:
            break
        print("  %s: %d/%d MB (try %d)" % (fname, cur // 1048576, exp // 1048576, i + 1))
        subprocess.run(["curl", "-L", "-C", "-", "--retry", "3", "--retry-delay", "2",
                        "--speed-limit", "30000", "--speed-time", "15", "-s", "-o", dest, mir])
    cur = os.path.getsize(dest) if os.path.exists(dest) else 0
    print("  %s %s: %d MB" % ("OK" if (exp == 0 or cur >= exp) else "INCOMPLETE", fname, cur // 1048576))


def pick(tool):
    for h in HOSTS:
        for s in tool["systems"]:
            if s["host"] == h:
                return s
    for s in tool["systems"]:
        if s["host"] == "all":
            return s
    return tool["systems"][0] if len(tool["systems"]) == 1 else None


robust(plat.get("url"), plat.get("archiveFileName"))
for dep in plat["toolsDependencies"]:
    tool = next((t for t in pkg["tools"] if t["name"] == dep["name"] and t["version"] == dep["version"]), None)
    if not tool:
        print("  (no tool entry %s %s)" % (dep["name"], dep["version"]))
        continue
    s = pick(tool)
    if not s:
        print("  (no system %s)" % dep["name"])
        continue
    print("tool %s %s [%s]" % (dep["name"], dep["version"], s["host"]))
    robust(s.get("url"), s.get("archiveFileName"))

print("== core install esp32:esp32@%s ==" % TARGET)
subprocess.run([ACLI, "core", "install", "esp32:esp32@%s" % TARGET])
subprocess.run([ACLI, "core", "list"])
print("ALL DONE")
