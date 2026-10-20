#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Частичный реверс: r/t на паузе везут обратно только проеханную часть."""
import asyncio
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
WORK = fresh_work("test24")
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


def show(steps):
    return " · ".join(mod.step_text(s) for s in steps)


def steps_of(text):
    steps, _, _, err = mod.parse_program(text)
    assert not err, err
    return steps


def editor_for(text, speed=None):
    editor = mod.ProgramEditor()
    editor.set_program(steps_of(text), 1, speed)
    return editor


def st(text):
    """Последний разобранный шаг программы (заготовка «текущего»)."""
    return steps_of(text)[-1]


def partial(text, mode, done_text="", current_step=None, used=0.0, **kw):
    """Готовый реверс проеханного: программа, режим и куски маршрута."""
    editor = editor_for(text)
    done = steps_of(done_text) if done_text else []
    return show(mod.partial_reverse_steps(
        done, editor, mode, current=current_step, used=used, **kw))


# --------------------------------------------------------------------------- #
# Часть A: сборка маршрута «обратно по проеханному»
# --------------------------------------------------------------------------- #
check("движения — это вперёд/назад/влево/вправо",
      set(mod.MOVE_VECTORS) == {"fwd", "back", "left", "right"}, set(mod.MOVE_VECTORS))

check("недоеханный шаг становится отрезком в секундах",
      partial("вперёд 2с", "back", current_step=st("вперёд 2с"), used=0.4) == "↓0.4с",
      partial("вперёд 2с", "back", current_step=st("вперёд 2с"), used=0.4))

check("маршрут: проеханное полностью + недоеханный шаг, всё в обратном порядке",
      partial("вперёд 1с\nвлево 0.5с\nвперёд 2с", "back",
              done_text="вперёд 1с\nвлево 0.5с",
              current_step=st("вперёд 2с"), used=0.4) == "↓0.4с · →0.5с · ↓1с",
      partial("вперёд 1с\nвлево 0.5с\nвперёд 2с", "back",
              done_text="вперёд 1с\nвлево 0.5с",
              current_step=st("вперёд 2с"), used=0.4))

check("длительность недоеханного больше плана — обрезается планом",
      partial("вперёд 2с", "back", current_step=st("вперёд 2с"), used=99) == "↓2с",
      partial("вперёд 2с", "back", current_step=st("вперёд 2с"), used=99))

check("шаг короче MIN_STEP_SECONDS в маршрут не попадает",
      partial("вперёд 2с", "back", current_step=st("вперёд 2с"),
              used=mod.MIN_STEP_SECONDS / 2) == "",
      partial("вперёд 2с", "back", current_step=st("вперёд 2с"),
              used=mod.MIN_STEP_SECONDS / 2))

check("ровно MIN_STEP_SECONDS — попадает",
      partial("вперёд 2с", "back", current_step=st("вперёд 2с"),
              used=mod.MIN_STEP_SECONDS) == "↓0.05с",
      partial("вперёд 2с", "back", current_step=st("вперёд 2с"),
              used=mod.MIN_STEP_SECONDS))

check("недоеханная пауза робота не двигает — в маршрут не идёт",
      partial("пауза 2с", "back", current_step=st("пауза 2с"), used=1.0) == "",
      partial("пауза 2с", "back", current_step=st("пауза 2с"), used=1.0))

check("недоделанное мигание в маршрут не идёт",
      partial("мигнуть 3\nвперёд 2с", "back",
              current_step=st("мигнуть 3")) == "",
      partial("мигнуть 3\nвперёд 2с", "back", current_step=st("мигнуть 3")))

check("недоделанный цвет в маршрут не идёт",
      partial("цвет 3\nвперёд 2с", "back", current_step=st("цвет 3")) == "",
      partial("цвет 3\nвперёд 2с", "back", current_step=st("цвет 3")))

