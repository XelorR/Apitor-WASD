#!/usr/bin/env python3
"""Обратный проезд (r/R/t/T), Enter — пуск, Esc — стоп записи, e — редактор, y — тест."""
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
WORK = fresh_work("test17")

spec = importlib.util.spec_from_file_location("apitor_remote", APP)
mod = importlib.util.module_from_spec(spec)
sys.modules["apitor_remote"] = mod
spec.loader.exec_module(mod)

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


def show(steps):
    return " · ".join(mod.step_text(s) for s in steps)


def steps_of(text):
    steps, _, _, err = mod.parse_program(text)
    assert not err, err
    return steps


def reverse(text, mode, **kw):
    steps = steps_of(text)
    editor = mod.ProgramEditor()
    editor.set_program(steps, 1, None)
    return show(mod.reversed_steps(editor, mode, **kw))


# --------------------------------------------------------------------------- #
# Часть A: юниты
# --------------------------------------------------------------------------- #
check("ключи: Enter — пуск", mod.KEYMAP["enter"] == "run", mod.KEYMAP["enter"])
check("ключи: r/R — обратно задним ходом",
      (mod.KEYMAP["r"], mod.KEYMAP["R"]) == ("rev_back", "rev_back_np"), mod.KEYMAP["r"])
check("ключи: t/T — обратно, развернув робота",
      (mod.KEYMAP["t"], mod.KEYMAP["T"]) == ("rev_front", "rev_front_np"), mod.KEYMAP["t"])
check("ключи: тест-поездка переехала на y", mod.KEYMAP["y"] == "test", mod.KEYMAP["y"])
check("раскладка: к→r, К→R, е→t, Е→T, н→y, Н→Y, т→n, Т→N",
      [mod._to_latin_layout(ch) for ch in "кКеЕнНтТ"]
      == ["r", "R", "t", "T", "y", "Y", "n", "N"],
      [mod._to_latin_layout(ch) for ch in "кКеЕнНтТ"])

# обратный проезд: порядок, длительности, свет и скорость
prog = "цвет 1\nвперёд 2\nцвет 3\nвправо 1\nвперёд 1.5с\nцвет 5\nпауза 2\nвперёд 1с\n"
got = reverse(prog, "back")
check("реверс задним ходом: маршрут в обратном порядке, свет перед участками",
      got == "●5 · ↓1с · ‖2с · ●3 · ↓1.5с · ←0.6с · ●1 · ↓1.2с", got)
got = reverse(prog, "front")
check("реверс передом: вперёд/назад не реверсится, только влево/вправо",
      got == "●5 · ↑1с · ‖2с · ●3 · ↑1.5с · ←0.6с · ●1 · ↑1.2с", got)
got = reverse(prog, "back", drop_pauses=True)
check("реверс с Shift: паузы выброшены", got == "●5 · ↓1с · ●3 · ↓1.5с · ←0.6с · ●1 · ↓1.2с", got)
check("реверс: длительности шагов сохранены (вперёд 2 → ↓1.2с)",
      "↓1.2с" in got and "←0.6с" in got, got)

got = reverse("скорость 6\nвперёд 1с\nскорость 12\nвперёд 2с\nназад 1с\n", "back")
check("реверс: скорость ставится перед участком, который так ехали",
      got == "»12 · ↑1с · ↓2с · »6 · ↓1с", got)
got = reverse("скорость 8\nвперёд 1с\nпауза 0.5с\nвлево 0.7с\n", "front", drop_pauses=True)
check("реверс: шапка скорости без изменений — » не появляется", got == "→0.7с · ↑1с", got)
got = reverse("цвет 4\nвперёд 1с\nмигнуть 2\nпауза 1с\n", "back")
check("реверс: мигание остаётся миганием", got == "●4 · ‖1с · ✦2 · ↓1с", got)
check("реверс программы без цвета: цвет не трогаем",
      reverse("вперёд 1с\nназад 2с\n", "back") == "↑2с · ↓1с",
      reverse("вперёд 1с\nназад 2с\n", "back"))
steps = steps_of("пауза 3\n")
editor = mod.ProgramEditor()
editor.set_program(steps, 1, None)
check("реверс одних пауз без пауз — пусто",
      mod.reversed_steps(editor, "back", drop_pauses=True) == [])

# --------------------------------------------------------------------------- #
# Часть B: живой пульт (PTY + key-state через FIFO)
# --------------------------------------------------------------------------- #
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK + "/home")
os.makedirs(WORK + "/programs")
KBD = WORK + "/kbd"
os.mkfifo(KBD)
EVENT = mod._EVENT
KEY_W, KEY_A, KEY_D = 17, 30, 32
LSHIFT, RSHIFT = 42, 54

env = dict(os.environ)
env["TERM"] = "xterm-256color"
env["HOME"] = WORK + "/home"
env["EDITOR"] = "true"       # «редактор», который сразу закрывается
master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--no-tui", "--key-state-device", KBD, "--program-dir", WORK + "/programs"],
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
    raw = {"enter": b"\r", "esc": b"\x1b", "backspace": b"\x7f", "shift": b"\x1b[Z"}.get(text)
    os.write(master, raw if raw is not None else text.encode())
    read(wait)
    return take()


