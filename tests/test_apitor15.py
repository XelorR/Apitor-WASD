#!/usr/bin/env python3
"""Макросы: запись (M … Enter), шаги с секундами, R/x/p/f/g, блокировки."""
import importlib.util
import os
import pty
import re
import select
import shutil
import subprocess
import sys
import time

from harness import ROOT, PY, APP, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test15")
PROGDIR = os.path.join(WORK, "programs")
FAKEHOME = os.path.join(WORK, "home")
KBD = os.path.join(WORK, "kbd")

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(PROGDIR)
os.makedirs(FAKEHOME)
os.mkfifo(KBD)

spec = importlib.util.spec_from_file_location("apitor_remote", APP)
mod = importlib.util.module_from_spec(spec)
sys.modules["apitor_remote"] = mod
spec.loader.exec_module(mod)

EVENT = mod._EVENT
KEY_W, KEY_A, KEY_D, KEY_S = 17, 30, 32, 31
KEY_1, KEY_B = 2, 48
LSHIFT, RSHIFT = 42, 54

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


# --------------------------------------------------------------------------- #
# Часть A: модульные проверки
# --------------------------------------------------------------------------- #

def kinds(steps):
    return [(s.kind, s.value, s.seconds) for s in steps]


# секунды разными способами
text = "скорость 6\nвперёд 1.2с\nпауза 0.4s\nвправо 1.5сек\nвперёд 2.5\n"
steps, repeat, speed, errors = mod.parse_program(text)
check("parser: секунды в разных видах", errors == [] and kinds(steps) == [
    ("fwd", 1, 1.2), ("pause", 1, 0.4), ("right", 1, 1.5), ("fwd", 1, 2.5),
], (errors, kinds(steps)))
check("parser: «скорость» в начале — шапка", speed == 6 and repeat == 1)

# «с» и «s» равнозначны: пульт пишет по языку интерфейса, а читает оба
same = []
for text in ("вперёд 1.1s", "вперёд 1.1с", "вперёд 1.1 s", "вперёд 1.1S",
             "вперёд 1,1s", "↑1.1s", "вперёд 1.1sec", "вперёд 1.1 секунды",
             "вперёд 1.1s # сек", "ВПЕРЁД 1.1S"):
    steps, _, _, errors = mod.parse_program(text + "\n")
    same.append((text, errors, kinds(steps)))
check("parser: «1.1s» == «1.1с» (и s, и S, и с пробелом)",
      all(e == [] and k == [("fwd", 1, 1.1)] for _, e, k in same),
      [x for x in same if x[1] or x[2] != [("fwd", 1, 1.1)]])

# интерфейс — только про запись: файл с «s» читается и в русском режиме
mod.LANG = "en"
en_steps, _, _, en_err = mod.parse_program("speed 6\nforward 1.5s\n")
ed_en = mod.ProgramEditor()
ed_en.set_program(en_steps, 1, 6)
en_text = ed_en.serialize()
check("parser: англ. интерфейс пишет «1.5s»",
      en_err == [] and "forward 1.5s" in en_text, en_text)
check("step_text: англ. — ↑1.5s", mod.step_text(en_steps[0]) == "↑1.5s",
      mod.step_text(en_steps[0]))
mod.LANG = "ru"
ru_steps, _, _, ru_err = mod.parse_program(en_text)
check("parser: файл с «1.5s» читается и в рус. интерфейсе",
      ru_err == [] and ru_steps[0].seconds == 1.5, (en_text, ru_err))
ed_ru = mod.ProgramEditor()
ed_ru.set_program(ru_steps, 1, 6)
check("parser: рус. интерфейс пишет «1.5с»", "вперёд 1.5с" in ed_ru.serialize(),
      ed_ru.serialize())

# смена скорости по ходу
steps, _, speed, errors = mod.parse_program("скорость 4\nвперёд 1с\nскорость 9\nназад 0.5с\n")
check("parser: смена скорости в середине — шаг", errors == [] and kinds(steps) == [
    ("fwd", 1, 1.0), ("speed", 9, None), ("back", 1, 0.5),
], (errors, kinds(steps)))

# значки
steps, _, _, errors = mod.parse_program("↑1.2с →0.5с »12 ‖2с ✦ ●8\n")
check("parser: значки с секундами", errors == [] and kinds(steps) == [
    ("fwd", 1, 1.2), ("right", 1, 0.5), ("speed", 12, None),
    ("pause", 1, 2.0), ("blink", 1, None), ("color", 8, None),
], (errors, kinds(steps)))

