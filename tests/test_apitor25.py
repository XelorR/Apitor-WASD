#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Разовая программа (o): как p, но не сохраняется и исчезает после прогона."""
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
WORK = fresh_work("test25")
PROGDIR = os.path.join(WORK, "programs")
FAKEHOME = os.path.join(WORK, "home")
DRAFT = os.path.join(PROGDIR, "_draft.txt")
JOURNAL = os.path.join(FAKEHOME, ".config", "apitor-control", "runs.log")

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(PROGDIR)
os.makedirs(FAKEHOME)
# файл для загрузки в разовую программу (g в режиме o)
with open(os.path.join(PROGDIR, "разово.txt"), "w", encoding="utf-8") as fh:
    fh.write("вперёд 2с\n")

env = dict(os.environ)
env["TERM"] = "xterm-256color"
env["HOME"] = FAKEHOME


class Term:
    """Пульт в --simulate: клавиши в PTY, вывод копим и разбираем."""

    def __init__(self, extra=()):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
        self.proc = subprocess.Popen(
            [PY, APP, "--simulate", "--no-tui", "--no-key-state", "--log",
             "--program-dir", PROGDIR, *extra],
            stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
        )
        os.close(slave)
        self.buf = b""
        self.read(1.6)
        self.take()
        self.key("q", 0.8)      # подключиться (симулятор)
        self.take()

    def read(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([self.master], [], [], 0.05)
            if ready:
                try:
                    data = os.read(self.master, 65536)
                except OSError:
                    return
                if not data:
                    return
                self.buf += data

    def take(self):
        out = self.buf.decode("utf-8", "replace")
        self.buf = b""
        return out

    def key(self, text, wait=0.35):
        raw = {"enter": b"\r", "esc": b"\x1b", "backspace": b"\x7f"}.get(text)
        os.write(self.master, raw if raw is not None else text.encode())
        self.read(wait)
        return self.take()

    def raw(self, data, wait=0.5):
        os.write(self.master, data)
        self.read(wait)
        return self.take()

    def wait(self, seconds):
        self.read(seconds)
        return self.take()

    def stop(self, ctrl_c=True):
        if ctrl_c and self.proc.poll() is None:
            os.write(self.master, b"\x03")
            self.read(1.2)
        self.proc.terminate()
        try:
            self.proc.wait(3)
        except Exception:  # noqa: BLE001 — тест не должен зависать
            self.proc.kill()


def run_starts(text):
    return [line for line in text.splitlines() if "[run] старт:" in line]


# --------------------------------------------------------------------------- #
# Сценарий 1: p → ↑2, o → →1; Enter проезжает разовую, потом снова p
# --------------------------------------------------------------------------- #
t = Term()
try:
    out = t.key("p", 0.3)
    out += t.key("w", 0.2) + t.key("w", 0.3)
    check("p: обычная программа набрана", "↑2 (1 шаг" in out, out)
    out = t.key("esc", 0.3)
    check("Esc из p — в пульт", "пульт" in out, out)

    out = t.key("o", 0.3)
    check("o: открылась разовая программа", "разовая программа" in out, out)
    check("o: пустая разовая программа показывает скорость",
          "(пусто)" in out and "скор. 6" in out, out)
    out = t.key("d", 0.3)
    check("o: шаг попал в разовую программу", "→" in out and "1 шаг" in out, out)
    out = t.key("p", 0.3)
    check("p из разовой: обычная программа не изменилась",
          "↑2" in out and "1 шаг" in out, out)
    t.key("esc", 0.3)

    out = t.key("o", 0.3)
    check("o снова: разовая программа помнит →1", "→" in out, out)
    out = t.key("enter", 0.2) + t.wait(2.6)
    starts = run_starts(out)
    check("Enter в o: прогон разовой программы",
          any("разово" in line and "1 шаг" in line for line in starts), out)
    check("Enter в o: едет →, а не ↑2", "▶ →" in out and "▶ ↑2" not in out, out)
    check("Enter в o: прогон дошёл до конца", "готово: 1 шаг" in out, out)
    check("после прогона — снова пульт",
          "разовая программа больше не в памяти" in out, out)

    out = t.key("o", 0.3)
    check("после прогона разовая программа исчезла",
          "(пусто)" in out, out)
    t.key("esc", 0.3)

    out = t.key("enter", 0.2) + t.wait(2.6)
    starts = run_starts(out)
    check("Enter после o: снова программа из p",
          any("1 шаг" in line and "разово" not in line for line in starts), out)
    check("Enter после o: едет ↑2 из p", "▶ ↑2" in out and "▶ →" not in out, out)
    check("Enter после o: прогон завершён", "готово: 1 шаг" in out, out)

    out = t.key("r", 0.2) + t.wait(3.2)
    check("r после o: обратный проезд программы из p",
          "реверс задним ходом" in out and "разово" not in "".join(run_starts(out)), out)
    check("r после o: назад едет ↑2 из p", "▶ ↓1.2с" in out, out)
finally:
    t.stop(ctrl_c=False)

# автозапись должна содержать программу из p, а не разовую
t = Term()
try:
    t.key("p", 0.3)
    t.key("w", 0.2) + t.key("w", 0.3)
    t.key("esc", 0.3)
    t.key("o", 0.3)
    t.key("a", 0.2) + t.key("a", 0.3)   # разовая ←2 — сохраняться не должна
    t.key("esc", 0.3)
    t.stop()                            # Ctrl+C — выход, автозапись
finally:
    pass
draft = open(DRAFT, encoding="utf-8").read() if os.path.exists(DRAFT) else ""
check("автозапись: в черновике обычная программа",
      "вперёд 2" in draft, draft)
check("автозапись: разовой программы в черновике нет",
      "влево" not in draft, draft)

# --------------------------------------------------------------------------- #
# Сценарий 2: f в o не сохраняет; g загружает в разовую, p не трогает
# --------------------------------------------------------------------------- #
t = Term()
try:
    t.key("p", 0.3) + t.key("w", 0.2)
    t.key("esc", 0.3)
    out = t.key("o", 0.3)
    out = t.key("f", 0.4)
    check("f в o: разовая программа не сохраняется",
          "не сохраняется" in out and "[save]" not in out, out)
    out = t.key("g", 0.7)
    check("g в o: список файлов показан", "разово.txt" in out, out)
    out = t.key("1", 0.2) + t.key("enter", 0.5)
    check("g в o: файл загружен разово", "загружено разово" in out, out)
    check("g в o: в разовой программе ↑2с", "↑2с" in out, out)
    out = t.key("p", 0.4)
    check("p после g: обычная программа по-прежнему ↑1", "↑" in out and "↑2с" not in out, out)
    t.key("esc", 0.3)
    out = t.key("o", 0.3)
    check("o: загруженная разовая программа на месте", "↑2с" in out, out)
    out = t.key("x", 0.3)
    check("x в o: разовая очищена", "(пусто)" in out and "очищена" in out, out)
    t.key("esc", 0.3)
    out = t.key("p", 0.4)
    check("x в o: обычная программа не тронута", "↑" in out, out)
finally:
    t.stop(ctrl_c=False)

# --------------------------------------------------------------------------- #
# Сценарий 3: Shift+Enter в o — разово и без пауз; после — снова p
# --------------------------------------------------------------------------- #
t = Term()
try:
    t.key("p", 0.3) + t.key("w", 0.2)
    t.key("esc", 0.3)
    t.key("o", 0.3)
    t.key("w", 0.2) + t.key(" ", 0.2) + t.key("d", 0.3)
    out = t.raw(b"\x1b[13;2u", 0.2) + t.wait(2.8)
    starts = run_starts(out)
    check("Shift+Enter в o: разовая программа без пауз",
          any("разово" in line and "без пауз" in line and "2 шага" in line
              for line in starts), out)
    check("Shift+Enter в o: пауза выброшена", "▶ ‖" not in out, out)
    check("Shift+Enter в o: прогон завершён", "готово: 2 шага" in out, out)
    out = t.key("o", 0.3)
    check("после Shift+Enter разовая исчезла", "(пусто)" in out, out)
    t.key("esc", 0.3)
    out = t.key("enter", 0.2) + t.wait(2.0)
    check("Enter после Shift+Enter: программа из p",
          "разово" not in "".join(run_starts(out)) and "▶ ↑" in out, out)
finally:
    t.stop(ctrl_c=False)

# --------------------------------------------------------------------------- #
# Сценарий 4: пауза на разовом прогоне → r; после возврата — снова p
# --------------------------------------------------------------------------- #
t = Term()
try:
    t.key("p", 0.3) + t.key("w", 0.2)
    t.key("esc", 0.3)
    t.key("o", 0.3)
    t.key("g", 0.7)
    out = t.key("1", 0.2) + t.key("enter", 0.5)
    check("g в o для реверса: маршрут загружен", "↑2с" in out, out)
    t.key("enter", 0.2)                    # пуск разовой
    t.wait(0.9)
    out = t.key(" ", 0.3)
    check("пауза на разовом прогоне", "r/t — обратно по проеханному" in out, out)
    out = t.key("r", 3.6)
    starts = run_starts(out)
    check("r на паузе разового: реверс проеханной части",
          any("реверс проеханной части" in line and "разово" in line
              for line in starts), out)
    check("r на паузе разового: назад отрезком",
          re.search(r"▶ ↓\d+(?:\.\d+)?с", out) is not None, out)
    check("r на паузе разового: возврат завершён", "готово: 1 шаг" in out, out)
    out = t.key("o", 0.3)
    check("после разового реверса разовая исчезла", "(пусто)" in out, out)
    t.key("esc", 0.3)
    out = t.key("enter", 0.2) + t.wait(2.0)
    check("Enter после разового реверса: снова p",
          "разово" not in "".join(run_starts(out)) and "▶ ↑" in out, out)
finally:
    t.stop(ctrl_c=False)

# --------------------------------------------------------------------------- #
# Сценарий 4b: r прямо из режима o — разовый реверс и исчезновение
# --------------------------------------------------------------------------- #
t = Term()
try:
    t.key("p", 0.3) + t.key("w", 0.2)
    t.key("esc", 0.3)
    t.key("o", 0.3) + t.key("d", 0.3)
    out = t.key("r", 0.2) + t.wait(2.6)
    starts = run_starts(out)
    check("r в o: разовый реверс задним ходом",
          any("реверс задним ходом" in line and "разово" in line
              for line in starts), out)
    check("r в o: едет ←, а не →", "▶ ←" in out, out)
    check("r в o: реверс завершён", "готово: 1 шаг" in out, out)
    out = t.key("o", 0.3)
    check("после r в o разовая исчезла", "(пусто)" in out, out)
    t.key("esc", 0.3)
    out = t.key("enter", 0.2) + t.wait(2.0)
    check("Enter после r в o: снова программа из p",
          "разово" not in "".join(run_starts(out)) and "▶ ↑" in out, out)
finally:
    t.stop(ctrl_c=False)

journal = open(JOURNAL, encoding="utf-8").read() if os.path.exists(JOURNAL) else ""
check("журнал: разовый прогон помечен «(разово)»", "(разово)" in journal, journal)
check("журнал: разовый реверс записан",
      "пауза на шаге 1/1" in journal, journal)

# --------------------------------------------------------------------------- #
# Сценарий 5: TUI — рамка показывает именно разовую программу
# --------------------------------------------------------------------------- #
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
ROW = re.compile(r"\x1b\[(\d+);1H\x1b\[2K(.*?)(?=\x1b\[[0-9]+;1H|\x1b\[\?25l|\Z)", re.S)


def frames(out):
    result = []
    for segment in out.split("\x1b[1;1H")[1:]:
        rows = {int(n): ANSI.sub("", t) for n, t in ROW.findall("\x1b[1;1H" + segment)}
        if rows:
            result.append(rows)
    return result


def last(out):
    all_frames = frames(out)
    return all_frames[-1] if all_frames else {}


def frame_title(frame):
    for row in frame.values():
        if row.startswith("┌─") and "программа ·" in row:
            return row
    return ""


def frame_body(frame):
    for row in frame.values():
        if row.startswith("│"):
            row = row[1:]
            if row.endswith("│"):
                row = row[:-1]
            return row
    return ""


master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 76, 0, 0))
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--tui", "--key-state-device", os.path.join(WORK, "nope"),
     "--program-dir", PROGDIR],
    stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
)
os.close(slave)
buf = b""