check("недоеханная смена скорости в маршрут не идёт",
      partial("вперёд 1с\nскорость 12\nвперёд 2с", "back",
              current_step=st("вперёд 1с\nскорость 12")) == "",
      partial("вперёд 1с\nскорость 12\nвперёд 2с", "back",
              current_step=st("вперёд 1с\nскорость 12")))

check("полностью проеханные движения считаются",
      partial("вперёд 1с\nвлево 0.5с", "back",
              done_text="вперёд 1с\nвлево 0.5с") == "→0.5с · ↓1с",
      partial("вперёд 1с\nвлево 0.5с", "back",
              done_text="вперёд 1с\nвлево 0.5с"))

check("проеханные паузы остаются (как и у полного реверса)",
      partial("вперёд 1с\nпауза 1\nвлево 1с", "back",
              done_text="вперёд 1с\nпауза 1\nвлево 1с") == "→1с · ‖1с · ↓1с",
      partial("вперёд 1с\nпауза 1\nвлево 1с", "back",
              done_text="вперёд 1с\nпауза 1\nвлево 1с"))

check("drop_pauses выбрасывает паузы и из проеханного",
      partial("вперёд 1с\nпауза 1\nвлево 1с", "back",
              done_text="вперёд 1с\nпауза 1\nвлево 1с",
              drop_pauses=True) == "→1с · ↓1с",
      partial("вперёд 1с\nпауза 1\nвлево 1с", "back",
              done_text="вперёд 1с\nпауза 1\nвлево 1с", drop_pauses=True))

check("мигание остаётся миганием",
      partial("мигнуть 2\nвперёд 1с", "back",
              done_text="мигнуть 2\nвперёд 1с") == "↓1с · ✦2",
      partial("мигнуть 2\nвперёд 1с", "back", done_text="мигнуть 2\nвперёд 1с"))

check("режим front: вперёд/назад не реверсится",
      partial("вперёд 1с\nвлево 1с", "front",
              done_text="вперёд 1с\nвлево 1с") == "→1с · ↑1с",
      partial("вперёд 1с\nвлево 1с", "front", done_text="вперёд 1с\nвлево 1с"))

check("режим front: недоеханный шаг тоже не реверсится",
      partial("вперёд 2с", "front", current_step=st("вперёд 2с"),
              used=0.5) == "↑0.5с",
      partial("вперёд 2с", "front", current_step=st("вперёд 2с"), used=0.5))

check("скорость — в точках смены, от скорости конца маршрута",
      partial("вперёд 1с\nскорость 12\nвлево 2с", "back",
              done_text="вперёд 1с\nскорость 12",
              current_step=st("влево 2с"), used=0.5) == "»12 · →0.5с · »6 · ↓1с",
      partial("вперёд 1с\nскорость 12\nвлево 2с", "back",
              done_text="вперёд 1с\nскорость 12",
              current_step=st("влево 2с"), used=0.5))

lit = mod.NUMBER_BY_COLOR.get(mod.COLOR_BY_NUMBER[3])  # так же считает и пульт
check("номер цвета ходит через COLOR_BY_NUMBER/NUMBER_BY_COLOR", lit == 3, lit)
check("свет — в точках смены, base_light — что горит сейчас",
      partial("цвет 8\nвперёд 1с\nцвет 3\nвлево 2с", "back",
              done_text="цвет 8\nвперёд 1с\nцвет 3",
              current_step=st("влево 2с"), used=0.5,
              base_light=lit) == "→0.5с · ●8 · ↓1с",
      partial("цвет 8\nвперёд 1с\nцвет 3\nвлево 2с", "back",
              done_text="цвет 8\nвперёд 1с\nцвет 3",
              current_step=st("влево 2с"), used=0.5, base_light=lit))

check("цвет проеханного ставится явно, даже если base_light неизвестен",
      partial("цвет 3\nвперёд 1с", "back", done_text="цвет 3\nвперёд 1с") == "●3 · ↓1с",
      partial("цвет 3\nвперёд 1с", "back", done_text="цвет 3\nвперёд 1с"))