# десятичная запятая и «мелочи»
steps, _, _, errors = mod.parse_program("вперёд 1,5с\n")
check("parser: запятая вместо точки", errors == [] and steps[0].seconds == 1.5, (errors,))

# ошибки
for name, bad, expect in (
    ("мигнуть в секундах", "мигнуть 1с\n", "не бывает в секундах"),
    ("цвет в секундах", "цвет 1с\n", "не бывает в секундах"),
    ("слишком короткий шаг", "вперёд 0.001с\n", "от 0.05"),
    ("слишком длинный шаг", "вперёд 601с\n", "до 600"),
    ("повтор в секундах", "повтор 1с\n", "число 1..99"),
    ("скорость в секундах", "скорость 1с\n", "число 1..12"),
    ("число без команды", "1.2с\n", "без команды"),
):
    _, _, _, errors = mod.parse_program(bad)
    check(f"parser-ошибка: {name}", len(errors) == 1 and expect in errors[0], errors)

# сериализация и круговорот
ed = mod.ProgramEditor()
steps, repeat, speed, _ = mod.parse_program(
    "скорость 7\nвперёд 1.25с\nпауза 0.4с\nвправо 2\nскорость 12\nвперёд 0.5с\nцвет 8\n"
)
ed.set_program(steps, repeat, speed)
out = ed.serialize()
check("serialize: секунды и скорость по ходу",
      "вперёд 1.25с" in out and "скорость 12" in out.splitlines()[4], out)
back = mod.parse_program(out)
check("serialize: круговорот", kinds(back[0]) == kinds(steps) and back[2] == speed, out)
check("serialize: шапка скорости одна", out.splitlines()[0] == "скорость 7", out)

# значок шага
check("step_text: секунды", mod.step_text(mod.Step("fwd", 1, 1.2)) == "↑1.2с")
check("step_text: скорость", mod.step_text(mod.Step("speed", 12)) == "»12")
check("step_text: цвет", mod.step_text(mod.Step("color", 8)) == "●8")

# цвета: белый = 8, а у Color.WHITE значение 10
check("цвета: номер 8 — белый", mod.COLOR_BY_NUMBER[8] == mod.Color.WHITE)
check("цвета: белый — номер 8", mod.NUMBER_BY_COLOR[mod.Color.WHITE] == 8)
check("цвета: 0 — выключить", mod.COLOR_BY_NUMBER[0] == mod.Color.OFF)
check("цвета: 1 — красный", mod.COLOR_BY_NUMBER[1] == mod.Color.RED)

# редактор: шаги и секунды соседствуют
ed = mod.ProgramEditor()
steps, _, _, _ = mod.parse_program("вперёд 1с\n")
ed.set_program(steps, 1, 6)
now = 100.0
ed.key("w", now)           # новый шаг, а не +1 к шагу с секундами
check("редактор: w после шага с секундами добавляет шаг",
      [s.kind for s in ed.steps] == ["fwd", "fwd"] and ed.steps[0].seconds == 1.0
      and ed.steps[1].seconds is None, [(s.kind, s.seconds) for s in ed.steps])
ed.clear()
steps, _, _, _ = mod.parse_program("вперёд 1с\n")
ed.set_program(steps, 1, 6)
res = ed.key("5", now + 0.1)   # число к шагу с секундами — предупреждение
check("редактор: число после шага с секундами — предупреждение",
      res is not None and res.action == "warn", res.action if res else None)
ed.key("backspace", now + 0.2)
check("редактор: Backspace убирает шаг с секундами", len(ed.steps) == 0, ed.steps)
ed.set_program(steps, 1, 6)
check("редактор: has_timed", ed.has_timed() is True)
ed.clear()
ed.key("w", now)
check("редактор: обычная программа — не макрос", ed.has_timed() is False)

# запись: сценарии
def record(script):
    rec = mod.MacroRecorder()
    rec.start(6)
    script(rec)
    return rec.stop(999.0)


steps = record(lambda r: (r.move("fwd", 10.0, 6), r.move(None, 11.2, 6),
                          r.move("back", 11.7, 6), r.move(None, 12.5, 6)))
