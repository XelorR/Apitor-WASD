#!/usr/bin/env python3
"""e/E — редактор в любом режиме, мотор 3 на v/V, Shift+Enter без key-state.

Shift+Enter приходит как CSI-u (kitty-протокол) или 27;2;13~ (xterm
modifyOtherKeys) — так его видит пульт в терминалах, которые умеют
расширенные клавиши, даже когда key-state выключен.
"""
import fcntl
import importlib.util
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
WORK = fresh_work("test20")

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK + "/programs")
os.makedirs(WORK + "/home")

spec = importlib.util.spec_from_file_location("apitor_remote", APP)
mod = importlib.util.module_from_spec(spec)
sys.modules["apitor_remote"] = mod
spec.loader.exec_module(mod)

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


# --------------------------------------------------------------------------- #
# Часть A: юниты — карта клавиш и разбор CSI-u
# --------------------------------------------------------------------------- #
check("e/E — внешний редактор", (mod.KEYMAP["e"], mod.KEYMAP["E"]) == ("edit_external", "edit_external"),
      (mod.KEYMAP["e"], mod.KEYMAP["E"]))
check("v/V — мотор 3", (mod.KEYMAP["v"], mod.KEYMAP["V"]) == ("m3_fwd", "m3_rev"),
      (mod.KEYMAP["v"], mod.KEYMAP["V"]))
check("e больше не мотор 3", mod.KEYMAP["e"] != "m3_fwd", mod.KEYMAP["e"])

CSI_CASES = [
    (b"13;2u", "s-enter"),        # kitty: Shift+Enter
    (b"13u", "enter"),            # kitty: обычный Enter
    (b"13;2:3u", None),           # kitty: отпускание Shift+Enter
    (b"27;2;13~", "s-enter"),     # xterm modifyOtherKeys: Shift+Enter
    (b"27;1;13~", "enter"),
    (b"27;5;99~", "\x03"),        # xterm: Ctrl+C
    (b"99;5u", "\x03"),           # kitty: Ctrl+C
    (b"114;2u", "R"),             # kitty: Shift+r (обратный проезд)
    (b"61;2u", "+"),              # kitty: Shift+= (скорость)
    (b"45;2u", "_"),
    (b"27;2u", "esc"),            # Shift+Esc остаётся Esc
    (b"27;1;127~", "backspace"),  # Ctrl+Backspace — как Backspace
    (b"Z", None),                 # просто backtab — не наша клавиша
    (b"?1u", None),               # ответ терминала на запрос
    (b"1;5C", None),              # стрелка с модификатором (её ловит стрелочный разбор)
]
for seq, want in CSI_CASES:
    got = mod._decode_csi(seq)
    check(f"CSI {seq.decode()!r} → {want!r}", got == want, repr(got))

# --------------------------------------------------------------------------- #
# Часть B: живой пульт
# --------------------------------------------------------------------------- #
KBD = WORK + "/kbd"
os.mkfifo(KBD)
EVENT = mod._EVENT
KEY_W = 17

env = dict(os.environ)
env["TERM"] = "xterm-256color"
env["HOME"] = WORK + "/home"
env["EDITOR"] = "true"       # «редактор», который сразу закрывается
master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--key-state-device", KBD, "--program-dir", WORK + "/programs"],
    stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
)
os.close(slave)
kbd = os.open(KBD, os.O_WRONLY)

buf = b""
everything = b""


def read(seconds):
    global buf, everything
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
            everything += data


def take():
    global buf
    out = buf.decode("utf-8", "replace")
    buf = b""
    return out


def key(text, wait=0.7):
    raw = {"enter": b"\r", "esc": b"\x1b", "backspace": b"\x7f"}.get(text)
    os.write(master, raw if raw is not None else text.encode())
    read(wait)
    return take()


def raw(seq, wait=0.5):
    os.write(master, seq)
    read(wait)
    return take()


def wait(seconds):
    read(seconds)
    return take()


read(2.0)
take()

# программа: вперёд 4 и пауза 1 (без key-state — Shift придёт от терминала)
key("q")
editor_out = key("p")
for _ in range(4):
    editor_out += key("w")
editor_out += key(" ")
editor_out += key("esc")
check("программа с паузой набрана", "↑4 · ‖" in editor_out, editor_out)

# Shift+Enter из терминала (kitty): прогон без пауз
out = raw(b"\x1b[13;2u", 0.2) + wait(3.5)
check("Shift+Enter (kitty CSI-u) в пульте: прогон без пауз",
      "без пауз" in out and "старт: 1 шаг" in out and "▶ ‖" not in out, out)
check("Shift+Enter: пауза выброшена, шаг проехал",
      "готово: 1 шаг" in out, out)

# Shift+Enter из терминала (xterm modifyOtherKeys)
out = raw(b"\x1b[27;2;13~", 0.2) + wait(3.5)
check("Shift+Enter (xterm 27;2;13~): тоже без пауз",
      "без пауз" in out and "старт: 1 шаг" in out, out)

# обычный Enter — по-прежнему с паузами
out = key("enter", 0.2) + wait(4.0)
check("Enter без Shift: прогон с паузами",
      "старт: 2 шага" in out and "▶ ‖" in out, out)

# мотор 3 — на v/V
out = key("v")
check("v — мотор 3 вперёд", "мотор 3: вперёд" in out, out)
out = key("V")
check("V — мотор 3 назад", "мотор 3: назад" in out, out)
out = key("e", 0.3)
check("e больше не мотор 3", "мотор 3" not in out, out)