def wait(seconds):
    read(seconds)
    return take()


def event(code, value):
    os.write(kbd, EVENT.pack(0, 0, 1, code, value))


kbd = os.open(KBD, os.O_WRONLY)
read(2.0)
take()
key("q")

# программа из двух шагов: вперёд 4 и пауза
key("p")
for _ in range(4):
    key("w")           # подряд = «вперёд 4»
key(" ")               # пауза
key("esc")
wait(0.3)

# Enter в пульте — пуск последней программы
out = key("enter", 0.1) + wait(4.0)
check("Enter в пульте запускает программу", "старт: 2 шага" in out, out)
check("Enter: прогон завершён", "готово: 2 шага" in out, out)
check("подсказка после прогона: Enter — ещё раз, r/t — обратно",
      "Enter — ещё раз · r — назад · t — развернув робота" in out, out)

# r — обратный проезд задним ходом
out = key("r", 0.1) + wait(4.0)
check("r: реверс задним ходом",
      "старт: 2 шага · скор. 6 · реверс задним ходом" in out, out)
check("r: шаги идут в обратном порядке и реверсом",
      "▶ ↓2.4с" in out and "▶ ‖1с" in out and "▶ ↓" in out, out)
check("r: прогон завершён", "готово: 2 шага" in out, out)

# t — робота развернули рукой: вперёд/назад не реверсится
out = key("t", 0.1) + wait(4.0)
check("t: реверс передом", "реверс передом (робот развёрнут)" in out, out)
check("t: вперёд остаётся вперёд", "▶ ↑2.4с" in out, out)

# Shift+r (Shift зажат физически) — без пауз
event(LSHIFT, 1)
out = key("R", 0.1) + wait(3.0)
check("R (с Shift): реверс без пауз", "реверс задним ходом · без пауз" in out, out)
check("R: паузы выброшены", "▶ ‖" not in out, out)
event(LSHIFT, 0)
wait(0.4)

# Shift+Enter — обычный прогон без пауз
event(LSHIFT, 1)
wait(0.4)  # дать key-state прочитать событие
out = key("enter", 0.1) + wait(3.0)
check("Shift+Enter: обычный прогон без пауз (шаг остался один — пауза ушла)",
      "старт: 1 шаг" in out and "без пауз" in out and "▶ ‖" not in out, out)
event(LSHIFT, 0)
wait(0.4)

# программа после реверса не изменилась
out = key("p")
check("после реверса программа та же", "↑4 · ‖" in out and "2 шага" in out, out)
out = key("esc")

# пустая программа: Enter подсказывает
key("x")
out = key("enter", 0.5)
check("Enter без программы — подсказка", "программы нет" in out, out)
out = key("r", 0.5)
check("r без программы — подсказка", "обратный проезд нечего выполнять" in out, out)

# e в режиме программы открывает редактор
key("p")
key("w")
out = key("e", 1.5)
check("e в режиме программы открывает редактор", "редактор" in out.lower(), out)
out = key("esc")
check("после редактора — снова пульт", "пульт" in out, out)

# запись макроса: Esc останавливает, Enter во время записи молчит
out = key("m")
check("m начинает запись", "запись макроса" in out, out)
out = key("enter", 0.6)
check("Enter во время записи — «сначала Esc или n (стоп)»",
      "сначала Esc или n (стоп)" in out, out)
out = key("m", 0.5)
check("m во время записи не останавливает, а объясняет состояние",
      "запись уже идёт" in out and "Esc или n" in out, out)
out = wait(0.3)
os.write(kbd, EVENT.pack(0, 0, 1, KEY_W, 1))
time.sleep(0.4)
os.write(kbd, EVENT.pack(0, 0, 1, KEY_W, 0))
out += wait(0.5)
out += key("n", 0.8)
check("n останавливает запись и макрос готов", "макрос записан" in out, out)
check("макрос: подсказка про Enter и r/t", "Enter — проехать, r/t — обратно" in out, out)
out = key("m", 0.4)
out += key("esc", 0.8)
check("Esc тоже останавливает запись", "запись остановлена" in out, out)

out = key("enter", 0.1) + wait(1.5)
check("Enter после записи проезжает макрос", "старт: 1 шаг · скор. 6 · макрос" in out, out)
out = key("r", 0.1) + wait(1.5)
check("r проезжает макрос обратно",
      "реверс задним ходом" in out and "▶ ↓0.4" in out, out)

# r проезжает макрос обратно
# тест-поездка теперь на y (она идёт ~7 с — ждём, иначе помешает дальше)
out = key("y", 0.6) + wait(7.0)
check("y — тест-поездка", "тест-поездка" in out and "готово. Если направления неверные" in out, out)
out = key("t", 0.1) + wait(2.0)
check("t больше не тест-поездка",
      "тест-поездка" not in out and "реверс передом" in out, out)

os.write(master, b"\x03")
read(1.5)
proc.wait(timeout=5)
check("выход по Ctrl+C", proc.returncode == 0, proc.returncode)

print()
print("ОШИБОК:", failures)
sys.exit(1 if failures else 0)