check("запись: движение, ожидание, движение", kinds(steps) == [
    ("fwd", 1, 1.2), ("pause", 1, 0.5), ("back", 1, 0.8)], kinds(steps))

steps = record(lambda r: (r.move("fwd", 0.0, 6), r.move("left", 1.0, 6),
                          r.move(None, 1.5, 6)))
check("запись: смена направления без стопа",
      kinds(steps) == [("fwd", 1, 1.0), ("left", 1, 0.5)], kinds(steps))

steps = record(lambda r: (r.move("fwd", 0.0, 6), r.event("color", 3, 1.0),
                          r.move(None, 2.0, 6), r.event("blink", 1, 3.0),
                          r.move("fwd", 4.0, 6), r.move(None, 5.0, 6)))
check("запись: свет рвёт отрезок, мигание в паузе", kinds(steps) == [
    ("fwd", 1, 1.0), ("color", 3, None), ("fwd", 1, 1.0),
    ("pause", 1, 1.0), ("blink", 1, None), ("pause", 1, 1.0), ("fwd", 1, 1.0),
], kinds(steps))

steps = record(lambda r: (r.move("fwd", 0.0, 6), r.speed_changed(12, 1.0),
                          r.speed_changed(6, 2.0), r.move(None, 3.0, 6)))
check("запись: буст на ходу", kinds(steps) == [
    ("fwd", 1, 1.0), ("speed", 12, None), ("fwd", 1, 1.0),
    ("speed", 6, None), ("fwd", 1, 1.0)], kinds(steps))

steps = record(lambda r: (r.speed_changed(9, 1.0), r.move("fwd", 2.0, 9),
                          r.move(None, 3.0, 9)))
check("запись: скорость, менявшаяся стоя, — перед движением",
      kinds(steps) == [("speed", 9, None), ("fwd", 1, 1.0)], kinds(steps))

steps = record(lambda r: (r.move("fwd", 0.0, 6), r.move(None, 0.02, 6),
                          r.move("fwd", 0.1, 6), r.move(None, 1.0, 6)))
check("запись: дребезг не пишется", kinds(steps) == [("fwd", 1, 0.9)], kinds(steps))

rec = mod.MacroRecorder()
rec.start(6)
rec.move("fwd", 0.0, 6)
rec.move(None, 5.0, 6)
steps = rec.stop(20.0)
check("запись: пауза до Enter не пишется", kinds(steps) == [("fwd", 1, 5.0)], kinds(steps))


# точность прогона: сроки по часам, ошибка не накапливается
import asyncio


class TimingRobot:
    async def stop_all_motors(self):
        pass


class TimingStub:
    _run_paused = False
    _run_abort = None
    RUN_TICK = mod.Remote.RUN_TICK
    robot = TimingRobot()

    def _is_connected(self):
        return True

    def _check_run(self):
        if self._run_abort is not None:
            raise mod._RunAbort

    async def _call(self, fn, *args):
        return True

    async def _raw_drive(self, move, speed):
        return True


async def measure():
    stub = TimingStub()
    t0 = time.monotonic()
    await mod.Remote._run_motion(stub, "fwd", 0.30, 6)
    motion = time.monotonic() - t0
    t0 = time.monotonic()
    await mod.Remote._sleep_checked(stub, 0.30)
    pause = time.monotonic() - t0
    t0 = time.monotonic()
    for _ in range(10):
        await mod.Remote._run_motion(stub, "fwd", 0.05, 6)
    ten = time.monotonic() - t0
    return motion, pause, ten


motion, pause, ten = asyncio.run(measure())
check("точность прогона: 0.30 с движения (<= 20 мс)", abs(motion - 0.30) <= 0.02, motion)
check("точность прогона: 0.30 с паузы (<= 20 мс)", abs(pause - 0.30) <= 0.02, pause)
check("точность прогона: 10 отрезков по 0.05 с без накопления ошибки",
      abs(ten - 0.50) <= 0.03, ten)


async def paused_measure():
    """Пауза прогона не должна «съедать» остаток шага."""
    stub = TimingStub()
    stub._run_paused = True
    task = asyncio.create_task(mod.Remote._sleep_checked(stub, 0.30))
    await asyncio.sleep(0.5)
    still_paused = not task.done()
    stub._run_paused = False
    t0 = time.monotonic()
    await task
    return still_paused, time.monotonic() - t0