# e в пульте открывает редактор и возвращает программу
out = key("e", 1.5)
check("e в пульте открывает внешний редактор", "открываю редактор" in out, out)
check("после редактора программа перечитана",
      "обновлено из редактора" in out and "2 шага" in out, out)
out = key("enter", 0.2) + wait(4.0)
check("после e пульт остаётся пультом (Enter сразу проезжает программу)",
      "старт: 2 шага" in out, out)

# e в режиме программы — как и раньше
out = key("p")
check("подсказка программы: повтор на «*»", "* — повтор" in out, out)
check("подсказка программы: r/R/t/T — обратно", "r/R/t/T — обратно" in out, out)
out = key("e", 1.5)
check("e в режиме программы тоже открывает редактор", "открываю редактор" in out, out)
key("esc")

# в режиме программы повтор программы — на «*», а r/R/t/T везут обратно
out = key("p") + key("x") + key("w") + key("w") + key(" ")
check("программа для реверса набрана", "↑2 · ‖" in out and "2 шага" in out, out)
out = key("*")
check("*- в режиме программы повтор +1", "повтор 2" in out, out)
out = key("*") + key("3")
check("*3 — ровно 3 повтора", "повтор 3" in out, out)
out = key("*") + key("1")
last = [l for l in out.splitlines() if l.strip()][-1]
check("*1 возвращает один повтор", "повтор" not in last, last)

out = key("r", 0.2) + wait(4.5)
check("r в режиме программы: реверс задним ходом",
      "старт: 2 шага · скор. 6 · реверс задним ходом" in out, out)
check("r: пауза на месте", "▶ ‖1с" in out, out)
out = key("p") + key("R", 0.2) + wait(3.0)
check("R в режиме программы: без пауз",
      "реверс задним ходом · без пауз" in out and "▶ ‖" not in out, out)
out = key("p") + key("t", 0.2) + wait(4.5)
check("t в режиме программы: реверс передом",
      "старт: 2 шага · скор. 6 · реверс передом (робот развёрнут)" in out, out)
out = key("p") + key("T", 0.2) + wait(3.0)
check("T в режиме программы: передом без пауз",
      "реверс передом (робот развёрнут) · без пауз" in out, out)
out = key("esc") + key("p")
check("после реверсов программа не изменилась", "↑2 · ‖" in out and "2 шага" in out, out)
out = key("h", 0.5)
check("справка программы: повтор на «*»", "*5 — ровно 5 раз" in out, out)
check("справка программы: r / R / t / T",
      "r / R / t / T" in out and "маршрут обратно" in out, out)
key("esc")

# во время записи макроса редактор не открывается
out = key("m")
check("m начинает запись", "запись макроса" in out, out)
out = key("e", 0.5)
check("e во время записи — «идёт запись макроса»",
      "идёт запись макроса" in out and "редактор" not in out.lower(), out)
out = key("esc", 0.8)
check("Esc останавливает запись", "запись остановлена" in out or "макрос записан" in out, out)

# справка: новые и старые клавиши
out = key("h", 0.5)
check("справка: v / V — мотор 3", "v / V" in out and "мотор 3" in out, out)
check("справка: e / E — редактор", "e / E" in out and "EDITOR" in out, out)
check("справка: Shift+Enter про терминал", "Shift+Enter" in out and "kitty" in out, out)

# без ответа терминала расширенный режим не включался
check("терминал промолчал — CSI-u не включали",
      b"\x1b[>1u" not in everything and b"\x1b[?u" in everything, everything[-200:])

os.write(master, b"\x03")
read(1.5)
proc.wait(timeout=5)
check("выход по Ctrl+C", proc.returncode == 0, proc.returncode)

# --------------------------------------------------------------------------- #
# Часть C: терминал, который умеет расширенные клавиши
# --------------------------------------------------------------------------- #
master2, slave2 = pty.openpty()
fcntl.ioctl(slave2, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
proc2 = subprocess.Popen(
    [PY, APP, "--simulate", "--key-state-device", KBD + "2", "--program-dir", WORK + "/programs"],
    stdin=slave2, stdout=slave2, stderr=slave2, cwd=ROOT, env=env, close_fds=True,
)
os.close(slave2)
out2 = b""
deadline = time.time() + 3.0
replied = False
while time.time() < deadline:
    ready, _, _ = select.select([master2], [], [], 0.02)
    if not ready:
        continue
    try:
        data = os.read(master2, 65536)
    except OSError:
        break
    if not data:
        break
    out2 += data
    if not replied and b"\x1b[?u" in out2:
        os.write(master2, b"\x1b[?0u")   # «умею расширенные клавиши»
        replied = True
    if replied and b"\x1b[>1u" in out2:
        break
check("запрос терминалу отправлен", b"\x1b[?u" in out2, out2[:200])
check("ответ терминала получен в срок", replied, out2[:200])
check("терминал умеет — расширенный режим включён", b"\x1b[>1u" in out2, out2[:300])

os.write(master2, b"\x03")
end = time.time() + 2
while time.time() < end:
    ready, _, _ = select.select([master2], [], [], 0.05)
    if not ready:
        continue
    try:
        data = os.read(master2, 65536)
    except OSError:
        break
    if not data:
        break
    out2 += data
proc2.wait(timeout=5)
check("при выходе расширенный режим выключен", b"\x1b[<u" in out2, out2[-200:])
check("выход по Ctrl+C (расширенный режим)", proc2.returncode == 0, proc2.returncode)

print()
print("ОШИБОК:", failures)
sys.exit(1 if failures else 0)
