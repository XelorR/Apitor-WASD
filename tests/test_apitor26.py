#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Экран прогона: прогресс-бар с машинкой и прокручиваемая цепочка шагов."""
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
import types

from harness import ROOT, PY, APP, NOKS, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test26")
PROGDIR = os.path.join(WORK, "programs")
FAKEHOME = os.path.join(WORK, "home")

spec = importlib.util.spec_from_file_location("apitor_remote", APP)
mod = importlib.util.module_from_spec(spec)
sys.modules["apitor_remote"] = mod
spec.loader.exec_module(mod)

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


def plain(text):
    return mod._ANSI_RE.sub("", text)


def steps_of(text):
    steps, _, _, err = mod.parse_program(text)
    assert not err, err
    return steps


class RunStub:
    """Мини-пульт в режиме прогона; всё, что читает Tui."""

    def __init__(self, text, *, repeat=1, done=0, progress=0.0, paused=False):
        self.profile = types.SimpleNamespace(name="Robot R")
        self.mode = "run"
        self.recording = False
        self.prompt = None
        self.latched = False
        self.key_state = False
        self.led_color = mod.Color.WHITE
        self._boost_speed = None
        self.editor = mod.ProgramEditor()
        self.editor.set_program(steps_of(text), repeat, 6)
        self.once_editor = mod.ProgramEditor()
        self.speed = 6
        self._run_plan = mod.RunPlan(self.editor.steps, 6, repeat, editor=self.editor)
        self._run_editor = self.editor
        self._run_source = "editor"
        self._run_total = len(self.editor.steps)
        self._run_planned = sum(self.editor._step_seconds(s)
                                for s in self.editor.steps) * repeat
        self._run_planned_steps = self.editor.steps * repeat
        self._run_done = self._run_planned_steps[:done]
        self._run_current = (self._run_planned_steps[done]
                             if done < len(self._run_planned_steps) else None)
        self._run_progress = progress
        self._run_step = done % len(self.editor.steps) + 1
        self._run_rep = done // len(self.editor.steps) + 1
        self._run_paused = paused

    def _is_connected(self):
        return True

    def _keys_hint(self):
        return mod.Remote._keys_hint(self)


# --------------------------------------------------------------------------- #
# Часть A: развёрнутый маршрут и секунды прогресса
# --------------------------------------------------------------------------- #
stub = RunStub("вперёд 1с\nвлево 1с", repeat=3)
chain = mod.Tui(stub)._run_chain_steps()
check("повтор разворачивает маршрут в общую цепочку",
      len(chain) == 6
      and [s.kind for s in chain] == ["fwd", "left", "fwd", "left", "fwd", "left"],
      [s.kind for s in chain])

stub = RunStub("вперёд\nпауза\nмигнуть\nцвет 3\nскорость 8")
captions = [mod.Tui(stub)._run_caption(s) for s in stub.editor.steps]
check("у каждого шага в рамке есть действие и количество",
      captions == ["↑ вперёд · 1", "‖ пауза · 1", "✦ мигнуть · 1",
                   "● цвет · 3", "» скорость · 8"], captions)

stub = RunStub("вперёд 1с\nвлево 1с", repeat=2, done=2, progress=0.4)
tui = mod.Tui(stub)
done, total = tui._run_seconds()
check("прогресс: проеханные шаги плюс текущий отрезок",
      abs(done - 2.4) < 1e-6 and abs(total - 4.0) < 1e-6, (done, total))

stub = RunStub("вперёд 1с\nвлево 1с", progress=99.0)
done, total = mod.Tui(stub)._run_seconds()
check("текущий отрезок не выходит за длину своего шага",
      abs(done - 1.0) < 1e-6 and abs(total - 2.0) < 1e-6, (done, total))

stub = RunStub("вперёд 1с\nвлево 1с", done=2)
done, total = mod.Tui(stub)._run_seconds()
check("на финише прогресс равен всему плану",
      abs(done - total) < 1e-6 and abs(total - 2.0) < 1e-6, (done, total))

stub = RunStub("вперёд 4с", done=0)
tui = mod.Tui(stub)
line = plain(tui._run_progress_line(76))
check("в начале машинка слева и видно секунды",
      "🚗" in line and "0.0 / 4.0 с" in line and line.index("🚗") == 0, line)
stub._run_progress = 2.0
mid = plain(tui._run_progress_line(76))
check("на середине машинка сдвинулась вправо",
      "2.0 / 4.0 с" in mid and mid.index("🚗") > line.index("🚗"), (line, mid))
