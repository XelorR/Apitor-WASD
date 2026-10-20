#!/usr/bin/env python3
"""--no-key-state: слежение за клавишами выключено совсем (и флаг есть в справке)."""
import fcntl
import importlib.util
import os
import pty
import select
import shutil
import struct
import subprocess
import sys
import termios
import time

from harness import ROOT, PY, APP, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test18")

spec = importlib.util.spec_from_file_location("apitor_remote", APP)
mod = importlib.util.module_from_spec(spec)
sys.modules["apitor_remote"] = mod
spec.loader.exec_module(mod)

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


# -- аргументы --------------------------------------------------------------- #
args = mod.build_parser().parse_args([])
check("по умолчанию key-state включён (флага нет)", not getattr(args, "no_key_state", False))
args = mod.build_parser().parse_args(["--no-key-state"])
check("--no-key-state принимается", args.no_key_state is True)
text = mod.build_parser().format_help() + mod.build_parser().format_usage()
check("--no-key-state есть в справке --help", "--no-key-state" in text, text[:200])

# -- живой пульт ------------------------------------------------------------- #
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK + "/home")
os.makedirs(WORK + "/programs")

env = dict(os.environ)
env["TERM"] = "xterm-256color"
env["HOME"] = WORK + "/home"
master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--no-tui", "--no-key-state",
     "--key-state-device", WORK + "/nope",  # даже такой путь не должен пугать
     "--program-dir", WORK + "/programs"],
    stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
)
os.close(slave)
buf = b""


def read(seconds):
    global buf
    end = time.time() + seconds
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


def key(text, wait=0.7):
    raw = {"enter": b"\r", "esc": b"\x1b"}.get(text)
    os.write(master, raw if raw is not None else text.encode())
    read(wait)
    return take()


read(1.5)
out = take()
check("--no-key-state сообщает о себе", "[info] key-state выключен (--no-key-state)" in out, out)
check("--no-key-state: без предупреждений про key-state", "[warn] key-state" not in out, out)

key("q")
out = key("6", 0.5)
check("подключение и цвет работают", "подсветка: синий" in out, out)

out = key("p")
check("режим программы по-прежнему работает", "[prog]" in out, out)
out = key("w")
check("шаги набираются", "↑" in out, out)
key("esc")

out = key("m")
check("запись макроса по-прежнему работает", "запись макроса" in out, out)
out = key("esc", 0.8)
check("Esc останавливает запись", "ничего не записалось" in out or "макрос записан" in out, out)

os.write(master, b"\x03")
read(1.2)
proc.wait(timeout=5)
check("выход по Ctrl+C", proc.returncode == 0, proc.returncode)

print()
print("ОШИБОК:", failures)
sys.exit(1 if failures else 0)