still_paused, rest = asyncio.run(paused_measure())
check("пауза прогона: пауза-шаг не заканчивается сам", still_paused)
check("пауза прогона: после продолжения — остаток шага (~0.30 с)",
      abs(rest - 0.30) <= 0.05, rest)


# --------------------------------------------------------------------------- #
# Часть B: живой пульт (PTY + --simulate + key-state через FIFO)
# --------------------------------------------------------------------------- #

env = dict(os.environ)
env["TERM"] = "dumb"
env["HOME"] = FAKEHOME
master, slave = pty.openpty()
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--no-tui", "--speed", "6", "--key-state-device", KBD,
     "--program-dir", PROGDIR],
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


def key(text, wait=0.5):
    """Нажатие «как в терминале»: enter/esc/backspace — служебные байты."""
    raw = {"enter": b"\r", "esc": b"\x1b", "backspace": b"\x7f"}.get(text)
    os.write(master, raw if raw is not None else text.encode())
    read(wait)
    return take()


def wait(seconds):
    read(seconds)
    return take()


def hold(code, seconds, wait=0.4):
    """Нажать и отпустить клавишу (key-state): отрезок движения длится seconds."""
    os.write(kbd, EVENT.pack(0, 0, 1, code, 1))
    time.sleep(seconds)
    os.write(kbd, EVENT.pack(0, 0, 1, code, 0))
    read(wait)
    return take()


def tap(code, wait=0.4):
    os.write(kbd, EVENT.pack(0, 0, 1, code, 1))
    os.write(kbd, EVENT.pack(0, 0, 1, code, 0))
    read(wait)
    return take()


def secs_in(out):
    return [float(x) for x in re.findall(r"\[rec\] (?:↑|↓|←|→|‖)([\d.]+)с", out)]


read(1.5)
take()
out = key("m")
check("M без подключения — предупреждение", "запись макроса: сначала подключитесь" in out, out)
out = key("q")
check("подключение (--simulate)", "подключено" in out, out)

# -- запись макроса ---------------------------------------------------------- #
out = key("m")
check("M начинает запись", "запись макроса" in out, out)
text = hold(KEY_W, 0.6)
text += hold(KEY_A, 0.5)
check("запись: движение вперёд попало в лог", "↑" in text and "‖" in text, text)
rec_secs = secs_in(text)
check("запись: длительность вперёд ≈ 0.6 с",
      any(0.45 <= s <= 0.85 for s in rec_secs), rec_secs)
check("запись: пауза между действиями ≈ 0.4 с",
      any(0.25 <= s <= 0.7 for s in rec_secs), rec_secs)
out = key("esc", 1.0)
check("Esc останавливает запись", "макрос записан" in out and "Enter — проехать" in out, out)
check("макрос: три шага", "3 шага" in out, out)
m = re.search(r"макрос записан: 3 шага · ([\d.]+) с", out)
check("макрос: сумма длительностей ≈ 1.5 с",
      m is not None and 1.2 <= float(m.group(1)) <= 2.0, out)
check("макрос показан строкой программы", "[prog]" in out and "↑" in out, out)

# -- Enter: повторить макрос ------------------------------------------------- #
out = key("enter", 0.1) + wait(3.0)
check("Enter: запуск макроса", "старт: 3 шага · скор. 6 · макрос" in out, out)
check("Enter: шаги с секундами", "▶ ↑" in out and "▶ ←" in out, out)
check("Enter: прогон завершён", "готово: 3 шага" in out, out)
check("Enter: подсказка после прогона", "Enter — ещё раз · r — назад" in out, out)
m = re.search(r"за ([\d.]+) с \(план ([\d.]+) с\)", out)
delta = float(m.group(1)) - float(m.group(2)) if m else -99
check("Enter: прогон не длиннее плана (разница — стартовый светофор ~0.35 с)",
      m is not None and 0.25 <= delta <= 0.6, (delta, out))

# -- x: очистить ------------------------------------------------------------- #
out = key("x")
check("x очищает макрос", "программа очищена" in out, out)
out = key("enter", 0.1) + wait(1.0)
check("Enter после x — подсказка, а не прогон",
      "программы нет" in out and "старт" not in out, out)

