#!/usr/bin/env python3
"""up/down/left/right/rght are valid program statements."""
import importlib.util
import os
import pty
import select
import shutil
import subprocess
import sys
import time

from harness import ROOT, PY, APP, NOKS, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test7")
PROGDIR = os.path.join(WORK, "programs")

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(PROGDIR)

spec = importlib.util.spec_from_file_location("apitor_remote", APP)
mod = importlib.util.module_from_spec(spec)
sys.modules["apitor_remote"] = mod
spec.loader.exec_module(mod)

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


# --- parser unit checks ----------------------------------------------------
steps, repeat, speed, errors = mod.parse_program(
    "up 2\ndown 3\nleft\nright 2\nrght\nUP 4\nRIGHT 2\n")
got = [(s.kind, s.value) for s in steps]
want = [("fwd", 2), ("back", 3), ("left", 1), ("right", 2), ("right", 1),
        ("fwd", 4), ("right", 2)]
check("up/down/left/right/rght parse", got == want, f"got {got}")
check("no errors", errors == [], f"errors {errors}")

steps, repeat, speed, errors = mod.parse_program("speed 5\nup\ndown")
check("works with headers", speed == 5 and [(s.kind, s.value) for s in steps] ==
      [("fwd", 1), ("back", 1)] and errors == [], f"{speed} {steps} {errors}")

steps, repeat, speed, errors = mod.parse_program("upp 2\n")
check("'upp' still an error", errors and not steps, f"{steps} {errors}")

steps, repeat, speed, errors = mod.parse_program("rght 3 right 1\n")
check("rght equals right", [(s.kind, s.value) for s in steps] ==
      [("right", 3), ("right", 1)] and errors == [], f"{steps} {errors}")

# --- end-to-end: load a file with the new words ----------------------------
prog = os.path.join(PROGDIR, "words.txt")
with open(prog, "w") as fh:
    fh.write("up 2\ndown 3\nleft\nrght 4\n")

env = dict(os.environ)
env["TERM"] = "dumb"
master, slave = pty.openpty()
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--no-tui", "--key-state-device", NOKS, "--program", prog, "--program-dir", PROGDIR],
    stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
)
os.close(slave)
buf = b""


def read(timeout):
    global buf
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


try:
    read(1.2)
    out = buf.decode("utf-8", "replace")
    buf = b""
    check("file with new words loads (4 steps)", "4 шага" in out, out)
    os.write(master, b"p")
    read(0.8)
    out = buf.decode("utf-8", "replace")
    check("steps shown in program mode",
          "↑2" in out and "↓3" in out and "←" in out and "→4" in out,
          out)
    os.write(master, b"\x03")
    read(1.0)
finally:
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    check("exit 0", proc.returncode == 0, f"code={proc.returncode}")
    os.close(master)

print(f"failures: {failures}")
sys.exit(1 if failures else 0)
