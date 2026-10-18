#!/usr/bin/env python3
"""K/L are mode selectors (not a toggle): hold vs cruise control."""
import os
import pty
import select
import shutil
import subprocess
import sys
import time

from harness import ROOT, PY, APP, NOKS, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test5")
PROGDIR = os.path.join(WORK, "programs")

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(PROGDIR)

env = dict(os.environ)
env["TERM"] = "dumb"
master, slave = pty.openpty()
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--key-state-device", NOKS, "--program-dir", PROGDIR],
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


def drain(timeout=0.35):
    global buf
    read(timeout)
    text, buf = buf.decode("utf-8", "replace"), b""
    return text


def send(keys, wait=0.35):
    for key in keys:
        os.write(master, key.encode("utf-8"))
        time.sleep(0.12)
    read(wait)
    return drain(0.1)


failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


try:
    out = drain(1.2)
    check("default mode in banner", "режим: удержание" in out, out)
    send(["q"], 1.2)

    out = send(["l"])
    check("l selects cruise control", "круиз-контроль" in out, out)
    out = send(["l"])
    check("l again: still cruise control (no toggle)", "круиз-контроль" in out and "удержание" not in out, out)
    out = send(["k"])
    check("k selects hold", "удержание" in out and "круиз" not in out, out)
    out = send(["k"])
    check("k again: still hold (no toggle)", "удержание" in out and "круиз" not in out, out)

    out = send(["L"])
    check("Shift+L selects cruise control", "круиз-контроль" in out, out)
    out = send(["K"])
    check("Shift+K selects hold", "удержание" in out, out)

    out = send(["д"])   # russian layout: physical l
    check("RU 'д' = l", "круиз-контроль" in out, out)
    out = send(["л"])   # russian layout: physical k
    check("RU 'л' = k", "удержание" in out, out)

    # круиз-контроль: едет и после отпускания (авто-стопа нет)
    send(["l"])
    out = send(["w"], wait=1.3)
    check("cruise: drives on", "вперёд" in out, out)
    check("cruise: no auto-stop", "клавиша отпущена" not in out, out)
    out = send([" "], wait=0.5)
    check("space stops cruise", "стоп" in out, out)

    # hold: auto-stop after release
    send(["k"])
    out = send(["w"], wait=1.3)
    check("hold: auto-stop after release", "клавиша отпущена" in out, out)

    # k/l do nothing in program mode
    send(["p"])
    out = send(["k"])
    check("k does nothing in program mode", "удержание" not in out and "круиз" not in out, out)
    out = send(["l"])
    check("l does nothing in program mode", "удержание" not in out and "круиз" not in out, out)
    send(["\x1b"], 0.4)

    # --latched (прежнее имя флага) включает круиз-контроль
    out = send(["\x03"], wait=1.0)
    check("quit", "Пока" in out, out)
finally:
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    check("exit code 0", proc.returncode == 0, f"code={proc.returncode}")
    os.close(master)

# second run with --latched
master, slave = pty.openpty()
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--key-state-device", NOKS, "--latched", "--program-dir", PROGDIR],
    stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
)
os.close(slave)
buf = b""
try:
    out = drain(1.2)
    check("--latched (прежнее имя) включает круиз-контроль",
          "режим: круиз-контроль" in out, out)
    out = send(["\x03"], wait=1.0)
    check("quit (cruise)", "Пока" in out, out)
finally:
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    os.close(master)

print(f"failures: {failures}")
sys.exit(1 if failures else 0)