check("пустое проеханное — пустой маршрут",
      partial("вперёд 2с", "back") == "" and
      partial("вперёд 2с", "back", drop_pauses=True) == "")

check("reversed_steps с готовым steps= совпадает со старым вызовом",
      show(mod.reversed_steps(editor_for("вперёд 1с\nвлево 2с"), "back")) ==
      show(mod.reversed_steps(editor_for("вперёд 1с\nвлево 2с"), "back",
                              steps=steps_of("вперёд 1с\nвлево 2с"))))


# --------------------------------------------------------------------------- #
# Часть A2: продолжение обычной программы с паузы (Enter)
# --------------------------------------------------------------------------- #
def remaining(text, index, used):
    editor = editor_for(text)
    info = mod.ResumeInfo(editor.steps, index, used, editor)
    return show(info.remaining())


check("продолжение: остаток текущего шага и всё после него",
      remaining("вперёд 5с\nвправо 2с", 0, 3.0) == "↑2с · →2с",
      remaining("вперёд 5с\nвправо 2с", 0, 3.0))
check("продолжение: соседние одинаковые движения склеиваются",
      remaining("вперёд 2с\nвперёд 3с", 0, 1.0) == "↑4с",
      remaining("вперёд 2с\nвперёд 3с", 0, 1.0))
check("продолжение: на конце программы остаётся пусто",
      remaining("вперёд 2с", 1, 0.0) == "" and
      remaining("вперёд 2с", 0, 2.0) == "",
      (remaining("вперёд 2с", 1, 0.0), remaining("вперёд 2с", 0, 2.0)))

editor = editor_for("вперёд 5с\nвправо 2с")
info = mod.ResumeInfo(editor.steps, 0, 3.0, editor, repeat=4, rep=2)
check("продолжение: остаток круга и оставшиеся повторы",
      show(info.remaining_all()) == "↑2с · →2с · ↑5с · →2с · ↑5с · →2с",
      show(info.remaining_all()))


class PauseStub:
    """Мини-пульт в паузе: план, проеханное и текущий шаг."""


editor = editor_for("вперёд 5с\nвправо 2с")
PauseStub._run_plan = mod.RunPlan(editor.steps, 6, 1, editor=editor)
PauseStub._run_done = [editor.steps[0]]
PauseStub._run_current = editor.steps[1]
PauseStub._run_progress = 0.5
PauseStub._run_step = 2
PauseStub._run_rep = 1
PauseStub._run_editor = editor
PauseStub.speed = 6
PauseStub._run_led = mod.Color.WHITE
PauseStub._resume_info_from_run = mod.Remote._resume_info_from_run
resume = mod.Remote._resume_plan(PauseStub())
check("Enter на паузе обычного прогона: остаток шага и дальше",
      resume is not None and show(resume.steps) == "→1.5с",
      show(resume.steps) if resume else None)
check("продолжение с места — без повтора и с пометкой partial",
      resume is not None and resume.repeat == 1 and resume.partial
      and resume.rev is None,
      (resume.repeat, resume.partial, resume.rev) if resume else None)

editor = editor_for("вперёд 5с\nвправо 2с")
RepeatStub = type("RepeatStub", (), {})
RepeatStub._run_plan = mod.RunPlan(editor.steps, 6, 4, editor=editor)
RepeatStub._run_done = [editor.steps[0]]
RepeatStub._run_current = editor.steps[1]
RepeatStub._run_progress = 0.5
RepeatStub._run_step = 2
RepeatStub._run_rep = 2
RepeatStub._run_editor = editor
RepeatStub.speed = 6
RepeatStub._run_led = mod.Color.WHITE
RepeatStub._resume_info_from_run = mod.Remote._resume_info_from_run
resume = mod.Remote._resume_plan(RepeatStub())
check("Enter на паузе повторяемой программы: остаток и оставшиеся круги",
      resume is not None
      and show(resume.steps) == "→1.5с · ↑5с · →2с · ↑5с · →2с",
      show(resume.steps) if resume else None)

