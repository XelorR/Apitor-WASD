#!/usr/bin/env python3
"""Unicode symbols: one symbol per action in the editor row; symbols parse in files."""
import importlib.util
import os
import pty
import select
import shutil
import subprocess
import sys
import time

from harness import ROOT, PY, APP, NOKS, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test8")
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
steps, _, _, errors = mod.parse_program("↑5 →2 ↓3 ‖ ✦2 ●3")
got = [(s.kind, s.value) for s in steps]
want = [("fwd", 5), ("right", 2), ("back", 3), ("pause", 1), ("blink", 2), ("color", 3)]
check("symbols parse", got == want and errors == [], f"{got} {errors}")

steps, _, _, errors = mod.parse_program("вперёд 5 вправо 2 назад 3 пауза мигнуть 2 цвет 3")
check("symbols == words",
      [(s.kind, s.value) for s in steps] == want and errors == [], f"{steps} {errors}")

steps, _, _, errors = mod.parse_program("↑ 5, →x3\n")
check("symbols with separators/x", [(s.kind, s.value) for s in steps] ==
      [("fwd", 5), ("right", 3)] and errors == [], f"{steps} {errors}")

steps, _, _, errors = mod.parse_program("●\n")
check("● without a number is an error", not steps and len(errors) == 1, f"{steps} {errors}")

check("one symbol per action",
      mod.step_text(mod.Step("fwd")) == "↑"
      and mod.step_text(mod.Step("back")) == "↓"
      and mod.step_text(mod.Step("left")) == "←"
      and mod.step_text(mod.Step("right")) == "→"
      and mod.step_text(mod.Step("pause")) == "‖"
      and mod.step_text(mod.Step("blink")) == "✦"
      and mod.step_text(mod.Step("color", 3)) == "●3"
      and mod.step_text(mod.Step("fwd", 5)) == "↑5",
      f"{[mod.step_text(mod.Step(k)) for k in ('fwd', 'back', 'left', 'right', 'pause', 'blink')]}")

# save keeps words (files stay human-readable), load understands both
ed = mod.ProgramEditor()
ed.steps = [mod.Step("fwd", 5), mod.Step("color", 3)]
ser = ed.serialize()
check("serialize stays words", "вперёд 5" in ser and "цвет 3" in ser, repr(ser))

# --- end-to-end: symbol file loads, row shows symbols ----------------------
prog = os.path.join(PROGDIR, "symbols.txt")
with open(prog, "w") as fh:
    fh.write("# только значки\nскорость 6\n↑5 →2 ‖ ✦ ●3\n")

env = dict(os.environ)
env["TERM"] = "dumb"
env["HOME"] = WORK
master, slave = pty.openpty()
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--no-tui", "--key-state-device", NOKS, "--program", prog, "--program-dir", PROGDIR,
     "--step-time", "0.05", "--turn-time", "0.05", "--pause-time", "0.05",
     "--blink-time", "0.02"],
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


try:
    read(1.2)
    out = take()
    check("symbol file loads (5 steps)", "5 шагов" in out, out)
    os.write(master, b"q")  # simulate: connect
    read(0.8)
    take()
    os.write(master, b"p")
    read(0.8)
    out = take()
    check("row shows one symbol per action",
          "↑5 · →2 · ‖ · ✦ · ●3" in out, out)
    os.write(master, b"\r")  # run
    read(1.5)
    out = take()
    check("run log shows symbols",
          "▶ ↑5" in out and "▶ ‖" in out and "▶ ✦" in out and "▶ ●3" in out, out)
    check("run finished", "готово" in out, out)
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