stub._run_done = [stub.editor.steps[0]]
stub._run_current = None
stub._run_progress = 0.0
end = plain(tui._run_progress_line(76))
check("на финише машинка справа, счётчик полный",
      "4.0 / 4.0 с" in end and end.index("🚗") > mid.index("🚗"), (mid, end))
check("прогресс-бар с машинкой занимает всю ширину",
      mod._display_width(tui._run_progress_line(76)) == 76,
      mod._display_width(tui._run_progress_line(76)))


# --------------------------------------------------------------------------- #
# Часть B: текущий шаг в центре, прошедшие сверху, будущие снизу
# --------------------------------------------------------------------------- #
TEXT8 = "вперёд 1с\nвлево 1с\nпауза 1\nвправо 1с\nназад 1с\nцвет 3\nскорость 8\nмигнуть 1"


def chain_rows(done):
    stub = RunStub(TEXT8, done=done)
    rows = mod.Tui(stub)._run_chain(76, 20, screen_top=4, screen_height=24)
    return stub, [plain(row) for row in rows]


stub, rows = chain_rows(3)
current_top = next(i for i, row in enumerate(rows) if row.strip().startswith("╔"))
check("текущая рамка стоит в центре экрана",
      current_top == 6, current_top)
check("в цепочке ровно 20 строк под шапкой", len(rows) == 20, len(rows))
check("выполненные рамки — выше текущей",
      any("✓" in row for row in rows[:current_top])
      and not any("✓" in row for row in rows[current_top:]),
      (rows[:current_top], rows[current_top:]))
check("будущие рамки — ниже текущей",
      any("│" in row and "▶" not in row and "✓" not in row
          for row in rows[current_top + 3:]), rows[current_top + 3:])
current_text = "".join(rows[current_top:current_top + 3])
check("в текущей рамке действие и количество",
      "▶" in current_text and "вправо" in current_text and "1 с" in current_text,
      current_text)

stub0, rows0 = chain_rows(0)
top0 = next(i for i, row in enumerate(rows0) if row.strip().startswith("╔"))
check("первый шаг тоже центрируется, выше него пусто",
      top0 == 6 and not any(row.strip() for row in rows0[:top0]),
      (top0, rows0[:top0]))

stub7, rows7 = chain_rows(7)
top7 = next(i for i, row in enumerate(rows7) if row.strip().startswith("╔"))
check("последний шаг остаётся в центре, прошедшие уезжают вверх",
      top7 == 6 and sum("✓" in row for row in rows7[:top7]) >= 2,
      (top7, rows7[:top7]))

# --------------------------------------------------------------------------- #
# Часть C: кадр прогона целиком
# --------------------------------------------------------------------------- #
stub = RunStub(TEXT8, done=3)
rows = mod.Tui(stub)._render(76, 24)
texts = [plain(row) for row in rows]
check("кадр прогона занимает весь экран", len(rows) == 24, len(rows))
check("сверху — машинка и секунды, ниже — статус и баннер",
      "🚗" in texts[0] and " / " in texts[0] and " с" in texts[0]
      and "прогон" in texts[1]
      and any(row.startswith("прогон:") for row in texts[2:4]), texts[:4])
check("в прогоне нет старой рамки программы и лога",
      not any("[prog]" in row for row in texts)
      and not any(row.startswith("┌─ лог") for row in texts), texts)
check("текущая рамка в центре всего кадра",
      texts[10].strip().startswith("╔"), texts[10])
check("цвета трёх состояний различимы",
      any("\x1b[2;37m" in row for row in rows)     # выполнено — серый
      and any("\x1b[1;33m" in row for row in rows)  # сейчас — жёлтый
      and any("\x1b[36m" in row for row in rows), rows)  # дальше — голубой

stub = RunStub("вперёд 1с\nвлево 1с\nпауза 1", repeat=2, done=3)
rows = [plain(row) for row in mod.Tui(stub)._render(76, 24)]
check("при повторе в статусе общий номер шага и множитель",
      "4/6" in rows[1] and "×2" in rows[1], rows[1])
check("при повторе цепочка нумеруется через круги",
      any("4/6" in row and "╔" in row for row in rows)
      and any("6/6" in row for row in rows), rows)
stub._run_paused = True
rows = [plain(row) for row in mod.Tui(stub)._render(76, 24)]
check("пауза видна в статусе", "пауза" in rows[1], rows[1])

