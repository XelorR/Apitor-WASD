#!/usr/bin/env python3
"""TUI + макрос: индикатор записи в шапке, живая строка записи, [rec] в логе."""
import fcntl
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import sys
import termios
import time

from harness import ROOT, PY, APP, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test16")

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK + "/home")
os.makedirs(WORK + "/programs")
KBD = WORK + "/kbd"
os.mkfifo(KBD)

spec = None
import importlib.util
spec = importlib.util.spec_from_file_location("apitor_remote", APP)
mod = importlib.util.module_from_spec(spec)
sys.modules["apitor_remote"] = mod
spec.loader.exec_module(mod)
EVENT = mod._EVENT
KEY_W, KEY_A = 17, 30

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
ROW = re.compile(r"\x1b\[(\d+);1H\x1b\[2K(.*?)(?=\x1b\[[0-9]+;1H|\Z)", re.S)


def screens(out):
    result = []
    for segment in out.split("\x1b[1;1H")[1:]:
        rows = {int(n): ANSI.sub("", t) for n, t in ROW.findall("\x1b[1;1H" + segment)}
        if rows:
            result.append(rows)
    return result


def last_screen(out):
    all_screens = screens(out)
    return all_screens[-1] if all_screens else {}


env = dict(os.environ)
env["TERM"] = "xterm-256color"
env["HOME"] = WORK + "/home"
master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--tui", "--key-state-device", KBD,
     "--program-dir", WORK + "/programs"],
    stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
)
os.close(slave)
kbd = os.open(KBD, os.O_WRONLY)
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


def key(text, wait=0.6):
    raw = {"enter": b"\r", "esc": b"\x1b"}.get(text)
    os.write(master, raw if raw is not None else text.encode())
    read(wait)
    return take()


def hold(code, seconds, wait=0.5):
    os.write(kbd, EVENT.pack(0, 0, 1, code, 1))
    time.sleep(seconds)
    os.write(kbd, EVENT.pack(0, 0, 1, code, 0))
    read(wait)
    return take()


read(1.5)
take()
key("q")
key("m")
out = key("m")  # m во время записи только напоминает про стоп
rows = last_screen(out)
check("TUI: пустая запись даёт строку-подсказку",
      any("[rec]" in row for row in rows.values()), rows)

key("m")
out = hold(KEY_W, 0.5)
rows = last_screen(out)
status = rows.get(1, "")
check("TUI: шапка показывает запись со счётчиком", "запись 1" in status, status)
check("TUI: живая строка записи со секундами",
      any("[rec] ↑" in row and "с" in row for row in rows.values()), rows)
check("TUI: [rec] в логе", "↑" in out and "[rec]" in out, out)

out = key("esc", 1.0)
rows = last_screen(out)
check("TUI: после Esc шапка без записи", "запись" not in rows.get(1, ""), rows.get(1))
check("TUI: лог говорит «макрос записан»",
      any("[rec] макрос записан" in row for row in rows.values()), rows)
check("TUI: строка программы — макрос со секундами",
      any("[prog]" in row and "↑" in row and "с" in row for row in rows.values()), rows)

# запись на ходу: смена направления и пауза
key("m")
hold(KEY_W, 0.4)
out = hold(KEY_A, 0.4)
rows = last_screen(out)
check("TUI: в строке записи видны оба движения",
      any(row.count("↑") + row.count("←") >= 2 for row in rows.values()), rows)

out = key("m")  # начинаем заново: Esc теперь останавливает запись
hold(KEY_A, 0.4)
out = key("esc", 0.8)
rows = last_screen(out)
check("TUI: Esc останавливает запись", "запись" not in rows.get(1, ""), rows.get(1))
check("TUI: Esc — макрос записан", "макрос записан" in out, out)
out = key("m")
check("TUI: m во время записи не останавливает", "запись уже идёт" in out, out)
out = key("n", 0.8)
check("TUI: n останавливает запись", "ничего не записалось" in out, out)

# баннер: режим и его клавиши видны всегда
out = key("m")
rows = last_screen(out)
check("TUI: баннер во время записи — «запись макроса» и клавиши",
      any("запись макроса:" in row for row in rows.values())
      and any("Esc или n — стоп" in row for row in rows.values()), rows)
key("esc", 0.8)

key("m")
hold(KEY_W, 1.5)
key("esc", 0.6)
out = key("enter", 0.4)
rows = last_screen(out)
check("TUI: баннер во время прогона — «прогон» и его клавиши",
      any("прогон:" in row for row in rows.values())
      and any("пауза/продолжить" in row for row in rows.values()), rows)
read(2.5)
take()

# Ctrl+C: терминал возвращён
os.write(master, b"\x03")
read(1.5)
proc.wait(timeout=5)
check("TUI: выход по Ctrl+C", proc.returncode == 0, proc.returncode)

print()
print("ОШИБОК:", failures)
sys.exit(1 if failures else 0)
