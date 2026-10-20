#!/usr/bin/env python3
"""While the external editor is open, apitor keys must go to the editor."""
import os
import pty
import select
import shutil
import subprocess
import sys
import time

from harness import ROOT, PY, APP, NOKS, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test3")
PROGDIR = os.path.join(WORK, "programs")
RECEIVED = os.path.join(WORK, "from_stdin.txt")

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(PROGDIR)
stub = os.path.join(WORK, "stub_editor.sh")
with open(stub, "w") as fh:
    fh.write("#!/bin/sh\n")
    fh.write("read -r line\n")
    fh.write(f"printf '%s' \"$line\" > {RECEIVED}\n")
    fh.write("printf 'вперёд 5\\n' > \"$1\"\n")
os.chmod(stub, 0o755)

env = dict(os.environ)
env["TERM"] = "dumb"
env["EDITOR"] = stub
master, slave = pty.openpty()
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--no-tui", "--key-state-device", NOKS, "--program-dir", PROGDIR],
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
    drain(1.0)
    send(["q"], 1.2)
    send(["p"])
    out = send(["w"])
    check("program built", "↑" in out and "1 шаг" in out, out)

    send(["E"], wait=0.1)  # editor starts and blocks reading stdin
    time.sleep(0.5)
    os.write(master, b"x1\n")  # these must go to the editor, not the app
    time.sleep(0.2)
    read(1.2)
    out = drain(0.2)

    check("editor reload applied", "↑5" in out, out)
    check("x NOT handled by app during editor", "очищена" not in out, out)
    check("1 NOT handled by app during editor", "подсветка" not in out, out)
    received = open(RECEIVED).read() if os.path.exists(RECEIVED) else "<missing>"
    check("editor received the keystrokes", received == "x1", received)

    out = send(["\x1b"], wait=0.5)
    check("Esc after editor -> remote", "пульт" in out, out)
    out = send(["p"])
    check("program survives", "↑5" in out, out)
    out = send(["\x03"], wait=1.0)
    check("quit", "Пока" in out, out)
finally:
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    check("exit code 0", proc.returncode == 0, f"code={proc.returncode}")
    os.close(master)

print(f"failures: {failures}")
sys.exit(1 if failures else 0)
