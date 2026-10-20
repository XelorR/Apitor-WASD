#!/usr/bin/env python3
"""English UI smoke test (fake HOME, --lang en)."""
import os
import pty
import select
import shutil
import subprocess
import sys
import time

from harness import ROOT, PY, APP, NOKS, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test4")
FAKEHOME = os.path.join(WORK, "home")
PROGDIR = os.path.join(WORK, "programs")

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(PROGDIR)
os.makedirs(FAKEHOME)
stub = os.path.join(WORK, "stub_editor.sh")
with open(stub, "w") as fh:
    fh.write("#!/bin/sh\nprintf 'forward 3\\nright 2\\n' > \"$1\"\n")
os.chmod(stub, 0o755)

env = dict(os.environ)
env.update({"TERM": "dumb", "HOME": FAKEHOME, "EDITOR": stub})
env.pop("VISUAL", None)
master, slave = pty.openpty()
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--no-tui", "--key-state-device", NOKS, "--lang", "en", "--program-dir", PROGDIR],
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
    out = send(["p"])
    check("program mode EN", "(empty)" in out and "Esc — remote" in out, out)
    out = send(["]"])
    check("] raises the speed on an empty program",
          "(empty)" in out and "speed 7" in out, out)
    out = send(["["])
    check("[ lowers the speed back", "speed 6" in out, out)
    out = send(["}"])  # Shift+] on a US layout
    check("Shift+] works like ]", "speed 7" in out, out)
    out = send(["{", "ъ"])  # Shift+[ and the Cyrillic ] key
    check("Shift+[ and Cyrillic ] work", "speed 6" in out and "speed 7" in out, out)
    out = send(["]", "1", "2"])
    check("]12 sets the exact speed", "speed 12" in out, out)
    out = send(["]"])
    check("at the limit the editor says so", "already 12" in out, out)
    out = send(["E"], wait=1.2)
    check("editor EN", "updated from the editor" in out and "↑3" in out, out)
    out = send(["x"])
    check("clear EN", "program cleared" in out, out)
    out = send(["\x1b"], wait=0.5)
    check("remote EN", "[mode] remote" in out, out)
    out = send(["\x03"], wait=1.0)
    check("quit EN", "Bye" in out, out)
finally:
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    check("exit code 0", proc.returncode == 0, f"code={proc.returncode}")
    os.close(master)

print(f"failures: {failures}")
sys.exit(1 if failures else 0)