def tui_read(seconds):
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


def tui_take():
    global buf
    out = buf.decode("utf-8", "replace")
    buf = b""
    return out


def tui_key(text, wait=0.4):
    raw = {"enter": b"\r", "esc": b"\x1b"}.get(text)
    os.write(master, raw if raw is not None else text.encode())
    tui_read(wait)
    return tui_take()


try:
    tui_read(1.6)
    tui_take()
    tui_key("q", 0.8)
    tui_take()
    tui_key("p", 0.4)
    state = last(tui_key("w", 0.3))
    check("TUI: рамка обычной программы", "программа · 1 шаг" in frame_title(state),
          frame_title(state))
    check("TUI: в рамке ↑", "↑" in frame_body(state), frame_body(state))

    state = last(tui_key("o", 0.4))
    check("TUI: рамка разовой программы", "разовая программа · 0 шагов" in frame_title(state),
          frame_title(state))
    check("TUI: разовая пустая", "(пусто)" in frame_body(state), frame_body(state))
    state = last(tui_key("d", 0.3))
    check("TUI: разовая показывает →",
          "разовая программа · 1 шаг" in frame_title(state) and "→" in frame_body(state),
          (frame_title(state), frame_body(state)))
    state = last(tui_key("p", 0.4))
    check("TUI: p показывает обычную ↑, а не разовую",
          "программа · 1 шаг" in frame_title(state)
          and "↑" in frame_body(state) and "→" not in frame_body(state),
          (frame_title(state), frame_body(state)))

    state = last(tui_key("o", 0.4))
    check("TUI: o снова показывает разовую →", "→" in frame_body(state),
          frame_body(state))
    out = tui_key("enter", 0.3)
    tui_read(2.4)
    out += tui_take()
    state = last(out)
    check("TUI: после разового прогона — пульт",
          any(row.startswith("пульт:") for row in state.values()), state)
    check("TUI: в пульте видна программа из p",
          "↑3" in frame_body(state)
          and any("последняя программа" in row for row in state.values()), state)
    state = last(tui_key("o", 0.4))
    check("TUI: разовая исчезла", "(пусто)" in frame_body(state), frame_body(state))
    tui_key("esc", 0.3)
    os.write(master, b"\x03")
    tui_read(1.5)
    tui_take()
finally:
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    os.close(master)

print(f"failures: {failures}")
sys.exit(1 if failures else 0)
