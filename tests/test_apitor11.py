#!/usr/bin/env python3
"""b/B in remote mode blinks the LED: short flash, color and on/off state kept."""
import os
import pty
import select
import shutil
import subprocess
import sys
import time

from harness import ROOT, PY, APP, NOKS, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test11")
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


env = dict(os.environ)
env["TERM"] = "dumb"
env["HOME"] = FAKEHOME
master, slave = pty.openpty()
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--no-tui", "--program-dir", PROGDIR,
     "--key-state-device", NOKS],
    stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
)
os.close(slave)
buf = b""

LED_OFF, LED_WHITE, LED_BLUE = "55aa0404000000", "55aa04040a0000", "55aa0404060000"


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


def send(keys, wait=0.7):
    for key in keys:
        os.write(master, key.encode())
        read(0.2)
    read(wait)
    global buf
    out = buf.decode("utf-8", "replace")
    buf = b""
    return out


def led_frames(out):
    return [line.split("-> ")[1].strip() for line in out.splitlines() if "[sim] -> 55aa0404" in line]


try:
    read(1.2)
    buf = b""

    out = send(["B"])
    check("B without connection warns",
          "нет подключения" in out and "мигнула" not in out, out)

    out = send(["q"])
    check("connected", "подключено" in out, out)

    out = send(["6"])
    check("blue light on", "подсветка: синий" in out and LED_BLUE in out, out)

    out = send(["B"])
    check("B blinks and keeps the color",
          "мигнула" in out and led_frames(out) == [LED_OFF, LED_BLUE], out)
    check("B does not change the light label", "подсветка: " not in out, out)

    out = send(["0"])
    check("light off", led_frames(out) == [LED_OFF], out)

    out = send(["b"])  # lowercase works too
    check("b on a dark light flashes white and stays off",
          "мигнула" in out and led_frames(out) == [LED_WHITE, LED_OFF], out)

    out = send(["И"])  # Shift+И == Shift+B on the Russian layout
    check("Russian layout Shift+И blinks",
          "мигнула" in out and led_frames(out) == [LED_WHITE, LED_OFF], out)

    out = send(["p"])
    check("program mode", "[prog]" in out, out)
    out = send(["B"])
    check("B does nothing in program mode",
          "мигнула" not in out and not led_frames(out), out)
    out = send(["b"])
    check("b in program mode adds a blink step", "✦" in out, out)

    # run: the program blinks on its own, but B from the remote must stay silent
    out = send(["w", "w"])
    os.write(master, b"\r")
    read(0.4)
    out += send(["B"])
    check("B is ignored during a run", "мигнула" not in out, out)
    read(2.5)  # let the program finish
    buf = b""
    out = send(["B"], wait=0.8)
    check("B works again after the run", "мигнула" in out, out)

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