# -- макрос редактируется как программа -------------------------------------- #
key("m")
hold(KEY_W, 0.4)
out = key("esc", 0.8)
check("макрос записан повторно", "макрос записан" in out, out)
out = key("p")
check("p: редактор показывает секунды", "↑0.4с" in out and "шаг" in out, out)
out = key("w")
check("редактор: w добавляет шаг после макроса", "(2 шага" in out and "↑" in out, out)
out = key("backspace")
check("редактор: Backspace убирает добавленный шаг", "(1 шаг" in out, out)
out = key("esc")
check("Esc: назад в пульт", "пульт" in out, out)

# -- f: сохранить (имя по умолчанию — «макрос-…») ---------------------------- #
out = key("f")
check("f: имя по умолчанию для макроса", "макрос-" in out and "имя файла" in out, out)
out = key("enter", 0.8)
check("f: файл сохранён", "сохранено:" in out, out)
files = [f for f in os.listdir(PROGDIR) if f.startswith("макрос-")]
check("f: файл макроса на диске", len(files) == 1, os.listdir(PROGDIR))
saved = os.path.join(PROGDIR, files[0]) if files else ""
body = open(saved, encoding="utf-8").read() if saved else ""
check("файл макроса: секунды и скорость",
      re.search(r"^вперёд [\d.]+с$", body, re.M) is not None
      and body.startswith("скорость 6"), body)
check("файл макроса: разбирается без ошибок",
      mod.parse_program(body)[3] == [], mod.parse_program(body)[3])

# -- g: загрузить ------------------------------------------------------------ #
out = key("x")
out = key("g")
check("g: список файлов помечает макрос", "макрос ·" in out, out)
out = key("1", 0.3) + key("enter", 0.8)
check("g: загрузка файла", "загружено:" in out, out)
out = key("p")
check("g: макрос в редакторе после загрузки", "↑" in out and "с" in out, out)
key("esc")

# -- во время записи программа и файлы не трогаются -------------------------- #
out = key("m")
for pressed, name in (("p", "p"), ("x", "x"), ("f", "f"), ("g", "g"), ("r", "r"),
                      ("t", "t"), ("enter", "Enter")):
    out = key(pressed, 0.35)
    check(f"во время записи {name} заблокировано",
          "идёт запись макроса" in out, out)
out = key("m")
check("M во время записи не останавливает, а объясняет состояние",
      "запись уже идёт" in out and "Esc или n" in out, out)
out = key("n")
check("N останавливает запись", "ничего не записалось" in out
      or "макрос записан" in out, out)

# -- буст и свет попадают в макрос ------------------------------------------- #
out = key("m")
os.write(kbd, EVENT.pack(0, 0, 1, LSHIFT, 1))
read(0.25)
os.write(kbd, EVENT.pack(0, 0, 1, KEY_W, 1))
time.sleep(0.4)
os.write(kbd, EVENT.pack(0, 0, 1, KEY_W, 0))
read(0.15)
os.write(kbd, EVENT.pack(0, 0, 1, LSHIFT, 0))
read(0.3)
out += take()
hold(KEY_D, 0.3)          # после отпускания Shift скорость снова 6
out += take()
out += key("1")
out += key("esc", 1.0)
check("макрос: буст записан как смена скорости", "»12" in out and "»6" in out, out)
check("макрос: свет записан", "●1" in out, out)
# в записи есть и смены скорости, и ожидания, и свет
check("макрос: последовательность »12 ↑ ‖ »6 → ‖ ●1 записана целиком",
      re.search(r"\[prog\] »12 · ↑[\d.]+с · ‖[\d.]+с · »6 · →[\d.]+с · ‖[\d.]+с · ●1",
                out) is not None, out)

# -- цвет 8 (белый) в программе: раньше ронял прогон ------------------------- #
out = key("x")
out = key("p")
for _ in range(8):
    out = key("c", 0.3)
check("редактор: цвет доведён до белого", "●8" in out, out)
out = key("enter", 0.1) + wait(1.5)
check("прогон с цветом 8 не падает", "готово: 1 шаг" in out and "прервано" not in out, out)
white_frame = mod.p.led_command(4, int(mod.Color.WHITE)).hex()
check("прогон с цветом 8: кадр белого (10)", white_frame in out, (white_frame, out))

# -- выход ------------------------------------------------------------------- #
os.write(master, b"\x03")
read(1.5)
proc.wait(timeout=5)
check("Ctrl+C: код выхода 0", proc.returncode == 0, proc.returncode)

print()
print("ОШИБОК:", failures)
sys.exit(1 if failures else 0)