# Тот самый пример: вперёд 5, вправо 5, вперёд 20; пауза на 16-й секунде,
# реверс доехал назад 16 с и 3 с поворота налево.
editor = editor_for("вперёд 5с\nвправо 5с\nвперёд 20с")
reverse = mod.partial_reverse_steps(
    editor.steps[:2], editor, "back", current=editor.steps[2], used=16.0)
origin = mod.ResumeInfo(editor.steps, 2, 16.0, editor, speed=6, led=8)
reverse_plan = mod.RunPlan(reverse, 6, 1, "back", partial=True,
                           editor=editor, origin=origin)


class ReversePauseStub:
    _run_plan = reverse_plan
    _run_done = [reverse[0]]
    _run_current = reverse[1]
    _run_progress = 3.0
    _run_step = 2
    _run_rep = 1
    _run_editor = editor
    speed = 6
    _run_led = mod.Color.WHITE


resume = mod.Remote._resume_plan(ReversePauseStub())
check("Enter на паузе реверса: 3 с поворота направо и 20 с вперёд",
      resume is not None and show(resume.steps) == "→3с · ↑20с",
      show(resume.steps) if resume else None)
check("продолжение после реверса не повторяет программу",
      resume is not None and resume.repeat == 1 and resume.partial
      and resume.rev is None,
      (resume.repeat, resume.partial, resume.rev) if resume else None)


class ResumeStub:
    """Мини-пульт: пауза уже нажата, частичный реверс ждёт остановки прогона."""
    _run_paused = True
    _run_abort = "partial"
    _partial_pending = True

    def _say(self, tag, text):
        pass


async def resume_pending():
    stub = ResumeStub()
    await mod.Remote._handle_run_key(stub, " ")
    return stub


stub = asyncio.run(resume_pending())
check("пробел во время ожидания реверса продолжает прогон",
      stub._run_paused is False, stub._run_paused)
check("пробел во время ожидания реверса отменяет отложенный запуск",
      stub._partial_pending is False and stub._run_abort is None,
      (stub._partial_pending, stub._run_abort))

# --------------------------------------------------------------------------- #
# Часть B: пульт — пауза, потом r/t
# --------------------------------------------------------------------------- #
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(PROGDIR)
os.makedirs(FAKEHOME)

env = dict(os.environ)
env["TERM"] = "xterm-256color"
env["HOME"] = FAKEHOME
env["EDITOR"] = "true"       # «редактор», который сразу закрывается
JOURNAL = os.path.join(FAKEHOME, ".config", "apitor-control", "runs.log")