mod.LANG, old_lang = "en", mod.LANG
try:
    stub = RunStub("вперёд 1с")
    rows = [plain(row) for row in mod.Tui(stub)._render(76, 24)]
    check("английский язык: секунды и действие в рамке",
          "0.0 / 1.0 s" in rows[0] and "forward" in "".join(rows), rows)
finally:
    mod.LANG = old_lang


# --------------------------------------------------------------------------- #
# Часть D: живой TUI — машинка едет, шаг остаётся в центре, пауза замирает
# --------------------------------------------------------------------------- #
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(PROGDIR)
os.makedirs(FAKEHOME)
route = os.path.join(PROGDIR, "route.txt")
with open(route, "w", encoding="utf-8") as fh:
    fh.write("скорость 6\nвперёд 0.9с\nвлево 0.5с\nпауза 0.3с\n"
             "вправо 0.5с\nназад 0.9с\nцвет 3\nмигнуть 1\n")

env = dict(os.environ)
env["TERM"] = "xterm-256color"
env["HOME"] = FAKEHOME

ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
ROW = re.compile(r"\x1b\[(\d+);1H\x1b\[2K(.*?)(?=\x1b\[[0-9]+;1H|\x1b\[\?25l|\Z)", re.S)


def frames(out):
    result = []
    for segment in out.split("\x1b[1;1H")[1:]:
        rows = {int(n): ANSI.sub("", text)
                for n, text in ROW.findall("\x1b[1;1H" + segment)}
        if rows:
            result.append(rows)
    return result


def last(out):
    all_frames = frames(out)
    return all_frames[-1] if all_frames else {}


def seconds(state):
    match = re.search(r"(\d+\.\d) / (\d+\.\d) с", state.get(1, ""))
    return (float(match.group(1)), float(match.group(2))) if match else None


def current_box(state):
    tops = [n for n, row in state.items() if row.strip().startswith("╔")]
    if not tops:
        return None, ""
    top = min(tops)
    return top, state.get(top + 1, "")


master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 76, 0, 0))
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--key-state-device", NOKS,
     "--program-dir", PROGDIR, "--program", route],
    stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
)
os.close(slave)
buf = b""


def read(seconds_):
    global buf
    end = time.time() + seconds_
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


def key(text, wait=0.4):
    os.write(master, text.encode())
    read(wait)
    return take()


try:
    read(1.5)
    take()
    key("q", 0.8)
    out = key("\r", 0.7)
    state = last(out)
    first = seconds(state)
    top1, body1 = current_box(state)
    check("живой прогон: сверху машинка и счётчик секунд",
          first is not None and "🚗" in state.get(1, ""), (first, state.get(1, "")))
    check("живой прогон: баннер режима прогона",
          any(row.startswith("прогон:") for row in state.values()), state)
    check("живой прогон: текущая рамка в центре",
          top1 is not None and 10 <= top1 <= 12, top1)
    check("живой прогон: в текущей рамке шаг и количество",
          "▶" in body1 and "вперёд" in body1 and "0.9 с" in body1,
          (top1, body1))

    out = take()
    read(1.0)
    out += take()
    later = last(out)
    second = seconds(later)
    top2, body2 = current_box(later)
    check("машинка едет: секунды растут", first and second and second[0] > first[0],
          (first, second))
    check("выполненные шаги появились над текущим",
          any("✓" in row for row in later.values()), later)
    check("текущий шаг остался в центре при прокрутке",
          top2 is not None and 10 <= top2 <= 12, top2)
    check("текущая рамка сменилась на следующий шаг",
          body2 != body1 and "//" not in body2, (body1, body2))

    pause = key(" ", 0.4)
    paused = last(pause)
    paused_seconds = seconds(paused)
    check("пауза: статус говорит «пауза»", "пауза" in paused.get(2, ""),
          paused.get(2, ""))
    read(1.0)
    paused2 = last(take())
    paused_seconds2 = seconds(paused2)
    check("пауза: машинка и секунды стоят",
          paused_seconds and paused_seconds2
          and abs(paused_seconds[0] - paused_seconds2[0]) < 0.11,
          (paused_seconds, paused_seconds2))

    key(" ", 0.2)
    read(3.2)
    out = take()
    state = last(out)
    check("после прогона — снова пульт",
          any(row.startswith("пульт:") for row in state.values()), state)
    check("отчёт о прогоне остался в логе",
          "[run] готово:" in out, out[-300:])
    check("в пульте машинки больше нет",
          not any("🚗" in row for row in state.values()), state)
finally:
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    read(0.4)
    take()
    os.close(master)

print(f"failures: {failures}")
sys.exit(1 if failures else 0)
