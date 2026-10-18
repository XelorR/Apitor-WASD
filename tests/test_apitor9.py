#!/usr/bin/env python3
"""key-state is attempted by default, warns on failure, and --key-state is gone."""
import os
import pty
import re
import select
import shutil
import subprocess
import sys
import time

from harness import ROOT, PY, APP, NOKS, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test9")
PROGDIR = os.path.join(WORK, "programs")
FAKEHOME = os.path.join(WORK, "home")

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(PROGDIR)
os.makedirs(FAKEHOME)

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


def run_app(extra, keys=b"", first_wait=1.5, key_wait=0.8):
    env = dict(os.environ)
    env["TERM"] = "dumb"
    env["HOME"] = FAKEHOME
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [PY, APP, "--simulate", "--program-dir", PROGDIR, *extra],
        stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
    )
    os.close(slave)
    buf = b""

    def read(timeout):
        nonlocal buf
        end = time.time() + timeout
        while time.time() < end:
            ready, _, _ = select.select([master], [], [], 0.05)
            if ready:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    return
                if not data:
                    return
                buf += data

    read(first_wait)
    if keys:
        for key in keys:
            os.write(master, bytes([key]))
            read(0.2)
        read(key_wait)
    out = buf.decode("utf-8", "replace")
    os.write(master, b"\x03")
    read(0.8)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    return out, proc.returncode


# --- 1. default launch: key-state turns on and the banner says so ----------
out, code = run_app([])
check("default: app starts", code == 0, f"code={code}")
check("default: key-state mode in banner",
      "режим: удержание (стоп в момент отпускания, key-state)" in out, out)
check("default: global-capture hint shown",
      "клавиши ловятся глобально" in out, out)
check("default: no fallback warning", "key-state невключился" not in out, out)

# --- 2. unusable device: warn, fall back, terminal keys still drive --------
out, code = run_app(["--key-state-device", NOKS], keys=b"qw")
check("bogus device: warning is shown",
      "key-state не включился" in out and "работает обычное удержание" in out, out)
check("bogus device: banner shows the fallback",
      "режим: удержание (авто-стоп" in out, out)
check("bogus device: no key-state hint", "ловятся глобально" not in out, out)
check("bogus device: terminal keys still drive", "55aa" in out, out)

# --- 3. --key-state is gone, --key-state-device stays ----------------------
help_out = subprocess.run([PY, APP, "--help"], capture_output=True, text=True).stdout
check("--key-state-device documented", "--key-state-device" in help_out, help_out)
check("no --key-state flag in help", re.search(r"--key-state(?!-device)", help_out) is None,
      re.findall(r"--key-state[^ ]*", help_out))
bad = subprocess.run([PY, APP, "--key-state"], capture_output=True, text=True)
check("old --key-state now rejected",
      bad.returncode == 2 and "unrecognized arguments" in bad.stderr, bad.stderr[-200:])

# --- 4. docs no longer tell users to pass the flag -------------------------
readme = open(os.path.join(ROOT, "README.md")).read()
check("README has no --key-state flag", re.search(r"`--key-state`", readme) is None,
      re.findall(r"`--key-state[^`]*`", readme)[:5])

print(f"failures: {failures}")
sys.exit(1 if failures else 0)
