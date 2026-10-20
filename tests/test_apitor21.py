#!/usr/bin/env python3
"""Реверс: точки смены скорости и света.

Скорость и цвет в обратном проезде ставятся там, где они МЕНЯЛИСЬ, а не
перед каждым шагом: реверс начинается со скорости конца маршрута, а на точке
перелома переключается на скорость начала. Свет — так же, и участки, которые
ехали «при том, что горело», закрываются тем цветом, который горел до прогона.
"""
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
WORK = fresh_work("test21")

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


def reversed_text(text, mode="back", base=None, drop_pauses=False):
    steps, repeat, speed, errors = mod.parse_program(text)
    ed = mod.ProgramEditor()
    ed.set_program(steps, repeat, speed)
    return [mod.step_text(s) for s in reversed_steps_ok(ed, mode, base, drop_pauses)], errors


def reversed_steps_ok(ed, mode, base, drop_pauses):
    try:
        return mod.reversed_steps(ed, mode, drop_pauses=drop_pauses, base_light=base)
    except TypeError:                      # совсем старая версия: без base_light
        return mod.reversed_steps(ed, mode, drop_pauses=drop_pauses)


# --------------------------------------------------------------------------- #
# Часть A: точки смены скорости — пример из задания
# --------------------------------------------------------------------------- #
SPEED_PROG = ("скорость 6\nвперёд\nвправо\nвперёд\nвправо\n"
              "скорость 12\nназад\nвперёд\nвперёд\n")
got, errors = reversed_text(SPEED_PROG)
check("пример со скоростями разбирается без ошибок", errors == [], errors)
want = ["»12", "↓0.6с", "↓0.6с", "↑0.6с", "»6", "←0.6с", "↓0.6с", "←0.6с", "↓0.6с"]
check("реверс: начинается со скорости конца маршрута (»12)", got == want, got)
check("реверс: скорость 6 включается на точке перелома и держится до конца",
      got.count("»6") == 1 and got.index("»6") == 4, got)
check("реверс: скорости не повторяются перед каждым шагом", got.count("»12") == 1, got)

got, _ = reversed_text(SPEED_PROG, mode="front")
check("t-реверс (развёрнут рукой): те же точки скорости",
      got == ["»12", "↑0.6с", "↑0.6с", "↓0.6с", "»6",
              "←0.6с", "↑0.6с", "←0.6с", "↑0.6с"], got)

got, _ = reversed_text(SPEED_PROG, drop_pauses=True)
check("без пауз: скорости там же", got == want, got)

# три отрезка: 6 → 12 → 4 → снова 12: меняется только там, где менялось
got, _ = reversed_text("скорость 6\nвперёд\nскорость 12\nвправо\n"
                       "скорость 4\nназад\nскорость 12\nвлево\n")
check("несколько смен: »12, »4, »12, »6 — каждая на своём месте",
      got == ["»12", "→0.6с", "»4", "↑0.6с", "»12", "←0.6с", "»6", "↓0.6с"], got)

# скорость меняли, но не ехали: на реверс не влияет
got, _ = reversed_text("вперёд\nскорость 12\n")
check("смена скорости без движения ничего не добавляет", got == ["↓0.6с"], got)

# --------------------------------------------------------------------------- #
# Часть B: точки смены света — та же логика
# --------------------------------------------------------------------------- #
COLOR_PROG = ("скорость 6\nцвет 3\nвперёд\nвправо\nцвет 5\nвперёд\nвправо\n"
              "цвет 1\nназад\nвперёд\nвперёд\n")
got, errors = reversed_text(COLOR_PROG, base=8)
check("пример со цветами разбирается без ошибок", errors == [], errors)
check("реверс начинается с последнего цвета: ●1, ●5, ●3",
      got == ["●1", "↓0.6с", "↓0.6с", "↑0.6с", "●5", "←0.6с", "↓0.6с",
              "●3", "←0.6с", "↓0.6с"], got)
check("цвета не повторяются перед каждым шагом",
      got.count("●1") == 1 and got.count("●5") == 1 and got.count("●3") == 1, got)

# участки, проеханные «при том, что горело», закрываются цветом до прогона
got, _ = reversed_text("вперёд 2\nцвет 5\nназад 2\n", base=8)
check("бесцветный участок в реверсе получает горевший цвет (●8)",
      got == ["●5", "↑1.2с", "●8", "↓1.2с"], got)
got, _ = reversed_text("вперёд 2\nцвет 5\nназад 2\n", base=0)
check("погашенный свет возвращается как ●0", got == ["●5", "↑1.2с", "●0", "↓1.2с"], got)
got, _ = reversed_text("вперёд 2\nцвет 5\nназад 2\n")
check("если цвет неизвестен, бесцветный участок не трогается",
      got == ["●5", "↑1.2с", "↓1.2с"], got)

# цвет 0 — это «выключить», и он тоже переключается в нужный момент
got, _ = reversed_text("цвет 0\nвперёд\nцвет 4\nназад\n", base=8)
check("цвет 0 — полноценная смена света", got == ["●4", "↑0.6с", "●0", "↓0.6с"], got)

# мигание остаётся миганием и попадает в свой отрезок
got, _ = reversed_text("цвет 2\nвперёд\nмигнуть 2\nцвет 7\nназад\n", base=8)
check("мигание остаётся на своём месте", got == ["●7", "↑0.6с", "●2", "✦2", "↓0.6с"], got)