class Term:
    """Пульт в --simulate: клавиши в PTY, вывод копим и разбираем."""

    def __init__(self, program: str, name: str):
        path = os.path.join(PROGDIR, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(program)
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
        self.proc = subprocess.Popen(
            [PY, APP, "--simulate", "--no-tui", "--no-key-state", "--log",
             "--program-dir", PROGDIR, "--program", path],
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

    def key(self, text, wait=0.4):
        os.write(self.master, text.encode())
        self.read(wait)
        return self.take()

    def wait(self, seconds):
        self.read(seconds)
        return self.take()

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(2)
        except Exception:  # noqa: BLE001 — тест не должен зависать
            self.proc.kill()


def run_reversed(text):
    """Длительность и значок первого шага обратного прогона."""
    m = re.search(r"▶ ([↑↓←→])(\d+(?:\.\d+)?)с", text)
    return (m.group(1), float(m.group(2))) if m else (None, None)


# ── сценарий 1: «вперёд 2с», пауза на ~0.5 с, r ───────────────────────────── #
t = Term("вперёд 2с\n", "сценарий1.txt")
try:
    out = t.key("\r", 0.2) + t.wait(0.6)      # Enter — пуск, едем
    check("пуск: программа поехала", "▶ ↑2с" in out, out)
    out = t.key(" ", 0.3)                     # пауза
    check("пауза: подсказка про r/t",
          "r/t — обратно по проеханному" in out, out)
    out = t.key("r", 1.6)
    check("r на паузе: прогон прерван ради возврата",
          "пауза на шаге 1 из 1 — везу обратно по проеханному" in out, out)
    check("r на паузе: заголовок — реверс проеханной части",
          "старт: 1 шаг · скор. 6 · реверс проеханной части (задним ходом)" in out, out)
    kind, secs = run_reversed(out)
    check("r на паузе: едем назад отрезком проеханного",
          kind == "↓" and secs is not None and 0.15 <= secs < 1.99,
          (kind, secs, out))
    check("r на паузе: прогон завершён", "готово: 1 шаг" in out, out)

    out = t.key("p", 0.4)
    check("программа в редакторе не изменилась",
          "↑2с" in out and "1 шаг" in out, out)
    out = t.key("\x1b", 0.3)                  # Esc — назад в пульт
finally:
    t.stop()

check("журнал: частичный реверс записан",
      os.path.exists(JOURNAL) and "пауза на шаге 1/1" in open(JOURNAL, encoding="utf-8").read(),
      open(JOURNAL, encoding="utf-8").read() if os.path.exists(JOURNAL) else "нет файла")

# ── сценарий 2: t на паузе — робота развернули рукой ──────────────────────── #
t = Term("вперёд 2с\n", "сценарий2.txt")
try:
    t.key("\r", 0.2)
    t.wait(0.6)
    t.key(" ", 0.3)
    out = t.key("t", 1.6)
    check("t на паузе: заголовок — реверс проеханной части (развёрнут)",
          "реверс проеханной части (робот развёрнут)" in out, out)
    kind, secs = run_reversed(out)
    check("t на паузе: вперёд остаётся вперёд, но только проеханное",
          kind == "↑" and secs is not None and 0.15 <= secs < 1.99, (kind, secs, out))
    check("t на паузе: прогон завершён", "готово: 1 шаг" in out, out)
finally:
    t.stop()

# ── сценарий 3: r без паузы — подсказка, прогон продолжается ──────────────── #
t = Term("вперёд 2с\n", "сценарий3.txt")
try:
    t.key("\r", 0.2)
    out = t.wait(0.4) + t.key("r", 0.5)
    check("r без паузы: сначала просят паузу",
          "сначала пауза (пробел), потом r или t" in out, out)
    check("r без паузы: реверса нет", "реверс проеханной части" not in out, out)
    out = t.wait(1.8)
    check("r без паузы: исходный прогон доехал сам", "готово: 1 шаг" in out, out)
finally:
    t.stop()

# ── сценарий 4: ещё не ехали — возвращаться некуда ────────────────────────── #
t = Term("пауза 2\n", "сценарий4.txt")
try:
    t.key("\r", 0.2)
    t.wait(0.3)
    t.key(" ", 0.3)
    out = t.key("r", 0.5)
    check("робот ещё не двигался: возвращаться некуда",
          "возвращаться некуда" in out and "реверс проеханной части" not in out, out)
    out = t.key("\x1b", 1.0)                  # Esc — прервать прогон
    check("после отказа прогон можно прервать", "прервано на шаге 1 из 1" in out, out)
finally:
    t.stop()

# ── сценарий 5: шаги 1с + пауза 1 + 2с, пауза на третьем шаге ─────────────── #
t = Term("вперёд 1с\nпауза 1\nвлево 2с\n", "сценарий5.txt")
try:
    out = t.key("\r", 0.2) + t.wait(2.6)
    check("сценарий 5: второй шаг уже проехан, третий идёт",
          "▶ ↑1с" in out and "▶ ‖" in out and "▶ ←2с" in out, out)
    out = t.key(" ", 0.3)
    out = t.key("r", 3.6)
    check("частичный реверс: шагов столько же (пауза осталась)",
          "старт: 3 шага" in out and "реверс проеханной части" in out, out)
    check("частичный реверс: недоеханный поворот — вправо",
          re.search(r"▶ →\d+(?:\.\d+)?с", out) is not None, out)
    check("частичный реверс: счётчик-пауза стала секундами",
          "▶ ‖1с" in out, out)
    order = [out.find("▶ →"), out.find("▶ ‖"), out.find("▶ ↓")]
    check("частичный реверс: обратный порядок — поворот, пауза, вперёд",
          all(i >= 0 for i in order) and order == sorted(order), (order, out))
    check("частичный реверс: доехали", "готово: 3 шага" in out, out)

    # тот же участок, но R — без пауз
    out = t.key("\r", 0.2) + t.wait(2.6)
    check("сценарий 5: прогон запущен заново", "старт: 3 шага" in out, out)
    t.key(" ", 0.3)
    out = t.key("R", 2.6)
    check("R на паузе: реверс проеханной части без пауз",
          "реверс проеханной части (задним ходом) · без пауз" in out, out)
    check("R на паузе: пауза выброшена из проеханного",
          "старт: 2 шага" in out and "▶ ‖" not in out, out)
    check("R на паузе: доехали", "готово: 2 шага" in out, out)
finally:
    t.stop()

# ── сценарий 6: Enter на паузе обычного прогона — продолжить с места ──────── #
t = Term("вперёд 1.2с\nвправо 0.6с\n", "сценарий6.txt")
try:
    t.key("\r", 0.2)
    t.wait(0.4)
    out = t.key(" ", 0.2)
    check("обычная пауза: подсказка про Enter",
          "Enter — с места" in out, out)
    out = t.key("\r", 4.0)
    check("Enter на паузе: останавливает и продолжает с места",
          "сейчас продолжу с текущего места" in out
          and "старт: 2 шага · скор. 6 · продолжение с места" in out, out)
    check("Enter на паузе: остаток шага и следующий шаг",
          re.search(r"▶ ↑\d+(?:\.\d+)?с", out) is not None
          and "▶ →0.6с" in out, out)
    check("Enter на паузе: программа доехала", "готово: 2 шага" in out, out)
finally:
    t.stop()

# ── сценарий 7: пауза во время реверса, Enter — обратно на обычный маршрут ── #
t = Term("вперёд 0.8с\nвправо 2с\nвперёд 0.6с\n", "сценарий7.txt")
try:
    t.key("\r", 0.2)
    t.wait(2.7)                    # ~0.1 с последнего «вперёд»
    t.key(" ", 0.2)
    out = t.key("r", 1.1)          # назад 0.1 с и в поворот налево
    check("сценарий 7: реверс поехал",
          "реверс проеханной части" in out and "▶ ←" in out, out)
    t.key(" ", 0.2)                # пауза в повороте реверса
    out = t.key("\r", 2.5)
    check("Enter на паузе реверса: продолжение с места",
          "сейчас продолжу с текущего места" in out
          and "продолжение с места" in out, out)
    check("Enter на паузе реверса: поворот направо и снова вперёд",
          "▶ →" in out and "▶ ↑" in out, out)
    check("Enter на паузе реверса: доехали", "готово: 2 шага" in out, out)
finally:
    t.stop()

check("журнал: продолжение с места записано",
      os.path.exists(JOURNAL) and "продолжение с шага" in open(
          JOURNAL, encoding="utf-8").read(),
      open(JOURNAL, encoding="utf-8").read() if os.path.exists(JOURNAL) else "нет файла")

print()
print("ОШИБОК:", failures)
sys.exit(1 if failures else 0)
