#!/usr/bin/env python3
"""Shift (hold) = speed boost to 12 in remote mode, only with key-state."""
import importlib.util
import os
import pty
import select
import shutil
import subprocess
import sys
import time

from harness import ROOT, PY, APP, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test12")
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
KEY_W, KEY_A, LSHIFT, RSHIFT = 17, 30, 42, 54

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
    [PY, APP, "--simulate", "--speed", "4", "--key-state-device", KBD,
     "--program-dir", PROGDIR],
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


def event(code, value, wait=0.45):
    os.write(kbd, EVENT.pack(0, 0, 1, code, value))
    read(wait)
    return take()


def key(text, wait=0.45):
    os.write(master, text.encode())
    read(wait)
    return take()


try:
    read(1.4)
    out = take()
    check("startup at speed 4", "скорость 4, режим" in out, out)
    kbd = os.open(KBD, os.O_WRONLY)
    key("q")

    out = event(KEY_W, 1)
    check("W drives at 4", "0104" in out and "вперёд — скорость 4" in out, out)

    out = event(LSHIFT, 1)
    check("left Shift boosts to 12",
          "буст: скорость 12" in out and "010c" in out and "скорость 12" in out, out)

    out = event(LSHIFT, 0)
    check("releasing Shift restores speed 4",
          "скорость как была: 4" in out and "0104" in out, out)

    out = event(KEY_W, 0)
    check("stop after release", "стоп (клавиша отпущена)" in out, out)

    # both shifts: boost ends only when the last one is released
    event(LSHIFT, 1)
    out = event(RSHIFT, 1)
    check("second Shift while boosted is quiet", "буст" not in out, out)
    out = event(LSHIFT, 0)
    check("one Shift still held -> still boosted", "как была" not in out, out)
    out = event(RSHIFT, 0)
    check("last Shift released -> restored", "скорость как была: 4" in out, out)

    # manual speed change while boosted wins
    event(LSHIFT, 1)
    out = key("[")
    check("manual speed change while boosted", "скорость 11" in out, out)
    out = event(LSHIFT, 0)
    check("manual value is kept on release", "как была" not in out, out)
    out = key("[" * 7)  # back to 4 for the next checks
    check("speed back to 4", "скорость 4" in out, out)

    # program editor: no boost
    key("p")
    out = event(LSHIFT, 1)
    check("no boost in the program editor", "буст" not in out, out)
    event(LSHIFT, 0)
    key("\x1b")

    # Shift+Q still disconnects (and the release restores the speed)
    out = event(LSHIFT, 1) + key("Q")
    check("Shift+Q disconnects", "буст" in out and "отключено" in out, out)
    out = event(LSHIFT, 0)
    check("release after Shift+Q restores", "скорость как была: 4" in out, out)

    # key-state dies while boosted -> speed comes back
    key("q")
    event(LSHIFT, 1)
    os.close(kbd)  # last writer gone -> EOF -> key-state lost
    read(1.5)
    out = take()
    check("key-state lost warns", "key-state отключился" in out, out)
    check("speed restored after key-state loss", "скорость как была: 4" in out, out)

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