# --------------------------------------------------------------------------- #
# Часть C: свойство — каждый участок едет столько же и при том же свете
# --------------------------------------------------------------------------- #
def events(steps, header, base):
    out, speed, light = [], header, base
    for s in steps:
        if s.kind == "color":
            light = s.value
            continue
        if s.kind == "speed":
            speed = max(mod.SPEED_MIN, min(mod.SPEED_MAX, s.value))
            continue
        out.append((s.kind, round(mod.ProgramEditor()._step_seconds(s), 3), speed, light))
    return out


WORDS = {"fwd": ["вперёд"], "back": ["назад"], "left": ["влево"],
         "right": ["вправо"], "pause": ["пауза"], "blink": ["мигнуть"]}
import random

random.seed(21)
generated = divergent = 0
for _case in range(300):
    lines, first = [], True
    for _ in range(random.randint(1, 9)):
        roll = random.random()
        if roll < 0.18:
            lines.append(f"цвет {random.choice('012345678')}")
        elif roll < 0.34:
            lines.append(f"скорость {random.randint(3, 12)}" if first
                         else random.choice([f"скорость {random.randint(3, 12)}",
                                             f"»{random.randint(3, 12)}"]))
        else:
            kind = random.choice(list(WORDS))
            count = random.randint(1, 4)
            lines.append(random.choice(WORDS[kind]) + (f" {count}" if count > 1 else ""))
        first = False
    steps, repeat, speed, errors = mod.parse_program("\n".join(lines) + "\n")
    if errors:
        continue
    base = random.choice([0, 3, 8])
    ed = mod.ProgramEditor()
    ed.set_program(steps, repeat, speed)
    for mode, mirror in (("back", mod.REVERSE_MIRROR["back"]),
                         ("front", mod.REVERSE_MIRROR["front"])):
        for drop in (False, True):
            generated += 1
            fwd = events(ed.steps, ed.speed, base)
            rev = events(reversed_steps_ok(ed, mode, base, drop), ed.speed, base)
            want = [(mirror.get(k, k), sec, sp, li) for k, sec, sp, li in reversed(fwd)]
            if drop:
                want = [e for e in want if e[0] != "pause"]
            if rev != want:
                divergent += 1
                if divergent == 1:
                    print("  расхождение:", "\n".join(lines),
                          "\n  вперёд:", fwd, "\n  реверс:", rev, "\n  надо:  ", want)
check(f"свойство: {generated} случайных реверсов — те же отрезки, скорости и свет",
      divergent == 0, f"{divergent} расхождений")

# --------------------------------------------------------------------------- #
# Часть D: живой пульт — кадры в --simulate
# --------------------------------------------------------------------------- #
open(WORK + "/programs/1.txt", "w", encoding="utf-8").write(
    "скорость 6\nцвет 3\nвперёд\nвправо\nцвет 5\nвперёд\nвправо\n"
    "цвет 1\nскорость 12\nназад\nвперёд\nвперёд\n")

KBD = WORK + "/kbd"
os.mkfifo(KBD)

env = dict(os.environ)
env["TERM"] = "xterm-256color"
env["HOME"] = WORK + "/home"
env["EDITOR"] = "true"
master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--no-tui", "--key-state-device", KBD, "--program-dir", WORK + "/programs"],
    stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
)
os.close(slave)
kbd = os.open(KBD, os.O_WRONLY)

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


read(2.0)
take()
key("q")
key("g")
key("1")
out = key("enter", 1.0)
check("программа со скоростями и цветами загружена",
      "загружено: 1.txt" in out and "11 шагов" in out, out)

out = key("r", 0.3) + (read(14.0) or take())
lines = out.splitlines()
seen = [l for l in lines if l.startswith("[run] ▶")]
checks = {
    "реверс начинается с ●1 и »12": seen[:2] == ["[run] ▶ ●1", "[run] ▶ »12"],
    "на точке перелома включается »6": seen.index("[run] ▶ »12") < seen.index("[run] ▶ »6"),
    "цвета идут ●1 → ●5 → ●3": [l for l in seen if l.startswith("[run] ▶ ●")]
                                == ["[run] ▶ ●1", "[run] ▶ ●5", "[run] ▶ ●3"],
}
for name, cond in checks.items():
    check(name, cond, seen[:14])

frames = [l.strip() for l in lines if "[sim] ->" in l]
speed_bytes = [f[-2:] for f in frames
               if f.startswith("[sim] -> 55aa0306") or f.startswith("[sim] -> 55aa0307")]
check("кадры движения: сначала 0c (12), потом 06 (6)",
      speed_bytes[:2] == ["0c", "0c"] and "06" in speed_bytes and speed_bytes.index("06") > 0, speed_bytes[:14])
check("кадры подсветки: ●1 (01), потом ●5 (05), потом ●3 (03)",
      all(any(needle in f for f in frames) for needle in
          ("55aa0404010000", "55aa0404050000", "55aa0404030000")),
      [f for f in frames if f.startswith("[sim] -> 55aa0404")][:8])

os.write(master, b"\x03")
read(1.5)
try:
    proc.wait(timeout=5)
except subprocess.TimeoutExpired:
    proc.kill()

print()
print(f"ОШИБОК: {failures}")
sys.exit(1 if failures else 0)
