#!/usr/bin/env python3
"""key-state end-to-end through a synthetic evdev device (FIFO): press/release drive."""
import importlib.util
import os
import pty
import select
import shutil
import subprocess
import sys
import time

from harness import ROOT, PY, APP, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test10")
PROGDIR = os.path.join(WORK, "programs")
FAKEHOME = os.path.join(WORK, "home")
KBD = os.path.join(WORK, "kbd")

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(PROGDIR)
os.makedirs(FAKEHOME)
os.mkfifo(KBD)

spec = importlib.util.spec_from_file_location("apitor_remote", APP)
mod = importlib.util.module_from_spec(spec)
sys.modules["apitor_remote"] = mod
spec.loader.exec_module(mod)

EVENT = mod._EVENT
KEY_W, KEY_S, KEY_A, KEY_D = 17, 31, 30, 32

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


env = dict(os.environ)
env["TERM"] = "dumb"
env["HOME"] = FAKEHOME
master, slave = pty.openpty()
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--key-state-device", KBD, "--program-dir", PROGDIR],
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


def take():
    global buf
    out = buf.decode("utf-8", "replace")
    buf = b""
    return out


def event(code, value):
    os.write(kbd, EVENT.pack(0, 0, 1, code, value))
    time.sleep(0.3)
    read(0.3)
    return take()


try:
    read(1.5)
    out = take()
    check("key-state on a custom device", "режим: удержание (стоп в момент отпускания, key-state)" in out
          and "key-state (evdev)" in out, out)

    kbd = os.open(KBD, os.O_WRONLY)  # the app already holds the read end

    os.write(master, b"q")  # simulate connect
    read(0.8)
    take()

    # W press -> drives, W release -> stops right away (no hold-timeout)
    out = event(KEY_W, 1)
    check("W press drives", "вперёд" in out and "55aa" in out, out)
    out = event(KEY_W, 0)
    check("W release stops at once", "стоп (клавиша отпущена)" in out, out)

    # S press -> back
    out = event(KEY_S, 1)
    check("S press drives backwards", "назад" in out, out)
    event(KEY_S, 0)

    # hold W, add A: switch to the last pressed; release A -> back to W
    event(KEY_W, 1)
    out = event(KEY_A, 1)
    check("A on top of W -> left", "влево" in out, out)
    out = event(KEY_A, 0)
    check("release A -> W still held", "вперёд" in out, out)
    out = event(KEY_W, 0)
    check("release W -> stop", "стоп (клавиша отпущена)" in out, out)

    # arrows work too (physical binding): ↑ = 103
    out = event(103, 1)
    check("arrow ↑ drives", "вперёд" in out, out)
    event(103, 0)

    # in program mode key-state must not drive
    os.write(master, b"p")
    read(0.5)
    take()
    out = event(KEY_W, 1)
    check("key-state does not drive in program mode",
          "вперёд" not in out and "55aa" not in out, out)
    out = event(KEY_W, 0)
    check("key-state release in program mode is silent", "стоп" not in out, out)

    os.write(master, b"\x1b")  # back to remote
    read(0.5)
    take()
    out = event(KEY_W, 1)
    check("key-state drives again after Esc", "вперёд" in out, out)
    event(KEY_W, 0)

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
