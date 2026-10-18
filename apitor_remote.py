#!/usr/bin/env python3
"""apitor_remote.py — пульт с горячими клавишами для Apitor Robot R.

Управляет роботом по Bluetooth LE через библиотеку `apitor-ble`.
Клавиши нажимаются по одной, Enter не нужен:

    q ............ подключиться         Shift+Q ...... отключиться
    w a s d ...... ехать                пробел / Esc . стоп
    ] [  (+ -) ... скорость (1..12)     1..8 ......... цвет подсветки
    0 ............ выключить подсветку
    e / Shift+E .. мотор 3 (аксессуар): вперёд / назад (тумблером)
    p ............ режим программы (шаги, как у Big Trak / Лунохода)
    R ............ в пульте: запустить последнюю программу (если была)
    F / G ........ сохранить / загрузить программу файлом
    J ............ журнал прогонов вкл/выкл
    t ............ тест-поездка (проверить направления)
    i ............ моторы по одному (калибровка)
    l ............ режим: удержание / фиксация
    h, ? ......... справка              Ctrl+C ....... выход

Режим программы: нажмите `p` — набирайте шаги (w/a/s/d — вперёд/назад/
влево/вправо, пробел — пауза, c — цвет, b — мигнуть, цифры — число шага),
Enter — запуск. Программа пишется живой строкой; f/g — сохранить/загрузить.
Esc — вернуться в пульт (программа остаётся), x — очистить программу,
E — правка во внешнем редакторе ($EDITOR/$VISUAL, иначе nvim/nano/vi;
на время редактора горячие клавиши пульта выключены).
Файлы простые: «вперёд 5», «вправо 2», понимаются и по-русски, и по-английски.

Язык интерфейса: --lang en (один раз, запоминается в config.json) или --lang ru.
Настройки (длительности шагов, журнал и т. п.) — в
~/.config/apitor-control/config.json, примеры есть в README.

Режим по умолчанию — "удержание": движок крутится, пока клавиша повторяется
(автоповтор операционной системы), и робот сам останавливается через
--hold-timeout секунд после отпускания. Клавиша `l` включает "фиксацию":
робот едет, пока не нажмёте стоп/другое.

С флагом --key-state удержание работает "как в играх": пульт читает реальное
состояние клавиш (Linux: evdev, Windows: WinAPI) и останавливает робота
в момент отпускания; автоповтор и таймаут не нужны.

Примеры:

    .venv/bin/python apitor_remote.py                # Robot R, скорость 6
    .venv/bin/python apitor_remote.py --speed 9      # быстрее
    .venv/bin/python apitor_remote.py --simulate     # без Bluetooth: печать кадров
    .venv/bin/python apitor_remote.py --key-state    # стоп в момент отпускания клавиши
    .venv/bin/python apitor_remote.py --address AA:BB:CC:DD:EE:FF
    .venv/bin/python apitor_remote.py --program ~/.config/apitor-control/programs/квадрат.txt
    .venv/bin/python apitor_remote.py --lang en       # английский интерфейс (запомнится)

Если робот едет наоборот или разворачивается не туда, откалибруйте сборку
флагами --flip-left, --flip-right, --left-motor N, --right-motor N
(подробности — в README.md).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from bleak import BleakScanner

from apitor_ble import protocol as p
from apitor_ble.exceptions import DiscoveryError
from apitor_ble.profiles import drive_directions, get_profile, motor_from_number
from apitor_ble.protocol import Color, Direction, Motor
from apitor_ble.robot import ApitorRobot
from apitor_ble.sensor import SensorFrame

if os.name == "posix":
    import select
    import termios

# --------------------------------------------------------------------------- #
# Настройки по умолчанию
# --------------------------------------------------------------------------- #

SPEED_MIN, SPEED_MAX = 1, 12
DEFAULT_SPEED = 6
DEFAULT_HOLD_TIMEOUT = 0.8
CACHE_PATH = Path.home() / ".config" / "apitor-control" / "addresses.json"
CONFIG_PATH = Path.home() / ".config" / "apitor-control" / "config.json"
JOURNAL_PATH = Path.home() / ".config" / "apitor-control" / "runs.log"
DEFAULT_PROGRAM_DIR = Path.home() / ".config" / "apitor-control" / "programs"
DRAFT_FILE = "_draft.txt"

# Длительности шагов программы по умолчанию (меняются в config.json).
DEFAULT_STEP_TIME = 0.6   # вперёд/назад, за «шаг»
DEFAULT_TURN_TIME = 0.6   # влево/вправо (поворот на месте)
DEFAULT_PAUSE_TIME = 1.0  # пауза
DEFAULT_BLINK_TIME = 0.25  # половина цикла «мигнуть»

IS_WINDOWS = os.name == "nt"

# --------------------------------------------------------------------------- #
# Язык интерфейса
# --------------------------------------------------------------------------- #

LANG = "ru"  # ru по умолчанию; --lang en переключает (и запоминается в config)


def tr(ru: str, en: str) -> str:
    """Строка интерфейса на текущем языке."""
    return en if LANG == "en" else ru


def steps_word(n: int) -> str:
    """«шаг»/«шага»/«шагов» (или step/steps)."""
    if LANG == "en":
        return "step" if n % 10 == 1 and n % 100 != 11 else "steps"
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return "шаг"
    if n10 in (2, 3, 4) and n100 not in (12, 13, 14):
        return "шага"
    return "шагов"


def load_config() -> dict:
    """Прочитать config.json (или пустой словарь)."""
    try:
        data = json.loads(CONFIG_PATH.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(data: dict) -> None:
    with contextlib.suppress(Exception):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8"
        )

# --------------------------------------------------------------------------- #
# Клавиши
# --------------------------------------------------------------------------- #

# Движение: имя -> (левое колесо вперёд?, правое колесо вперёд?).
MOVE_VECTORS = {
    "fwd": (True, True),
    "back": (False, False),
    "left": (False, True),  # разворот на месте влево
    "right": (True, False),  # разворот на месте вправо
}
MOVE_LABELS = {
    "fwd": "вперёд",
    "back": "назад",
    "left": "поворот влево (на месте)",
    "right": "поворот вправо (на месте)",
}
MOVE_LABELS_EN = {
    "fwd": "forward",
    "back": "back",
    "left": "turn left (in place)",
    "right": "turn right (in place)",
}


def move_label(move: str) -> str:
    return (MOVE_LABELS_EN if LANG == "en" else MOVE_LABELS)[move]


COLOR_BY_KEY = {
    "1": (Color.RED, "красный", "red"),
    "2": (Color.ORANGE, "оранжевый", "orange"),
    "3": (Color.YELLOW, "жёлтый", "yellow"),
    "4": (Color.GREEN, "зелёный", "green"),
    "5": (Color.CYAN, "голубой", "cyan"),
    "6": (Color.BLUE, "синий", "blue"),
    "7": (Color.PURPLE, "фиолетовый", "purple"),
    "8": (Color.WHITE, "белый", "white"),
}

# Символ -> действие. Стрелки приходят как "up"/"down"/"left"/"right".
KEYMAP: dict[str, str] = {
    "q": "connect",
    "Q": "disconnect",  # Shift+Q
    "w": "fwd", "s": "back", "a": "left", "d": "right",
    "up": "fwd", "down": "back", "left": "left", "right": "right",
    " ": "stop", "esc": "stop", "enter": "stop",
    "]": "speed_up", "=": "speed_up", "+": "speed_up",
    "[": "speed_down", "-": "speed_down", "_": "speed_down",
    "0": "lights_off",
    "e": "m3_fwd", "E": "m3_rev",
    "p": "prog", "P": "prog",
    "r": "run_last", "R": "run_last",
    "f": "save_prog", "F": "save_prog",
    "g": "load_prog", "G": "load_prog",
    "j": "journal", "J": "journal",
    "x": "clear_prog", "X": "clear_prog",
    "t": "test", "i": "identify", "l": "latch", "h": "help", "?": "help",
    "\x03": "quit",  # Ctrl+C (терминал в "сыром" режиме)
}
KEYMAP.update({key: f"color:{key}" for key in COLOR_BY_KEY})

# Русская раскладка: те же физические клавиши приходят кириллицей.
_LAYOUT = {
    "й": "q", "ц": "w", "у": "e", "ф": "a", "ы": "s", "в": "d", "е": "t",
    "р": "h", "д": "l", "о": "j", "ш": "i", "к": "r", "а": "f", "п": "g",
    "с": "c", "и": "b", "ч": "x", "з": "p",
    "х": "[", "ъ": "]",
    "Й": "Q", "Ц": "W", "У": "E", "Ф": "A", "Ы": "S", "В": "D", "Е": "T",
    "Р": "H", "Д": "L", "О": "J", "Ш": "I", "К": "R", "А": "F", "П": "G",
    "С": "C", "И": "B", "Ч": "X", "З": "P",
    "Х": "[", "Ъ": "]",
}


def _to_latin_layout(char: str) -> str:
    """Перевести кириллическую букву в ту же физическую клавишу QWERTY."""
    return _LAYOUT.get(char, char)


# --------------------------------------------------------------------------- #
# Программа (как у Big Trak / «Электроники ИМ-11»)
# --------------------------------------------------------------------------- #

# Шаг программы: вид + число.
#   fwd/back/left/right — сколько «шагов» ехать (1..99)
#   pause  — сколько пауз (1..99)
#   blink  — сколько раз мигнуть (1..99)
#   color  — цвет 0..8 (0 — выключить)
COUNT_KINDS = ("fwd", "back", "left", "right", "pause", "blink")

_STEP_WORDS = {
    "fwd": {"ru": "вперёд", "en": "forward"},
    "back": {"ru": "назад", "en": "back"},
    "left": {"ru": "влево", "en": "left"},
    "right": {"ru": "вправо", "en": "right"},
    "pause": {"ru": "пауза", "en": "pause"},
    "color": {"ru": "цвет", "en": "color"},
    "blink": {"ru": "мигнуть", "en": "blink"},
}

# Прощающий парсер: команды на русском и английском (можно вперемешку).
_STEP_SYNONYMS = {
    "вперёд": "fwd", "вперед": "fwd", "forward": "fwd", "forwards": "fwd", "ahead": "fwd",
    "назад": "back", "back": "back", "backward": "back", "backwards": "back",
    "влево": "left", "left": "left",
    "вправо": "right", "right": "right",
    "пауза": "pause", "pause": "pause", "wait": "pause",
    "цвет": "color", "color": "color", "colour": "color",
    "мигнуть": "blink", "blink": "blink", "flash": "blink",
}
_HEADER_SYNONYMS = {
    "повтор": "repeat", "repeat": "repeat",
    "скорость": "speed", "speed": "speed",
}


class Step:
    """Шаг программы (обычный класс: тесты грузят модуль через importlib)."""
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: int = 1) -> None:
        self.kind = kind
        self.value = value


def step_text(step: Step) -> str:
    """Шаг словами: «вперёд 5», «пауза», «цвет 3»."""
    word = _STEP_WORDS[step.kind][LANG]
    if step.kind == "color" or step.value != 1:
        return f"{word} {step.value}"
    return word


class EditorResult:
    """Ответ редактора на клавишу: что напечатать или что сделать."""
    __slots__ = ("action", "text")

    def __init__(self, action: str, text: str = "") -> None:
        self.action = action  # line | note | warn | run | save | load | remote
        self.text = text


class _RunAbort(Exception):
    """Программа прервана (Esc — в пульт, p — в режим программы, отключение или потеря связи)."""


class ProgramEditor:
    """Набор шагов программы: клавиши редактора и живая строка."""

    DIGIT_GAP = 1.0       # цифры, набранные подряд, — одно число
    CAPTURE_WINDOW = 1.5  # окно после c/r/клавиш скорости для «постфикса»

    def __init__(self, *, step_time=DEFAULT_STEP_TIME, turn_time=DEFAULT_TURN_TIME,
                 pause_time=DEFAULT_PAUSE_TIME, blink_time=DEFAULT_BLINK_TIME,
                 max_steps=0, speed=DEFAULT_SPEED) -> None:
        self.step_time = step_time
        self.turn_time = turn_time
        self.pause_time = pause_time
        self.blink_time = blink_time
        self.max_steps = max(0, int(max_steps))
        self.speed = max(SPEED_MIN, min(SPEED_MAX, int(speed)))
        self.steps: list[Step] = []
        self.repeat = 1
        self._digit_run = ""
        self._last_digit = 0.0
        self._capture: str | None = None  # speed | repeat | color
        self._capture_deadline = 0.0
        self._capture_digits = ""

    # -- состояние ----------------------------------------------------------- #
    def is_empty(self) -> bool:
        return not self.steps

    def clear(self) -> None:
        self.steps.clear()
        self.repeat = 1
        self._capture = None
        self._digit_run = ""

    def set_program(self, steps: list[Step], repeat: int, speed: int | None) -> None:
        self.steps = [Step(s.kind, s.value) for s in steps]
        self.repeat = max(1, min(99, int(repeat or 1)))
        if speed is not None:
            self.speed = max(SPEED_MIN, min(SPEED_MAX, int(speed)))
        self._capture = None
        self._digit_run = ""

    def _step_seconds(self, step: Step) -> float:
        if step.kind in ("fwd", "back"):
            return step.value * self.step_time
        if step.kind in ("left", "right"):
            return step.value * self.turn_time
        if step.kind == "pause":
            return step.value * self.pause_time
        if step.kind == "blink":
            return step.value * 2.0 * self.blink_time
        return 0.0

    def estimate(self) -> float:
        return sum(self._step_seconds(s) for s in self.steps) * self.repeat

    # -- живая строка -------------------------------------------------------- #
    def line(self) -> str:
        if not self.steps:
            return tr(
                "(пусто) — w/a/s/d — шаги, Enter — запуск, Esc — пульт, h — справка",
                "(empty) — w/a/s/d — steps, Enter — run, Esc — remote, h — help",
            )
        words = [step_text(s) for s in self.steps]
        if len(words) > 8:
            words = [f"…+{len(words) - 8}"] + words[-8:]
        n = len(self.steps)
        count = f"{n}/{self.max_steps} {steps_word(n)}" if self.max_steps else f"{n} {steps_word(n)}"
        status = f"{count} · ~{self.estimate():.1f} {tr('с', 's')} · {tr('скор.', 'speed')} {self.speed}"
        if self.repeat > 1:
            status += f" · {tr('повтор', 'repeat')} {self.repeat}"
        return " · ".join(words) + f" ({status})"

    def serialize(self) -> str:
        """Файл программы: просто и без лишних знаков («вперёд 5»)."""
        lines: list[str] = []
        if self.repeat > 1:
            lines.append(f"{tr('повтор', 'repeat')} {self.repeat}")
        lines.append(f"{tr('скорость', 'speed')} {self.speed}")
        for step in self.steps:
            word = _STEP_WORDS[step.kind][LANG]
            if step.kind == "color" or step.value != 1:
                lines.append(f"{word} {step.value}")
            else:
                lines.append(word)
        return "\n".join(lines) + "\n"

    # -- правка -------------------------------------------------------------- #
    def _warn_if_full(self) -> EditorResult | None:
        if self.max_steps and len(self.steps) >= self.max_steps:
            return EditorResult("warn", tr(
                f"лимит {self.max_steps} команд — больше нельзя (--max-steps)",
                f"limit of {self.max_steps} steps reached (--max-steps)",
            ))
        return None

    def _arm(self, capture: str, now: float) -> None:
        self._capture = capture
        self._capture_deadline = now + self.CAPTURE_WINDOW
        self._capture_digits = ""

    def _speed(self, delta: int, now: float) -> EditorResult:
        self.speed = max(SPEED_MIN, min(SPEED_MAX, self.speed + delta))
        self._arm("speed", now)
        return EditorResult("line", self.line())

    def _digit(self, digit: str, now: float) -> EditorResult:
        if self._capture and now > self._capture_deadline:
            self._capture = None
        if self._capture == "speed":
            self._capture_digits += digit
            self._capture_deadline = now + self.CAPTURE_WINDOW
            value = int(self._capture_digits)
            if value:
                self.speed = min(SPEED_MAX, value)
            return EditorResult("line", self.line())
        if self._capture == "repeat":
            self._capture_digits += digit
            self._capture_deadline = now + self.CAPTURE_WINDOW
            value = int(self._capture_digits)
            if value:
                self.repeat = min(99, value)
            return EditorResult("line", self.line())
        if self._capture == "color":
            value = int(digit)
            if 0 <= value <= 8:
                self.steps[-1].value = value
            self._capture = None
            return EditorResult("line", self.line())
        # обычный цифровой постфикс: число последнего шага (0 = 10)
        if now - self._last_digit > self.DIGIT_GAP:
            self._digit_run = ""
        self._last_digit = now
        self._digit_run += digit
        value = 10 if self._digit_run == "0" else int(self._digit_run)
        while value > 99 and len(self._digit_run) > 1:
            self._digit_run = self._digit_run[:-1]
            value = int(self._digit_run)
        if not self.steps or self.steps[-1].kind not in COUNT_KINDS:
            self._digit_run = ""
            return EditorResult("warn", tr(
                "число — к последнему шагу; добавьте шаг (w/a/s/d, пробел, b) "
                "или наберите c и цифру цвета",
                "a number applies to the last step; add one (w/a/s/d, space, b) "
                "or use c + color digit",
            ))
        self.steps[-1].value = max(1, min(99, value))
        return EditorResult("line", self.line())

    def _add_step(self, kind: str, now: float) -> EditorResult:
        if self.steps and self.steps[-1].kind == kind:
            self.steps[-1].value = min(99, self.steps[-1].value + 1)
            return EditorResult("line", self.line())
        full = self._warn_if_full()
        if full is not None:
            return full
        self.steps.append(Step(kind, 1))
        return EditorResult("line", self.line())

    def _add_color(self, now: float) -> EditorResult:
        if self.steps and self.steps[-1].kind == "color":
            last = self.steps[-1]
            last.value = 0 if last.value >= 8 else last.value + 1
        else:
            full = self._warn_if_full()
            if full is not None:
                return full
            self.steps.append(Step("color", 1))
        self._arm("color", now)
        return EditorResult("line", self.line())

    def key(self, key: str, now: float) -> EditorResult | None:
        """Клавиша редактора; None — клавиша редактору не принадлежит."""
        if len(key) == 1 and key.isdigit():
            return self._digit(key, now)
        self._capture = None
        if key in ("w", "up"):
            return self._add_step("fwd", now)
        if key in ("s", "down"):
            return self._add_step("back", now)
        if key in ("a", "left"):
            return self._add_step("left", now)
        if key in ("d", "right"):
            return self._add_step("right", now)
        if key == " ":
            return self._add_step("pause", now)
        if key == "b":
            return self._add_step("blink", now)
        if key == "c":
            return self._add_color(now)
        if key in ("]", "+", "="):
            return self._speed(+1, now)
        if key in ("[", "-", "_"):
            return self._speed(-1, now)
        if key == "r":
            self.repeat = 1 if self.repeat >= 99 else self.repeat + 1
            self._arm("repeat", now)
            return EditorResult("line", self.line())
        if key == "backspace":
            if self.steps:
                self.steps.pop()
            return EditorResult("line", self.line())
        if key == "esc":
            return EditorResult("remote")
        if key == "enter":
            return EditorResult("run")
        if key == "f":
            return EditorResult("save")
        if key == "g":
            return EditorResult("load")
        return None


def parse_program(text: str, max_steps: int = 0):
    """Прощающий парсер файла: (шаги, повтор, скорость, ошибки).

    Понимает русский и английский, е/ё, регистр, «× x *», запятые;
    «#» — комментарий. Ошибки — строки с номером строки.
    """
    steps: list[Step] = []
    repeat = 1
    speed: int | None = None
    errors: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if lineno == 1:
            raw = raw.lstrip("\ufeff")
        line = raw.split("#", 1)[0].lower().replace("ё", "е")
        line = line.replace("×", " ").replace("*", " ").replace(",", " ")
        line = re.sub(r"x(?=\d)", " ", line)  # «вперёд x5» == «вперёд 5»
        tokens = re.findall(r"[а-яa-z]+|\d+", line)
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.isdigit():
                errors.append(tr(f"строка {lineno}: число {tok} без команды",
                                 f"line {lineno}: number {tok} without a command"))
                i += 1
                continue
            kind = _STEP_SYNONYMS.get(tok)
            header = _HEADER_SYNONYMS.get(tok)
            number: int | None = None
            if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                number = int(tokens[i + 1])
                i += 1
            i += 1
            if header == "repeat":
                if number is None or not 1 <= number <= 99:
                    errors.append(tr(f"строка {lineno}: «{tok}» требует число 1..99",
                                     f"line {lineno}: «{tok}» needs a number 1..99"))
                else:
                    repeat = number
                continue
            if header == "speed":
                if number is None or not 1 <= number <= SPEED_MAX:
                    errors.append(tr(f"строка {lineno}: «{tok}» требует число 1..{SPEED_MAX}",
                                     f"line {lineno}: «{tok}» needs a number 1..{SPEED_MAX}"))
                else:
                    speed = number
                continue
            if kind is None:
                errors.append(tr(f"строка {lineno}: не понимаю «{tok}»",
                                 f"line {lineno}: don't understand «{tok}»"))
                continue
            if kind == "color":
                if number is None or not 0 <= number <= 8:
                    errors.append(tr(f"строка {lineno}: «{tok}» требует число 0..8",
                                     f"line {lineno}: «{tok}» needs a number 0..8"))
                    continue
            else:
                if number is None:
                    number = 1
                if not 1 <= number <= 99:
                    errors.append(tr(f"строка {lineno}: «{tok} {number}» — допустимо 1..99",
                                     f"line {lineno}: «{tok} {number}» — allowed 1..99"))
                    continue
            steps.append(Step(kind, number))
    if max_steps and len(steps) > max_steps:
        errors.append(tr(
            f"в программе {len(steps)} команд, а лимит {max_steps} (--max-steps)",
            f"the program has {len(steps)} steps, limit is {max_steps} (--max-steps)",
        ))
    return steps, repeat, speed, errors


# --------------------------------------------------------------------------- #
# Чтение клавиш (по одной, без Enter)
# --------------------------------------------------------------------------- #

_ARROWS_FINAL = {b"A": "up", b"B": "down", b"C": "right", b"D": "left"}


def _read_byte_timeout(fd: int, timeout: float) -> bytes | None:
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return None
    return os.read(fd, 1)


def _read_utf8_tail(fd: int, first: bytes) -> bytes:
    """Дочитать многобайтовый UTF-8 символ (кириллица) до конца."""
    lead = first[0]
    if 0xC0 <= lead < 0xE0:
        need = 1
    elif 0xE0 <= lead < 0xF0:
        need = 2
    elif 0xF0 <= lead < 0xF8:
        need = 3
    else:
        need = 0
    buf = bytearray(first)
    while need > 0:
        char = os.read(fd, 1)
        if not char:
            break
        buf += char
        need -= 1
    return bytes(buf)


def read_key_posix(fd: int) -> str | None:
    """Прочитать одно нажатие; None — неинтересная последовательность.

    Служебные клавиши приходят токенами («esc», «enter», «backspace»,
    «up»/«down»/«left»/«right»); остальное — «сырой» символ (раскладку
    переводит главный цикл, чтобы текстовые подсказки читали кириллицу как есть).
    """
    first = os.read(fd, 1)
    if not first:
        return "quit"  # поток ввода закрыт
    if first == b"\x1b":
        nxt = _read_byte_timeout(fd, 0.08)
        if nxt is None:
            return "esc"  # одиночный Esc
        if nxt not in (b"[", b"O"):
            return None  # Alt+клавиша и т. п.
        seq = b""
        while True:
            more = _read_byte_timeout(fd, 0.08)
            if more is None:
                break
            seq += more
            if more.isalpha() or more == b"~":
                break
        return _ARROWS_FINAL.get(seq[-1:])
    if first in (b"\r", b"\n"):
        return "enter"
    if first in (b"\x7f", b"\x08"):
        return "backspace"
    if first[0] >= 0x80:
        first = _read_utf8_tail(fd, first)
    return first.decode("utf-8", "replace")

# --------------------------------------------------------------------------- #
# Заглушка робота для --simulate
# --------------------------------------------------------------------------- #


class SimRobot:
    """Печатает кадры, которые отправила бы библиотека, вместо Bluetooth."""

    def __init__(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def address(self) -> str:
        return "SIM"

    def on_sensor(self, callback) -> None:  # совместимость с ApitorRobot
        pass

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def _send(self, data: bytes) -> None:
        print(f"  [sim] -> {data.hex()}", flush=True)

    async def run_motor(self, motor, direction, speed: int) -> None:
        await self._send(p.motor_command(int(motor), int(direction), int(speed)))

    async def stop_motor(self, motor) -> None:
        await self.run_motor(motor, Direction.STOP, 0)

    async def stop_all_motors(self) -> None:
        await self._send(p.stop_all_command())

    async def all_leds(self, color) -> None:
        await self._send(p.led_command(4, int(color)))


# --------------------------------------------------------------------------- #
# Терминал: одноклавишный ввод
# --------------------------------------------------------------------------- #


class RawTerminal:
    """"Сырой" режим терминала на время работы пульта (на Windows — no-op)."""

    def __enter__(self) -> RawTerminal:
        self._saved = None
        if IS_WINDOWS:
            with contextlib.suppress(Exception):
                import msvcrt

                while msvcrt.kbhit():  # выбросить нажатия, сделанные до запуска
                    msvcrt.getwch()
            return self
        fd = sys.stdin.fileno()
        self._fd = fd
        self._saved = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        # Не мешать выводу (OPOST оставляем), но убрать эхо, канонический режим,
        # сигналы (Ctrl+C придёт как символ) и управление потоком.
        new[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP | termios.IXON)
        new[2] &= ~(termios.CSIZE | termios.PARENB)
        new[2] |= termios.CS8
        new[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG)
        new[6][termios.VMIN] = 1
        new[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSADRAIN, new)
        termios.tcflush(fd, termios.TCIFLUSH)
        return self

    def __exit__(self, *exc) -> None:
        if not IS_WINDOWS and self._saved is not None:
            with contextlib.suppress(Exception):
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)


async def _scan_once(product: str, timeout: float) -> list:
    """Одно сканирование без фильтра по service UUID (он ломается на BlueZ 5.87).

    Возвращает список найденных устройств без ожидания полного таймаута,
    как только найден подходящий робот.
    """
    found: dict = {}
    done = asyncio.Event()

    def on_advert(device, advertisement_data) -> None:
        if p.device_name_matches(device.name, product):
            found.setdefault(device.address, device)
            done.set()

    scanner = BleakScanner(detection_callback=on_advert)
    await scanner.start()
    try:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(done.wait(), timeout=timeout)
    finally:
        with contextlib.suppress(Exception):
            await scanner.stop()
    return list(found.values())


# --------------------------------------------------------------------------- #
# Пульт
# --------------------------------------------------------------------------- #


class Remote:
    """Состояние пульта: подключение, движение, свет, режим и обработка клавиш."""

    CONNECT_TIMEOUT = 8.0  # сколько ждать прямой коннект по известному адресу
    SEND_DEBOUNCE = 0.06  # антидребезг команд движения, с

    def __init__(self, args: argparse.Namespace, profile, config: dict | None = None) -> None:
        cfg = config or {}
        self.product = profile.product
        self.profile = profile
        self.speed = max(SPEED_MIN, min(SPEED_MAX, args.speed))
        self.hold_timeout = max(0.1, args.hold_timeout)
        self.latched = bool(args.latched)
        self.sim = bool(args.simulate)
        self.use_cache = not args.no_cache
        self.scan_timeout = max(2.0, args.scan_timeout)
        self.cli_address = (args.address or "").strip() or None
        self.verbose = bool(args.verbose)
        self.want_key_state = bool(getattr(args, "key_state", False))

        # Настройки программы: флаг > config.json > значение по умолчанию.
        def number(flag_name: str, key: str, default: float, minimum: float) -> float:
            value = getattr(args, flag_name, None)
            if value is None:
                value = cfg.get(key, default)
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = default
            return max(minimum, value)

        self.step_time = number("step_time", "step_time", DEFAULT_STEP_TIME, 0.05)
        self.turn_time = number("turn_time", "turn_time", DEFAULT_TURN_TIME, 0.05)
        self.pause_time = number("pause_time", "pause_time", DEFAULT_PAUSE_TIME, 0.05)
        self.blink_time = number("blink_time", "blink_time", DEFAULT_BLINK_TIME, 0.05)
        max_steps = getattr(args, "max_steps", None)
        if max_steps is None:
            max_steps = cfg.get("max_steps", 0)
        try:
            max_steps = int(max_steps)
        except (TypeError, ValueError):
            max_steps = 0
        self.max_steps = max(0, max_steps)
        self.autosave = bool(cfg.get("autosave", True))
        log_flag = getattr(args, "log", None)
        self.journal = bool(cfg.get("journal", False)) if log_flag is None else bool(log_flag)
        program_dir = getattr(args, "program_dir", None) or cfg.get("program_dir")
        self.program_dir = Path(program_dir).expanduser() if program_dir else DEFAULT_PROGRAM_DIR
        self.journal_path = JOURNAL_PATH

        self.robot = None
        self.move = "stop"
        self.m3_dir: Direction | None = None
        self.last_input = 0.0
        self.low_power_warned = False
        self.key_state = False            # --key-state: слежение за клавишами работает
        self.key_state_devices = [        # --key-state-device: слушать только эти пути
            str(p) for p in (getattr(args, "key_state_device", None) or [])
        ]
        self._held_moves: list[str] = []  # зажатые сейчас направления (key-state)
        self._keys_backend = None

        # Режимы: remote — пульт, editor — редактор программы, run — выполнение.
        self.mode = "remote"
        self.prompt: dict | None = None   # ввод имени файла / выбор из списка
        self.led_color = Color.WHITE      # какой цвет стоит сейчас (для мигания)
        self.program_name: str | None = None
        self._draft_loaded = False
        self.editor = ProgramEditor(
            step_time=self.step_time, turn_time=self.turn_time,
            pause_time=self.pause_time, blink_time=self.blink_time,
            max_steps=self.max_steps, speed=self.speed,
        )
        self._run_task: asyncio.Task | None = None
        self._run_paused = False
        self._run_abort: str | None = None  # remote | editor
        self._run_step = 0
        self._run_total = 0
        self._external_editor = threading.Event()  # внешний редактор владеет клавиатурой
        self._reader_paused = threading.Event()    # поток ввода подтвердил паузу
        self._termios_original = None              # терминал до "сырого" режима
        self._pending_output: list[tuple[str, str]] = []  # вывод, отложенный на время редактора

        self.keys: asyncio.Queue = asyncio.Queue()
        self._connect_task: asyncio.Task | None = None
        self._send_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- вывод --------------------------------------------------------------- #
    def _emit(self, text: str, end: str = "\n") -> None:
        """Печать; во время внешнего редактора сообщения копятся и не мешают."""
        if self._external_editor.is_set():
            self._pending_output.append((text, end))
            return
        try:
            print(text, end=end, flush=True)
        except UnicodeEncodeError:  # старые консоли Windows
            print(text.encode("ascii", "replace").decode("ascii"), end=end, flush=True)

    def _flush_pending_output(self) -> None:
        pending, self._pending_output = self._pending_output, []
        for text, end in pending:
            try:
                print(text, end=end, flush=True)
            except UnicodeEncodeError:
                print(text.encode("ascii", "replace").decode("ascii"), end=end, flush=True)

    def _out(self, text: str, end: str = "\n") -> None:
        """Печать без [тега] (строки приглашений, эхо ввода)."""
        self._emit(text, end=end)

    def _say(self, tag: str, message: str) -> None:
        self._emit(f"[{tag}] {message}")

    def _dbg(self, message: str) -> None:
        if self.verbose:
            print(f"[dbg] {message}", file=sys.stderr, flush=True)

    # -- очередь клавиш ------------------------------------------------------ #
    def _put(self, item) -> None:
        if self._loop is None or self._loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):
            self._loop.call_soon_threadsafe(self.keys.put_nowait, item)

    def _queue_event(self, name: str, payload: str) -> None:
        self._put(("event", name, payload))

    def _drain_keys(self) -> None:
        """Выбросить нажатия, сделанные во время долгой операции (но не выход)."""
        quit_seen = False
        while not self.keys.empty():
            item = self.keys.get_nowait()
            if item == "quit":
                quit_seen = True
        if quit_seen:
            self.keys.put_nowait("quit")

    # -- состояние ----------------------------------------------------------- #
    def _is_connected(self) -> bool:
        return self.robot is not None and self.robot.is_connected

    def _is_connecting(self) -> bool:
        return self._connect_task is not None and not self._connect_task.done()

    def _connection_lost(self, exc: BaseException) -> None:
        if self.robot is None:
            return
        self.robot = None
        self.move = "stop"
        self.m3_dir = None
        self._say("err", tr(
            f"потеряна связь с роботом ({exc}) — нажмите q, чтобы подключиться снова",
            f"lost connection to the robot ({exc}) — press q to reconnect",
        ))

    async def _call(self, fn, *args) -> bool:
        """Вызвать метод робота, переживая разрыв связи."""
        try:
            await fn(*args)
            return True
        except Exception as exc:  # noqa: BLE001 — робот может отключиться в любой момент
            self._dbg(f"вызов робота не удался: {exc!r}")
            self._connection_lost(exc)
            return False

    # -- кэш адреса ---------------------------------------------------------- #
    def _cache_read(self) -> str | None:
        if not self.use_cache:
            return None
        try:
            data = json.loads(CACHE_PATH.read_text("utf-8"))
            address = data.get(self.product)
            return address if isinstance(address, str) and address else None
        except Exception:
            return None

    def _cache_write(self, address: str | None) -> None:
        if not self.use_cache or not address:
            return
        try:
            data = {}
            if CACHE_PATH.exists():
                with contextlib.suppress(Exception):
                    data = json.loads(CACHE_PATH.read_text("utf-8"))
            data[self.product] = address
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        except Exception as exc:
            self._dbg(f"не смог записать кэш адреса: {exc!r}")

    def _cache_forget(self) -> None:
        if not self.use_cache:
            return
        with contextlib.suppress(Exception):
            data = json.loads(CACHE_PATH.read_text("utf-8"))
            data.pop(self.product, None)
            CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

    # -- подключение --------------------------------------------------------- #
    async def _on_connect_key(self) -> None:
        if self._is_connected():
            self._say("warn", tr("уже подключено (Shift+Q — отключиться)",
                                 "already connected (Shift+Q to disconnect)"))
            return
        if self._is_connecting():
            self._say("warn", tr("подключение уже идёт, подождите...",
                                 "connection in progress, please wait..."))
            return
        if self.sim:
            self._say("robot", tr("подключаюсь (режим --simulate, без Bluetooth)...",
                                  "connecting (--simulate mode, no Bluetooth)..."))
        else:
            self._say("robot", tr("ищу робота (включён и не занят телефоном?)...",
                                  "looking for the robot (powered on and not connected to a phone?)..."))
        self._connect_task = asyncio.create_task(self._connect_worker())

    async def _connect_worker(self) -> None:
        try:
            if self.sim:
                robot = SimRobot()
                await robot.connect()
                self.robot = robot
                self._queue_event("connected", robot.address)
                return

            # 1) Быстрый путь: известный адрес (--address или кэш последнего).
            promised = self.cli_address
            from_cache = False
            if not promised:
                promised = self._cache_read()
                from_cache = promised is not None
            if promised:
                self._say("robot", tr(f"пробую подключиться к {promised}...",
                                      f"trying to connect to {promised}..."))
                try:
                    await self._connect_to(promised, timeout=self.CONNECT_TIMEOUT)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._dbg(f"прямой коннект не удался: {exc!r}")
                    if from_cache:
                        self._cache_forget()
                    self._say("warn", tr("адрес не ответил — ищу заново...",
                                         "the address did not answer — scanning again..."))

            # 2) Поиск в эфире (своё сканирование, без фильтра по UUID).
            self._say("robot", tr(f"сканирую Bluetooth ~{self.scan_timeout:.0f} с...",
                                  f"scanning Bluetooth for ~{self.scan_timeout:.0f} s..."))
            address, name = await self._scan_for_robot()
            self._say("robot", tr(f"нашёл {name} ({address}), подключаюсь...",
                                  f"found {name} ({address}), connecting..."))
            if promised and address != promised:
                where = tr("был в кэше", "was in the cache") if from_cache else \
                    tr("указан в --address", "given in --address")
                self._say("warn", tr(
                    f"внимание: это ДРУГОЙ робот — не тот, что {where} ({promised})",
                    f"warning: this is a DIFFERENT robot — not the one that {where} ({promised})",
                ))
                self._say("warn", tr(
                    "подключаюсь к нему; кэш будет обновлён "
                    "(вернуть прежнего: включить только его и снова нажать q)",
                    "connecting to it anyway; the cache will be updated "
                    "(to return to the previous one: power only it on and press q again)",
                ))
            elif not promised and self.use_cache:
                self._say("info", tr("кэш был пуст — адрес этого робота будет запомнен",
                                     "the cache was empty — this robot's address will be remembered"))
            await self._connect_to(address, timeout=self.CONNECT_TIMEOUT)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._queue_event("connect_failed", str(exc))

    async def _scan_for_robot(self) -> tuple[str, str]:
        deadline = time.monotonic() + self.scan_timeout
        last_error: Exception | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.2:
                break
            try:
                found = await _scan_once(self.product, min(remaining, 6.0))
            except Exception as exc:  # BlueZ иногда отвечает InProgress и т. п.
                last_error = exc
                self._dbg(f"ошибка сканирования: {exc!r}")
                found = []
            if found:
                device = found[0]
                return device.address, device.name or self.profile.name
        if last_error is not None:
            raise DiscoveryError(tr(f"не удалось просканировать эфир: {last_error}",
                                    f"could not scan the air: {last_error}"))
        raise DiscoveryError(tr("робот не найден — проверьте, что он включён и не подключён к телефону",
                                "robot not found — check that it is powered on and not connected to a phone"))

    async def _connect_to(self, address: str, *, timeout: float) -> None:
        robot = ApitorRobot(address=address, product=self.product)
        robot.on_sensor(self._on_sensor)
        try:
            await asyncio.wait_for(robot.connect(), timeout=timeout)
        except BaseException:
            with contextlib.suppress(Exception):
                await robot.disconnect()
            raise
        self.robot = robot
        self.low_power_warned = False
        self._cache_write(robot.address or address)
        self._queue_event("connected", robot.address or address)

    def _on_sensor(self, frame: SensorFrame) -> None:
        if frame.low_power and not self.low_power_warned:
            self.low_power_warned = True
            self._say("warn", "у робота низкий заряд батареи — скоро нужно зарядить")

    async def _on_disconnect_key(self) -> None:
        if self._connect_task is not None and not self._connect_task.done():
            self._say("warn", tr("подключение ещё идёт, отменяю...",
                                 "a connection is still in progress, cancelling..."))
            self._connect_task.cancel()
            return
        if not self._is_connected():
            self._say("warn", tr("не подключено", "not connected"))
            return
        if self.mode == "run":
            self._run_abort = "remote"  # программа остановится
        await self._stop(tr("перед отключением", "disconnecting"))
        with contextlib.suppress(Exception):
            await self.robot.disconnect()
        self.robot = None
        self._say("ok", tr("отключено. Нажмите q, чтобы подключиться снова",
                           "disconnected. Press q to connect again"))

    # -- движение ------------------------------------------------------------ #
    async def _send_move(self, move: str) -> None:
        if not self._is_connected() or move not in MOVE_VECTORS:
            return
        left_fwd, right_fwd = MOVE_VECTORS[move]
        left_motor, left_dir, right_motor, right_dir = drive_directions(
            self.profile, left_fwd, right_fwd
        )
        if not await self._call(self.robot.run_motor, left_motor, left_dir, self.speed):
            return
        if self.robot is None:
            return
        if not await self._call(self.robot.run_motor, right_motor, right_dir, self.speed):
            return
        self._say("motor", tr(f"{move_label(move)} — скорость {self.speed}",
                              f"{move_label(move)} — speed {self.speed}"))

    def _schedule_send(self) -> None:
        """Отправить текущее движение с небольшим антидребезгом."""
        if self._send_task is None or self._send_task.done():
            self._send_task = asyncio.create_task(self._send_soon())

    async def _send_soon(self) -> None:
        await asyncio.sleep(self.SEND_DEBOUNCE)
        if self._is_connected() and self.move != "stop":
            await self._send_move(self.move)

    async def _on_move(self, move: str) -> None:
        if not self._is_connected():
            if self._is_connecting():
                self._say("warn", tr("подождите, идёт подключение...",
                                     "wait, connecting..."))
            else:
                self._say("warn", tr("нет подключения — нажмите q",
                                     "not connected — press q"))
            return
        self.last_input = time.monotonic()
        if move == self.move:
            return  # автоповтор удержания: только продлеваем таймер
        self.move = move
        self._schedule_send()

    async def _stop(self, reason: str) -> None:
        if not self._is_connected():
            self._say("warn", tr("нет подключения — нажмите q",
                                 "not connected — press q"))
            return
        self.move = "stop"
        self.m3_dir = None
        if await self._call(self.robot.stop_all_motors):
            self._say("motor", tr(f"стоп ({reason})", f"stop ({reason})"))

    async def _raw_drive(self, move: str, speed: int) -> bool:
        """Кадры движения в обход состояния (для тест-поездки)."""
        left_fwd, right_fwd = MOVE_VECTORS[move]
        left_motor, left_dir, right_motor, right_dir = drive_directions(
            self.profile, left_fwd, right_fwd
        )
        if not await self._call(self.robot.run_motor, left_motor, left_dir, speed):
            return False
        if self.robot is None:
            return False
        return await self._call(self.robot.run_motor, right_motor, right_dir, speed)

    async def _test_drive(self) -> None:
        if not self._is_connected():
            self._say("warn", tr("нет подключения — нажмите q",
                                 "not connected — press q"))
            return
        self.move = "stop"  # чтобы сторож не мешал последовательности
        self._say("test", tr("тест-поездка (скорость 4). Смотрите на робота:",
                             "test drive (speed 4). Watch the robot:"))
        for move in ("fwd", "back", "left", "right"):
            self._say("test", f"-> {move_label(move)}")
            if not await self._raw_drive(move, 4):
                return
            await asyncio.sleep(1.2)
            if not await self._call(self.robot.stop_all_motors):
                return
            await asyncio.sleep(0.5)
        self._say("test", tr("готово. Если направления неверные — см. раздел калибровки (h или README)",
                             "done. If the directions are wrong — see calibration (h or README)"))

    async def _identify(self) -> None:
        if not self._is_connected():
            self._say("warn", tr("нет подключения — нажмите q",
                                 "not connected — press q"))
            return
        self.move = "stop"
        self._say("test", tr("по очереди кручу моторы 1, 2, 3 (скорость 4):",
                             "running motors 1, 2, 3 one by one (speed 4):"))
        for number in (1, 2, 3):
            motor = motor_from_number(number)
            self._say("test", tr(f"-> мотор {number}", f"-> motor {number}"))
            if not await self._call(self.robot.run_motor, motor, Direction.D1, 4):
                return
            await asyncio.sleep(1.2)
            if not await self._call(self.robot.stop_motor, motor):
                return
            await asyncio.sleep(0.4)
        self._say("test", tr(
            "готово. Запомните, какой порт крутит какое колесо (--left-motor/--right-motor)",
            "done. Note which port spins which wheel (--left-motor/--right-motor)",
        ))

    # -- свет и мотор 3 ------------------------------------------------------ #
    async def _set_led(self, color: Color, name: str) -> None:
        if not self._is_connected():
            self._say("warn", tr("нет подключения — нажмите q",
                                 "not connected — press q"))
            return
        if await self._call(self.robot.all_leds, color):
            self.led_color = color
            self._say("led", tr(f"подсветка: {name}", f"light: {name}"))

    async def _on_m3(self, direction: Direction, label_ru: str, label_en: str) -> None:
        if not self._is_connected():
            self._say("warn", tr("нет подключения — нажмите q",
                                 "not connected — press q"))
            return
        if self.m3_dir == direction:
            self.m3_dir = None
            if await self._call(self.robot.stop_motor, Motor.M3):
                self._say("motor", tr("мотор 3: стоп", "motor 3: stop"))
        else:
            self.m3_dir = direction
            if await self._call(self.robot.run_motor, Motor.M3, direction, self.speed):
                label = tr(label_ru, label_en)
                self._say("motor", tr(f"мотор 3: {label} — скорость {self.speed}",
                                      f"motor 3: {label} — speed {self.speed}"))

    # -- скорость и режим ---------------------------------------------------- #
    async def _on_speed(self, delta: int) -> None:
        new_speed = max(SPEED_MIN, min(SPEED_MAX, self.speed + delta))
        if new_speed == self.speed:
            self._say("speed", tr(
                f"скорость уже {self.speed} (предел {SPEED_MIN}..{SPEED_MAX})",
                f"speed is already {self.speed} (range {SPEED_MIN}..{SPEED_MAX})",
            ))
            return
        self.speed = new_speed
        self._say("speed", tr(f"скорость {self.speed}", f"speed {self.speed}"))
        if self._is_connected() and self.move != "stop":
            self._schedule_send()  # применить новую скорость на ходу

    def _on_latch(self) -> None:
        self.latched = not self.latched
        if self.latched:
            self._say("mode", tr("фиксация: робот едет, пока не нажмёте пробел/другое",
                                 "latched: the robot drives until you press space/other"))
        elif self.key_state:
            self._say("mode", tr("удержание: стоп в момент отпускания клавиши (key-state)",
                                 "hold: stop the moment the key is released (key-state)"))
        else:
            self._say("mode", tr(
                f"удержание: авто-стоп через {self.hold_timeout:g} с после отпускания",
                f"hold: auto-stop {self.hold_timeout:g} s after release",
            ))

    # -- сторож (авто-стоп в режиме удержания) ------------------------------- #
    async def _watchdog(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.05)
                if self.latched or self.move == "stop" or not self._is_connected() or self.key_state:
                    continue
                if self.mode != "remote" or self.prompt is not None:
                    continue
                if time.monotonic() - self.last_input > self.hold_timeout:
                    await self._stop(tr("клавиша отпущена", "key released"))
        except asyncio.CancelledError:
            pass

    # -- key-state: реальное состояние клавиш (--key-state) ------------------ #
    async def _enable_key_state(self) -> None:
        backend, error = make_key_state_backend(
            self._on_key_state, self._key_state_lost, self.key_state_devices or None
        )
        if backend is None:
            self._say("warn", tr(f"--key-state недоступен: {error}; работает обычное удержание",
                                 f"--key-state unavailable: {error}; using the usual hold mode"))
            return
        error = await backend.start()
        if error is not None:
            self._say("warn", tr(f"--key-state не включился: {error}; работает обычное удержание",
                                 f"--key-state did not start: {error}; using the usual hold mode"))
            return
        self._keys_backend = backend
        self.key_state = True
        self._say("info", tr(
            f"key-state ({backend.name}): стоп в момент отпускания клавиши",
            f"key-state ({backend.name}): stop the moment the key is released",
        ))
        self._say("hint", tr(
            "клавиши ловятся глобально — не печатайте WASD в других окнах",
            "keys are captured globally — don't type WASD in other windows",
        ))

    async def _on_key_state(self, action: str, pressed: bool) -> None:
        """Нажал/отпустил с реальной клавиатуры (режим --key-state)."""
        active = self.mode == "remote" and self.prompt is None
        if pressed:
            if action in self._held_moves:
                self._held_moves.remove(action)
            self._held_moves.append(action)
            if active:
                await self._on_move(action)
            return
        if action in self._held_moves:
            self._held_moves.remove(action)
        if self.latched or not active:
            return  # фиксация: отпускание не останавливает (и в чужих режимах — тоже)
        if self._held_moves:
            await self._on_move(self._held_moves[-1])  # вернуться к другой зажатой
        elif self.move != "stop":
            await self._stop(tr("клавиша отпущена", "key released"))

    def _key_state_lost(self, reason: str) -> None:
        """Backend сломался на ходу: остановиться и вернуться к таймауту."""
        if not self.key_state:
            return
        self.key_state = False
        self._held_moves.clear()
        self.last_input = time.monotonic()
        self._say("warn", tr(f"key-state отключился ({reason}) — дальше обычное удержание",
                             f"key-state stopped ({reason}) — falling back to the usual hold mode"))
        if self._is_connected() and self.move != "stop" and self._loop is not None:
            self._loop.create_task(self._stop(tr("key-state отключился", "key-state stopped")))

    # -- справка и статус ---------------------------------------------------- #
    def _print_banner(self) -> None:
        self._say("info", tr(
            f"пульт Apitor — {self.profile.name} (product '{self.profile.product}')",
            f"Apitor remote — {self.profile.name} (product '{self.profile.product}')",
        ))
        mode = (
            tr("фиксация (робот едет, пока не остановите)",
               "latched (the robot drives until you stop it)")
            if self.latched
            else (
                tr("удержание (стоп в момент отпускания, key-state)",
                   "hold (stop the moment the key is released, key-state)")
                if self.want_key_state
                else tr(f"удержание (авто-стоп через {self.hold_timeout:g} с)",
                        f"hold (auto-stop {self.hold_timeout:g} s after release)")
            )
        )
        self._say("info", tr(f"скорость {self.speed}, режим: {mode}",
                             f"speed {self.speed}, mode: {mode}"))
        self._say(
            "hint",
            tr("q — подключиться · Shift+Q — отключиться · w/a/s/d — ехать · "
               "пробел — стоп · p — программа · h — все клавиши · Ctrl+C — выход",
               "q — connect · Shift+Q — disconnect · w/a/s/d — drive · "
               "space — stop · p — program · h — all keys · Ctrl+C — quit"),
        )

    def _print_help(self) -> None:
        if self.mode == "editor":
            self._print_prog_help()
            return
        if self.mode == "run":
            self._print_run_help()
            return
        self._say("help", tr("клавиши пульта:", "remote keys:"))
        if LANG == "en":
            lines = (
                "  q             connect (scan or cached address)",
                "  Shift+Q       disconnect",
                "  w / s         forward / back           (arrows ↑ ↓ too)",
                "  a / d         turn left / right        (arrows ← → too)",
                "  space, Esc    STOP (everything at once)",
                "  ] [  or + -  speed up / down (1..12)",
                "  1..8          light: 1 red, 2 orange, 3 yellow, 4 green,",
                "                5 cyan, 6 blue, 7 purple, 8 white",
                "  0             lights off",
                "  e / Shift+E   motor 3 (accessory): forward / back — toggle",
                "  p             program mode: enter steps, run, files",
                "  x             clear the program (stay in the current mode)",
                "  R             run the last program (loaded or previous)",
                "  F / G         save / load a program file",
                "  J             toggle the run journal",
                "  t             test drive: forward, back, left, right",
                "  i             spin motors 1, 2, 3 one by one (calibration)",
                "  l             mode: hold (auto-stop) <-> latched",
                "  h, ?          this help              Ctrl+C — quit",
                "",
                "calibration (if the robot drives the wrong way), at launch:",
                "  --flip-left / --flip-right      flip the corresponding wheel",
                "  --left-motor 2 --right-motor 1  swap the wheels",
                "",
                "launch with --key-state: stop the moment the key is released",
                "(game style; Linux — /dev/input, Windows — WinAPI)",
            )
        else:
            lines = (
                "  q             подключиться (поиск или кэш адреса)",
                "  Shift+Q       отключиться",
                "  w / s         вперёд / назад          (стрелки ↑ ↓ тоже)",
                "  a / d         разворот влево/вправо   (стрелки ← → тоже)",
                "  пробел, Esc   СТОП (мгновенно всё)",
                "  ] [  или + -  скорость больше / меньше (1..12)",
                "  1..8          подсветка: 1 красный, 2 оранжевый, 3 жёлтый,",
                "                4 зелёный, 5 голубой, 6 синий, 7 фиолетовый, 8 белый",
                "  0             выключить подсветку",
                "  e / Shift+E   мотор 3 (аксессуар, если есть): вперёд / назад — тумблер",
                "  p             режим программы: набор шагов, запуск, файлы",
                "  x             очистить программу (режим не меняется)",
                "  R             запустить последнюю программу (загруженную или прошлую)",
                "  F / G         сохранить / загрузить программу файлом",
                "  J             журнал прогонов вкл/выкл",
                "  t             тест-поездка: вперёд, назад, влево, вправо",
                "  i             крутить моторы 1, 2, 3 по очереди (калибровка)",
                "  l             режим: удержание (авто-стоп) <-> фиксация",
                "  h, ?          эта справка            Ctrl+C — выход",
                "",
                "калибровка (если робот едет не туда), указывается при запуске:",
                "  --flip-left / --flip-right      развернуть соответствующее колесо",
                "  --left-motor 2 --right-motor 1  поменять колёса местами",
                "",
                "запуск с флагом --key-state: стоп в момент отпускания клавиши",
                "(как в играх; Linux — /dev/input, Windows — WinAPI)",
            )
        for line in lines:
            print(line, flush=True)

    def _print_prog_help(self) -> None:
        self._say("help", tr("клавиши режима программы:", "program mode keys:"))
        if LANG == "en":
            lines = (
                "  w a s d       steps: forward/back/left/right (arrows too)",
                "                pressing again — +1 to the last step's number",
                "  0..9          number of the last step (0 = 10); w w w w w = «forward 5»",
                "  space         «pause» step (again — +1)",
                "  c             «color» step: c, c, c — cycles; c3 — yellow directly",
                "  b             «blink» step (again — +1)",
                "  ] [ + - = _   speed; digits right after set it exactly: ]12",
                "  r             program repeat +1 (r5 — exactly 5 times)",
                "  Backspace     delete the last step",
                "  x             clear the program (stay in this mode)",
                "  E             edit the program in $EDITOR",
                "  Enter         run",
                "  f / g         save / load a program file",
                "  Esc           back to remote (the program stays)",
                "  h, ?          this help (Ctrl+C — quit)",
            )
        else:
            lines = (
                "  w a s d       шаги: вперёд/назад/влево/вправо (стрелки тоже)",
                "                повторное нажатие — +1 к числу последнего шага",
                "  0..9          число последнего шага (0 = 10); w w w w w = «вперёд 5»",
                "  пробел        шаг «пауза» (повтор — +1)",
                "  c             шаг «цвет»: c, c, c — по кругу; c3 — сразу жёлтый",
                "  b             шаг «мигнуть» (повтор — +1)",
                "  ] [ + - = _   скорость; цифры сразу после — точное значение: ]12",
                "  r             повтор программы +1 (r5 — ровно 5 раз)",
                "  Backspace     удалить последний шаг",
                "  x             очистить программу (остаться в этом режиме)",
                "  E             редактировать программу в $EDITOR",
                "  Enter         запустить",
                "  f / g         сохранить / загрузить программу",
                "  Esc           назад в пульт (программа остаётся)",
                "  h, ?          эта справка (Ctrl+C — выход)",
            )
        for line in lines:
            print(line, flush=True)

    def _print_run_help(self) -> None:
        self._say("help", tr("клавиши во время выполнения:", "keys while running:"))
        if LANG == "en":
            lines = (
                "  space         pause / resume",
                "  Esc           abort (back to remote)",
                "  p             abort and switch to program mode",
                "  Shift+Q       disconnect (the program stops)",
                "  h, ?          this help (Ctrl+C — quit)",
            )
        else:
            lines = (
                "  пробел        пауза / продолжить",
                "  Esc           прервать (вернуться в пульт)",
                "  p             прервать и перейти в режим программы",
                "  Shift+Q       отключиться (программа остановится)",
                "  h, ?          эта справка (Ctrl+C — выход)",
            )
        for line in lines:
            print(line, flush=True)

    # -- обработка клавиш и событий ------------------------------------------ #
    def _handle_event(self, item: tuple) -> None:
        _, name, payload = item
        if name == "connected":
            self._drain_keys()
            self.move = "stop"
            self.last_input = time.monotonic()
            self._say("ok", tr(f"подключено: {self.profile.name} ({payload})",
                               f"connected: {self.profile.name} ({payload})"))
            if (self.key_state and self._held_moves and self._loop is not None
                    and self.mode == "remote"):
                # Клавиша была зажата ещё до коннекта — продолжить движение.
                self._loop.create_task(self._on_move(self._held_moves[-1]))
            if not self.sim and not self.profile.calibrated:
                self._say(
                    "hint",
                    tr("направления для этой модели не проверены на железе: "
                       "нажмите t (тест) и при необходимости --flip-left/--flip-right",
                       "directions for this model are not verified on hardware: "
                       "press t (test) and, if needed, --flip-left/--flip-right"),
                )
        elif name == "connect_failed":
            self._say("err", tr(f"подключиться не удалось: {payload}",
                                f"could not connect: {payload}"))

    async def _handle_action(self, action: str) -> bool:
        if action == "quit":
            return False
        # В режиме выполнения программа сама управляет роботом: клавиши-пульта,
        # кроме подключения/отключения/журнала/справки, молчат.
        if self.mode == "run" and action not in ("connect", "disconnect", "journal", "help"):
            return True
        # В редакторе калибровка и мотор 3 не работают (чтобы не дёрнуть робота).
        if self.mode == "editor" and action in ("test", "identify", "m3_fwd", "m3_rev", "latch"):
            return True
        if action == "connect":
            await self._on_connect_key()
        elif action == "disconnect":
            await self._on_disconnect_key()
        elif action in MOVE_VECTORS:
            if not self.key_state:  # при key-state движение ведёт backend
                await self._on_move(action)
        elif action == "stop":
            await self._stop(tr("клавиша стоп", "stop key"))
        elif action == "speed_up":
            await self._on_speed(+1)
        elif action == "speed_down":
            await self._on_speed(-1)
        elif action == "lights_off":
            await self._set_led(Color.OFF, tr("выключена", "off"))
        elif action.startswith("color:"):
            entry = COLOR_BY_KEY[action.split(":", 1)[1]]
            await self._set_led(entry[0], entry[2] if LANG == "en" else entry[1])
        elif action == "m3_fwd":
            await self._on_m3(Direction.D1, "вперёд", "forward")
        elif action == "m3_rev":
            await self._on_m3(Direction.D2, "назад", "back")
        elif action == "latch":
            self._on_latch()
        elif action == "prog":
            await self._on_prog_key()
        elif action == "run_last":
            await self._on_run_last()
        elif action == "save_prog":
            await self._open_save_prompt()
        elif action == "load_prog":
            await self._open_load_prompt()
        elif action == "journal":
            self._toggle_journal()
        elif action == "clear_prog":
            self._on_clear_prog()
        elif action == "test":
            await self._test_drive()
            self._drain_keys()
        elif action == "identify":
            await self._identify()
            self._drain_keys()
        elif action == "help":
            self._print_help()
        return True

    # -- режим программы ------------------------------------------------------ #
    def _prog_hint(self) -> str:
        return tr(
            "w/a/s/d — шаги · 0..9 — число · c цвет · b мигнуть · пробел пауза · "
            "] [ — скорость (цифры сразу: ]12) · r — повтор · Backspace — убрать шаг · "
            "Enter — запуск · x — очистить · E — редактор ($EDITOR) · Esc — пульт · "
            "f/g — файл · h — справка",
            "w/a/s/d — steps · 0..9 — number · c color · b blink · space pause · "
            "] [ — speed (digits right after: ]12) · r — repeat · Backspace — delete step · "
            "Enter — run · x — clear · E — editor ($EDITOR) · Esc — remote · "
            "f/g — file · h — help",
        )

    async def _stop_if_moving(self, reason: str) -> None:
        if self._is_connected() and self.move != "stop":
            await self._stop(reason)

    async def _on_prog_key(self) -> None:
        await self._stop_if_moving(tr("режим программы", "program mode"))
        self.editor.speed = self.speed
        if self.editor.is_empty() and self.autosave:
            self._load_draft()
        self.mode = "editor"
        self._say("prog", self.editor.line())
        self._say("hint", self._prog_hint())

    async def _on_remote_key(self) -> None:
        self.speed = self.editor.speed
        self.mode = "remote"
        self._say("mode", tr(f"пульт (скорость {self.speed})",
                             f"remote (speed {self.speed})"))

    def _on_clear_prog(self) -> None:
        """x: очистить программу и остаться в текущем режиме."""
        self.editor.clear()
        self._draft_loaded = False
        draft = self.program_dir / DRAFT_FILE
        try:
            if draft.exists():
                draft.unlink()
        except OSError as exc:
            self._dbg(f"черновик не стереть: {exc!r}")
        self._say("prog", tr("программа очищена", "program cleared"))
        if self.mode == "editor":
            self._say("prog", self.editor.line())

    # -- внешний редактор ($EDITOR) ------------------------------------------- #
    def _editor_command(self) -> list[str] | None:
        """Команда внешнего редактора: $EDITOR/$VISUAL, иначе известные имена."""
        for env in ("EDITOR", "VISUAL"):
            value = os.environ.get(env)
            if value:
                parts = shlex.split(value)
                if parts:
                    return parts
        candidates = ("edit", "notepad") if IS_WINDOWS else ("nvim", "nano", "vi")
        for name in candidates:
            path = shutil.which(name)
            if path:
                return [path]
        return None

    def _pause_terminal_for_editor(self) -> list | None:
        """Вернуть терминал в обычный режим на время внешнего редактора."""
        if IS_WINDOWS:
            return None
        fd = sys.stdin.fileno()
        try:
            raw = termios.tcgetattr(fd)
            termios.tcsetattr(fd, termios.TCSADRAIN, self._termios_original)
        except Exception as exc:  # noqa: BLE001 — редактор всё равно откроется
            self._dbg(f"терминал не переключить на время редактора: {exc!r}")
            return None
        return raw

    def _resume_terminal_after_editor(self, raw) -> None:
        """Вернуть "сырой" режим терминала после внешнего редактора."""
        if IS_WINDOWS or raw is None:
            return
        fd = sys.stdin.fileno()
        with contextlib.suppress(Exception):
            termios.tcsetattr(fd, termios.TCSADRAIN, raw)

    async def _edit_program_external(self) -> None:
        """E: отдать текущую программу внешнему редактору и загрузить обратно."""
        cmd = self._editor_command()
        if cmd is None:
            self._say("warn", tr(
                "внешний редактор не найден: задайте $EDITOR или $VISUAL "
                "(Windows: edit/notepad; Linux: nvim/nano/vi)",
                "no external editor found: set $EDITOR or $VISUAL "
                "(Windows: edit/notepad; Linux: nvim/nano/vi)",
            ))
            return
        try:
            self.program_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._say("err", tr(f"не создать папку программ: {exc}",
                                f"cannot create the program folder: {exc}"))
            return
        try:
            fd, name = tempfile.mkstemp(prefix="_edit_", suffix=".txt", dir=self.program_dir)
        except OSError as exc:
            self._say("err", tr(f"не создать временный файл: {exc}",
                                f"cannot create a temporary file: {exc}"))
            return
        path = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(self.editor.serialize())
        except OSError as exc:
            self._say("err", tr(f"не записать временный файл: {exc}",
                                f"cannot write the temporary file: {exc}"))
            with contextlib.suppress(OSError):
                path.unlink()
            return
        self._say("prog", tr(
            f"открываю редактор ({' '.join(cmd)}) — горячие клавиши пульта выключены",
            f"opening the editor ({' '.join(cmd)}) — the remote hotkeys are off",
        ))
        self._external_editor.set()
        self._reader_paused.wait(timeout=1.0)
        self._drain_keys()
        raw = self._pause_terminal_for_editor()
        try:
            await asyncio.to_thread(subprocess.run, cmd + [str(path)])
        except Exception as exc:  # noqa: BLE001 — редактор может не запуститься
            self._say("err", tr(f"редактор не запустился: {exc}",
                                f"the editor did not start: {exc}"))
            self._resume_terminal_after_editor(raw)
            self._external_editor.clear()
            self._flush_pending_output()
            with contextlib.suppress(OSError):
                path.unlink()
            return
        self._resume_terminal_after_editor(raw)
        self._external_editor.clear()
        self._flush_pending_output()
        try:
            text = path.read_text("utf-8")
        except OSError as exc:
            self._say("err", tr(f"не прочитать файл после редактора: {exc}",
                                f"cannot read the file after the editor: {exc}"))
            return
        finally:
            with contextlib.suppress(OSError):
                path.unlink()
        steps, repeat, speed, errors = parse_program(text, self.max_steps)
        if errors:
            for message in errors[:5]:
                self._say("err", f"{path.name}: {message}")
            if len(errors) > 5:
                self._say("err", tr(f"…и ещё {len(errors) - 5} ошибок",
                                    f"…and {len(errors) - 5} more errors"))
            self._say("warn", tr("программа не изменена — исправьте ошибки в файле и повторите",
                                 "the program is unchanged — fix the errors and try again"))
            if self.mode == "editor":
                self._say("prog", self.editor.line())
            return
        self.editor.set_program(steps, repeat, speed)
        self.speed = self.editor.speed
        n = len(steps)
        self._say("prog", tr(f"обновлено из редактора ({n} {steps_word(n)})",
                             f"updated from the editor ({n} {steps_word(n)})"))
        self._say("prog", self.editor.line())

    def _load_draft(self) -> None:
        draft = self.program_dir / DRAFT_FILE
        try:
            text = draft.read_text("utf-8")
        except OSError:
            return
        steps, repeat, speed, errors = parse_program(text, self.max_steps)
        if errors or not steps:
            return
        self.editor.set_program(steps, repeat, speed)
        self._draft_loaded = True
        n = len(steps)
        self._say("info", tr(f"подхватил черновик ({n} {steps_word(n)})",
                             f"restored the draft ({n} {steps_word(n)})"))

    # -- диспетчер клавиш ----------------------------------------------------- #
    async def _handle_key(self, item: str) -> bool:
        if self.prompt is not None:
            return await self._handle_prompt_key(item)
        key = _to_latin_layout(item) if len(item) == 1 else item
        if key == "\x03":
            return False  # Ctrl+C
        if self.mode == "editor" and await self._handle_editor_key(key):
            return True
        if self.mode == "run" and await self._handle_run_key(key):
            return True
        action = KEYMAP.get(key)
        if action is None:
            return True
        return await self._handle_action(action)

    async def _handle_editor_key(self, key: str) -> bool:
        if key == "E":
            await self._edit_program_external()
            return True
        result = self.editor.key(key, time.monotonic())
        if result is None:
            return False
        if result.action in ("line", "note"):
            self._say("prog", result.text)
        elif result.action == "warn":
            self._say("warn", result.text)
        elif result.action == "run":
            await self._start_program_run(from_editor=True)
        elif result.action == "save":
            await self._open_save_prompt()
        elif result.action == "load":
            await self._open_load_prompt()
        elif result.action == "remote":
            await self._on_remote_key()
        return True

    async def _handle_run_key(self, key: str) -> bool:
        if key == " ":
            self._run_paused = not self._run_paused
            self._say("run", tr("пауза", "paused") if self._run_paused
                      else tr("продолжаю", "resuming"))
            return True
        if key == "esc":
            self._run_abort = "remote"  # Esc: прервать и вернуться в пульт
            return True
        if key == "p":
            self._run_abort = "editor"  # P: прервать и перейти в режим программы
            return True
        return False

    # -- файлы программы ------------------------------------------------------ #
    def _prompt_write(self, text: str) -> None:
        self._out(text, end="")

    def _prompt_end(self) -> None:
        print(flush=True)
        self.prompt = None

    async def _open_save_prompt(self) -> None:
        if self.editor.is_empty():
            self._say("warn", tr("нечего сохранять — программа пуста",
                                 "nothing to save — the program is empty"))
            return
        await self._stop_if_moving(tr("сохранение программы", "saving the program"))
        stamp = time.strftime("%Y-%m-%d-%H%M")
        default = self.program_name or tr(f"программа-{stamp}.txt",
                                          f"program-{stamp}.txt")
        self.prompt = {"kind": "save", "text": "", "default": default}
        self._prompt_write(f"[save] {tr('имя файла', 'file name')} [{default}]: ")

    def _sanitize_name(self, name: str) -> str:
        name = name.strip().replace("/", "_").replace("\\", "_").replace("\x00", "")
        name = name[:80] or "program.txt"
        if not name.lower().endswith(".txt"):
            name += ".txt"
        return name

    def _write_program_file(self, name: str) -> None:
        try:
            self.program_dir.mkdir(parents=True, exist_ok=True)
            path = self.program_dir / name
            path.write_text(self.editor.serialize(), "utf-8")
        except OSError as exc:
            self._say("err", tr(f"не удалось сохранить: {exc}",
                                f"could not save: {exc}"))
            return
        self.program_name = name
        n = len(self.editor.steps)
        self._say("save", tr(f"сохранено: {path} ({n} {steps_word(n)})",
                             f"saved: {path} ({n} {steps_word(n)})"))

    def load_program_file(self, path: Path, announce: bool = True) -> bool:
        try:
            text = path.read_text("utf-8")
        except OSError as exc:
            self._say("err", tr(f"не прочитать {path}: {exc}",
                                f"cannot read {path}: {exc}"))
            return False
        steps, repeat, speed, errors = parse_program(text, self.max_steps)
        if errors:
            for message in errors[:5]:
                self._say("err", f"{path.name}: {message}")
            if len(errors) > 5:
                self._say("err", tr(f"…и ещё {len(errors) - 5} ошибок",
                                    f"…and {len(errors) - 5} more errors"))
            return False
        self.editor.set_program(steps, repeat, speed)
        self.speed = self.editor.speed
        self.program_name = path.name
        if announce:
            n = len(steps)
            self._say("load", tr(
                f"загружено: {path.name} ({n} {steps_word(n)} · скор. {self.editor.speed})",
                f"loaded: {path.name} ({n} {steps_word(n)} · speed {self.editor.speed})",
            ))
            if self.mode == "editor":
                self._say("prog", self.editor.line())
            else:
                self._say("hint", tr("R — запустить · p — редактор",
                                     "R — run · p — editor"))
        return True

    async def _open_load_prompt(self) -> None:
        await self._stop_if_moving(tr("загрузка программы", "loading a program"))
        files: list[Path] = []
        if self.program_dir.is_dir():
            files = sorted(
                (p for p in self.program_dir.glob("*.txt") if not p.name.startswith("_")),
                key=lambda item: item.name.lower(),
            )
        if not files:
            self._say("load", tr(f"нет сохранённых программ ({self.program_dir})",
                                 f"no saved programs ({self.program_dir})"))
            return
        shown = files[:12]
        self._say("load", tr(f"программы ({self.program_dir}):",
                             f"programs ({self.program_dir}):"))
        for i, path in enumerate(shown, 1):
            self._say("load", f"  {i}) {path.name} — {self._describe_file(path)}")
        if len(files) > len(shown):
            self._say("load", tr(f"…и ещё {len(files) - len(shown)}",
                                 f"…and {len(files) - len(shown)} more"))
        self.prompt = {"kind": "load", "files": shown, "text": ""}
        self._prompt_write(f"[load] {tr('номер', 'number')}: ")

    def _describe_file(self, path: Path) -> str:
        try:
            text = path.read_text("utf-8")
        except OSError:
            return tr("не прочитать", "unreadable")
        steps, _, _, errors = parse_program(text, self.max_steps)
        if errors:
            return tr("ошибка", "error")
        if not steps:
            return tr("пусто", "empty")
        return f"{len(steps)} {steps_word(len(steps))}"

    async def _handle_prompt_key(self, item: str) -> bool:
        prompt = self.prompt
        if prompt is None:
            return True
        if item == "\x03":
            return False
        kind = prompt["kind"]
        if kind == "save":
            if item == "esc":
                self._prompt_end()
                self._say("save", tr("отменено", "cancelled"))
            elif item == "enter":
                name = self._sanitize_name(prompt["text"].strip() or prompt["default"])
                self._prompt_end()
                if (self.program_dir / name).exists():
                    self.prompt = {"kind": "confirm", "name": name}
                    self._prompt_write(
                        f"[save] {tr(f'«{name}» уже есть — перезаписать? y/n', f'«{name}» already exists — overwrite? y/n')}: "
                    )
                else:
                    self._write_program_file(name)
            elif item == "backspace":
                if prompt["text"]:
                    prompt["text"] = prompt["text"][:-1]
                    self._prompt_write("\b \b")
            elif len(item) == 1 and item.isprintable():
                prompt["text"] += item
                self._prompt_write(item)
            return True
        if kind == "confirm":
            name = prompt["name"]
            self._prompt_end()
            if item in ("y", "Y", "д", "Д"):
                self._write_program_file(name)
            else:
                self._say("save", tr("отменено", "cancelled"))
            return True
        if kind == "load":
            if item == "esc":
                self._prompt_end()
                self._say("load", tr("отменено", "cancelled"))
            elif item == "enter":
                text = prompt["text"]
                files = prompt["files"]
                if text.isdigit() and 1 <= int(text) <= len(files):
                    chosen = files[int(text) - 1]
                    self._prompt_end()
                    self.load_program_file(chosen)
                else:
                    self._prompt_end()
                    self._say("warn", tr("нет такого номера", "no such number"))
                    self.prompt = {"kind": "load", "files": files, "text": text}
                    self._prompt_write(f"[load] {tr('номер', 'number')}: {text}")
            elif item == "backspace":
                if prompt["text"]:
                    prompt["text"] = prompt["text"][:-1]
                    self._prompt_write("\b \b")
            elif len(item) == 1 and item.isdigit():
                prompt["text"] += item
                self._prompt_write(item)
            return True
        return True

    # -- журнал и черновик ---------------------------------------------------- #
    def _toggle_journal(self) -> None:
        self.journal = not self.journal
        state = tr("включён", "on") if self.journal else tr("выключен", "off")
        self._say("log", tr(f"журнал {state}: {self.journal_path}",
                            f"journal {state}: {self.journal_path}"))

    def _journal_write(self, result: str, steps: int, planned: float, actual: float) -> None:
        if not self.journal:
            return
        try:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            name = self.program_name or tr("(без имени)", "(unnamed)")
            line = (f"{stamp} · {name} · {steps} {steps_word(steps)} · "
                    f"{tr('план', 'plan')} {planned:.1f} {tr('с', 's')} · "
                    f"{tr('факт', 'actual')} {actual:.1f} {tr('с', 's')} · {result}")
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with self.journal_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:
            self._dbg(f"журнал не записался: {exc!r}")

    def _autosave(self) -> None:
        if not self.autosave:
            return
        draft = self.program_dir / DRAFT_FILE
        try:
            if not self.editor.is_empty():
                self.program_dir.mkdir(parents=True, exist_ok=True)
                draft.write_text(self.editor.serialize(), "utf-8")
            elif self._draft_loaded and draft.exists():
                draft.unlink()
        except Exception as exc:
            self._dbg(f"черновик не сохранился: {exc!r}")

    # -- выполнение программы ------------------------------------------------- #
    async def _on_run_last(self) -> None:
        if self.editor.is_empty():
            return  # «ничего не было» — ноль реакции
        await self._start_program_run(from_editor=False)

    async def _start_program_run(self, *, from_editor: bool) -> None:
        if self._run_task is not None and not self._run_task.done():
            return
        if self.editor.is_empty():
            if from_editor:
                self._say("warn", tr("программа пуста — добавьте шаги (w/a/s/d)",
                                     "the program is empty — add steps (w/a/s/d)"))
            return
        if not self._is_connected():
            self._say("warn", tr("нет подключения — нажмите q",
                                 "not connected — press q"))
            return
        self.speed = self.editor.speed
        self._run_paused = False
        self._run_abort = None
        self.mode = "run"
        self._run_task = asyncio.create_task(self._run_worker())

    def _check_run(self) -> None:
        if self._run_abort is not None:
            raise _RunAbort
        if not self._is_connected():
            self._run_abort = "remote"
            raise _RunAbort

    async def _sleep_checked(self, duration: float) -> None:
        remaining = duration
        while remaining > 0:
            self._check_run()
            if self._run_paused:
                await asyncio.sleep(0.05)
                continue
            chunk = min(0.05, remaining)
            await asyncio.sleep(chunk)
            remaining -= chunk

    async def _run_motion(self, move: str, duration: float, speed: int) -> None:
        sent = False
        remaining = duration
        try:
            while remaining > 0:
                self._check_run()
                if self._run_paused:
                    if sent:
                        await self._call(self.robot.stop_all_motors)
                        sent = False
                    await asyncio.sleep(0.05)
                    continue
                if not sent:
                    if not await self._raw_drive(move, speed):
                        self._run_abort = "remote"
                        raise _RunAbort
                    sent = True
                chunk = min(0.05, remaining)
                await asyncio.sleep(chunk)
                remaining -= chunk
        finally:
            if sent and self._is_connected():
                await self._call(self.robot.stop_all_motors)

    async def _led_flash(self, color: Color, seconds: float, restore: Color) -> None:
        if not self._is_connected():
            return
        if not await self._call(self.robot.all_leds, color):
            return
        await asyncio.sleep(seconds)
        if self._is_connected():
            await self._call(self.robot.all_leds, restore)

    async def _run_worker(self) -> None:
        started = time.monotonic()
        steps = [Step(s.kind, s.value) for s in self.editor.steps]
        total = len(steps)
        repeat = max(1, self.editor.repeat)
        speed = self.editor.speed
        planned = self.editor.estimate()
        prev_led = self.led_color
        run_led = self.led_color
        self._run_total = total
        self._run_step = 0
        head = tr(f"старт: {total} {steps_word(total)} · скор. {speed}",
                  f"start: {total} {steps_word(total)} · speed {speed}")
        if repeat > 1:
            head += tr(f" · повтор {repeat}", f" · repeat {repeat}")
        self._say("run", head)
        self._say("hint", tr("пробел — пауза/продолжить, Esc — стоп",
                             "space — pause/resume, Esc — stop"))
        await self._led_flash(Color.GREEN, 0.35, run_led)
        finished = False
        try:
            for rep in range(1, repeat + 1):
                for idx, step in enumerate(steps, 1):
                    self._run_step = idx
                    self._check_run()
                    suffix = (tr(f" · повтор {rep}/{repeat}", f" · repeat {rep}/{repeat}")
                              if repeat > 1 else "")
                    self._say("run", f"▶ {step_text(step)}{suffix}")
                    if step.kind == "color":
                        run_led = Color(step.value)
                        if not await self._call(self.robot.all_leds, run_led):
                            self._run_abort = "remote"
                            raise _RunAbort
                    elif step.kind == "blink":
                        for _ in range(step.value):
                            if not await self._call(self.robot.all_leds, Color.OFF):
                                self._run_abort = "remote"
                                raise _RunAbort
                            await self._sleep_checked(self.blink_time)
                            if not await self._call(self.robot.all_leds, run_led):
                                self._run_abort = "remote"
                                raise _RunAbort
                            await self._sleep_checked(self.blink_time)
                    elif step.kind == "pause":
                        await self._sleep_checked(step.value * self.pause_time)
                    else:
                        await self._run_motion(
                            step.kind, self.editor._step_seconds(step), speed
                        )
            finished = True
        except _RunAbort:
            pass
        except Exception as exc:  # noqa: BLE001 — программа не должна ронять пульт
            self._dbg(f"программа упала: {exc!r}")
        elapsed = time.monotonic() - started
        if self._is_connected():
            await self._call(self.robot.stop_all_motors)
        if finished:
            await self._led_flash(Color.GREEN, 0.15, run_led)
            await self._led_flash(Color.GREEN, 0.15, run_led)
            self.speed = speed
            self.mode = "remote"
            self._say("run", tr(
                f"готово: {total} {steps_word(total)} за {elapsed:.1f} с (план {planned:.1f} с)",
                f"done: {total} {steps_word(total)} in {elapsed:.1f} s (planned {planned:.1f} s)",
            ))
            self._say("hint", tr("R — ещё раз · p — редактор", "R — run again · p — editor"))
            self._journal_write(tr("готово", "done"), total, planned, elapsed)
        else:
            await self._led_flash(Color.RED, 0.35, prev_led)
            if self._run_abort == "editor":
                self.mode = "editor"
                self._say("run", tr(
                    f"прервано на шаге {self._run_step} из {total} — режим программы",
                    f"aborted at step {self._run_step} of {total} — program mode",
                ))
                self._say("prog", self.editor.line())
            else:
                self.mode = "remote"
                self._say("run", tr(
                    f"прервано на шаге {self._run_step} из {total} — пульт",
                    f"aborted at step {self._run_step} of {total} — remote",
                ))
            self._journal_write(
                tr(f"прервано на шаге {self._run_step}/{total}",
                   f"aborted at step {self._run_step}/{total}"),
                total, planned, elapsed,
            )
        # вернуть подсветку, как было до запуска
        self.led_color = prev_led
        if self._is_connected():
            await self._call(self.robot.all_leds, prev_led)
        self._run_paused = False
        self._run_abort = None
        self._run_task = None

    # -- потоки чтения клавиатуры -------------------------------------------- #
    def _reader_thread_posix(self) -> None:
        fd = sys.stdin.fileno()
        while True:
            if self._external_editor.is_set():
                self._reader_paused.set()
                time.sleep(0.05)  # клавиатура отдана внешнему редактору
                continue
            self._reader_paused.clear()
            try:
                if not select.select([fd], [], [], 0.1)[0]:
                    continue
                key = read_key_posix(fd)
            except Exception as exc:  # noqa: BLE001 — ввод может закрыться в любой момент
                self._dbg(f"ошибка чтения stdin: {exc!r}")
                key = "quit"
            if key is not None:
                self._put(key)
                if key == "quit":
                    return

    def _reader_thread_windows(self) -> None:
        import msvcrt

        while True:
            if self._external_editor.is_set():
                self._reader_paused.set()
                time.sleep(0.05)  # клавиатура отдана внешнему редактору
                continue
            self._reader_paused.clear()
            if not msvcrt.kbhit():
                time.sleep(0.02)
                continue
            try:
                char = msvcrt.getwch()
            except KeyboardInterrupt:
                self._put("quit")
                return
            except Exception as exc:  # noqa: BLE001
                self._dbg(f"ошибка чтения stdin: {exc!r}")
                self._put("quit")
                return
            if char in ("\x00", "\xe0"):  # спецклавиша: стрелки и т. п.
                try:
                    code = msvcrt.getwch()
                except Exception:
                    continue
                arrow = {"H": "up", "P": "down", "K": "left", "M": "right"}.get(code)
                if arrow:
                    self._put(arrow)
                continue
            if char == "\r":
                self._put("enter")
            elif char == "\x08":
                self._put("backspace")
            elif char == "\x1b":
                self._put("esc")
            else:
                self._put(char)

    # -- главный цикл -------------------------------------------------------- #
    async def _cleanup(self) -> None:
        if self.robot is not None:
            with contextlib.suppress(Exception):
                await self.robot.stop_all_motors()
            with contextlib.suppress(Exception):
                await self.robot.disconnect()
            self.robot = None

    async def run(self) -> int:
        if not sys.stdin.isatty():
            print(
                tr("Ошибка: пульту нужен настоящий терминал (запустите его в окне терминала).",
                   "Error: the remote needs a real terminal (run it in a terminal window)."),
                file=sys.stderr,
            )
            return 2
        self._loop = asyncio.get_running_loop()
        self._print_banner()
        if not self.editor.is_empty() and self.program_name is not None:
            n = len(self.editor.steps)
            self._say("load", tr(
                f"программа «{self.program_name}»: {n} {steps_word(n)} · скор. {self.editor.speed}",
                f"program «{self.program_name}»: {n} {steps_word(n)} · speed {self.editor.speed}",
            ))
            self._say("hint", tr("R — запустить · p — редактор", "R — run · p — editor"))
        if self.journal:
            self._say("log", tr(f"журнал включён: {self.journal_path}",
                                f"journal is on: {self.journal_path}"))
        if self.want_key_state:
            await self._enable_key_state()
        elif self.key_state_devices:
            self._say("warn", tr("--key-state-device работает только вместе с --key-state",
                                 "--key-state-device only works together with --key-state"))
        if not IS_WINDOWS:
            with contextlib.suppress(Exception):
                self._termios_original = termios.tcgetattr(sys.stdin.fileno())
        with RawTerminal():
            target = self._reader_thread_windows if IS_WINDOWS else self._reader_thread_posix
            threading.Thread(target=target, daemon=True).start()
            watchdog = asyncio.create_task(self._watchdog())
            try:
                while True:
                    item = await self.keys.get()
                    if isinstance(item, tuple):
                        self._handle_event(item)
                        continue
                    if not await self._handle_key(item):
                        break
            except KeyboardInterrupt:  # на всякий случай (например, сигнал извне)
                pass
            finally:
                run_task = self._run_task
                if run_task is not None and not run_task.done():
                    self._run_abort = self._run_abort or "remote"
                    with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError, Exception):
                        await asyncio.wait_for(run_task, 3.0)
                self._autosave()
                watchdog.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watchdog
                if self._keys_backend is not None:
                    await self._keys_backend.stop()
                    self._keys_backend = None
                if self._send_task is not None and not self._send_task.done():
                    self._send_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._send_task
                if self._connect_task is not None and not self._connect_task.done():
                    self._connect_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await self._connect_task
                was_connected = self._is_connected()
                await self._cleanup()
                self._say("ok", tr("робот остановлен и отключён", "the robot is stopped and disconnected")
                          if was_connected else tr("выход", "exiting"))
        print(tr("Пока!", "Bye!"), flush=True)
        return 0


# --------------------------------------------------------------------------- #
# Состояние клавиш (--key-state)
# --------------------------------------------------------------------------- #
# Настоящие "нажал/отпустил" в обход автоповтора, как в играх: движение
# начинается в момент нажатия и прекращается в момент отпускания. Платформа
# определяется автоматически: Linux — evdev (/dev/input/event*), Windows —
# WinAPI (GetAsyncKeyState). Без флага работает обычный режим (автоповтор
# и авто-стоп по --hold-timeout).

_EVDEV_KEY_ACTION = {  # коды клавиш Linux -> действие (физические WASD, стрелки)
    17: "fwd", 103: "fwd",      # W, ↑
    31: "back", 108: "back",    # S, ↓
    30: "left", 105: "left",    # A, ←
    32: "right", 106: "right",  # D, →
}
# struct input_event: timeval (два машинных слова) + type, code (u16) + value (i32).
_EVENT = struct.Struct(("ll" if struct.calcsize("l") == 8 else "qq") + "HHi")


class EvdevKeyState:
    """Реальное состояние клавиш через /dev/input/event* (Linux).

    Читает все устройства ввода сразу (любая клавиатура) и следит только за
    WASD и стрелками; раскладка не важна — привязка к физическим клавишам.
    Новые устройства (например, USB-клавиатура) подхватываются на ходу.
    """

    name = "evdev"
    RESCAN_SECONDS = 2.0

    def __init__(self, on_change, on_fail, paths=None) -> None:
        self._on_change = on_change  # async (действие, нажато?)
        self._on_fail = on_fail      # sync (причина), если пропали все устройства
        self._paths: list[str] = [str(p) for p in paths] if paths else []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._fds: dict[int, str] = {}
        self._pending: dict[int, bytes] = {}  # недобранные байты (потоковые источники)
        self._rescan_task: asyncio.Task | None = None

    async def start(self) -> str | None:
        self._loop = asyncio.get_running_loop()
        denied = self._open_devices()
        if not self._fds:
            if self._paths:
                what = ", ".join(self._paths)
                hint = " (нет доступа — добавьте пользователя в группу input)" if denied else ""
                return f"не удалось открыть: {what}{hint}"
            if denied:
                return ("нет доступа к /dev/input/event* — добавьте пользователя "
                        "в группу input (sudo usermod -aG input $USER) и войдите заново")
            return "не найдено устройств /dev/input/event*"
        self._rescan_task = self._loop.create_task(self._rescan())
        return None

    def _candidate_paths(self) -> list[Path]:
        if self._paths:
            return [Path(p) for p in self._paths]
        return sorted(Path("/dev/input").glob("event*"))

    def _open_devices(self) -> int:
        """Открыть ещё не открытые устройства; вернуть число отказов в доступе."""
        denied = 0
        for path in self._candidate_paths():
            if str(path) in self._fds.values():
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except PermissionError:
                denied += 1
            except OSError:
                pass
            else:
                self._fds[fd] = str(path)
                self._loop.add_reader(fd, self._on_readable, fd)
        return denied

    def _on_readable(self, fd: int) -> None:
        while True:
            try:
                data = os.read(fd, _EVENT.size * 64)
            except BlockingIOError:
                return
            except OSError as exc:
                self._drop(fd, f"{self._fds.get(fd, fd)}: {exc}")
                return
            if not data:  # источник закрылся (EOF): дальше ждать нечего
                self._drop(fd, f"{self._fds.get(fd, fd)}: поток закрыт")
                return
            # Устройства отдают только целые кадры, но потоковые источники
            # (FIFO и т.п.) могут разрезать кадр — хвост дочитываем потом.
            chunk = self._pending.get(fd, b"") + data
            whole = len(chunk) - len(chunk) % _EVENT.size
            if whole:
                self._dispatch(chunk[:whole])
            if whole < len(chunk):
                self._pending[fd] = chunk[whole:]

    def _dispatch(self, data: bytes) -> None:
        for i in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
            _, _, etype, code, value = _EVENT.unpack_from(data, i)
            if etype != 1 or value not in (0, 1):  # EV_KEY; 2 — автоповтор ядра
                continue
            action = _EVDEV_KEY_ACTION.get(code)
            if action is not None and self._loop is not None:
                self._loop.create_task(self._on_change(action, value == 1))

    def _drop(self, fd: int, reason: str) -> None:
        with contextlib.suppress(Exception):
            self._loop.remove_reader(fd)
        with contextlib.suppress(OSError):
            os.close(fd)
        self._fds.pop(fd, None)
        self._pending.pop(fd, None)
        if not self._fds and self._rescan_task is not None:
            self._rescan_task.cancel()
            self._rescan_task = None
            self._on_fail(f"устройства ввода пропали ({reason})")

    async def _rescan(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            while True:
                await asyncio.sleep(self.RESCAN_SECONDS)
                self._open_devices()

    async def stop(self) -> None:
        if self._rescan_task is not None:
            self._rescan_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._rescan_task
            self._rescan_task = None
        for fd in list(self._fds):
            with contextlib.suppress(Exception):
                self._loop.remove_reader(fd)
            with contextlib.suppress(OSError):
                os.close(fd)
        self._fds.clear()
        self._pending.clear()


class WinApiKeyState:
    """Реальное состояние клавиш через GetAsyncKeyState (Windows)."""

    name = "WinAPI"
    POLL_SECONDS = 0.01
    LETTER_SCANCODE = {"fwd": 0x11, "left": 0x1E, "back": 0x1F, "right": 0x20}  # W A S D
    LETTER_VK = {"fwd": 0x57, "left": 0x41, "back": 0x53, "right": 0x44}
    ARROW_VK = {"fwd": 0x26, "back": 0x28, "left": 0x25, "right": 0x27}

    def __init__(self, on_change, on_fail) -> None:
        self._on_change = on_change
        self._on_fail = on_fail
        self._user32 = None
        self._vk_by_action: dict[str, tuple[int, ...]] = {}
        self._down: frozenset[str] = frozenset()
        self._task: asyncio.Task | None = None

    async def start(self) -> str | None:
        import ctypes  # только для Windows; импорт внутри, чтобы не мешать Linux

        try:
            self._user32 = ctypes.windll.user32
            self._user32.GetAsyncKeyState.restype = ctypes.c_short
            self._user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
            self._user32.GetKeyboardLayout.restype = ctypes.c_void_p
            self._user32.GetKeyboardLayout.argtypes = (ctypes.c_uint,)
            self._user32.MapVirtualKeyExW.restype = ctypes.c_uint
            self._user32.MapVirtualKeyExW.argtypes = (
                ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
            )
        except Exception as exc:  # noqa: BLE001 — WinAPI может быть недоступен
            return f"WinAPI недоступен ({exc})"
        hkl = self._user32.GetKeyboardLayout(0)
        vk_by_action = {}
        for action, scancode in self.LETTER_SCANCODE.items():
            # Скан-код -> виртуальная клавиша по текущей раскладке: физическая W
            # работает и при русской раскладке (MAPVK_VSC_TO_VK_EX = 2).
            vk = self._user32.MapVirtualKeyExW(scancode, 2, hkl) or self.LETTER_VK[action]
            vk_by_action[action] = (vk, self.ARROW_VK[action])
        self._vk_by_action = vk_by_action
        self._task = asyncio.get_running_loop().create_task(self._poll())
        return None

    def _is_down(self, action: str) -> bool:
        return any(
            self._user32.GetAsyncKeyState(vk) & 0x8000
            for vk in self._vk_by_action[action]
        )

    async def _poll(self) -> None:
        try:
            while True:
                down = frozenset(a for a in self._vk_by_action if self._is_down(a))
                for action in sorted(down - self._down):
                    await self._on_change(action, True)
                for action in sorted(self._down - down):
                    await self._on_change(action, False)
                self._down = down
                await asyncio.sleep(self.POLL_SECONDS)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            self._on_fail(f"опрос клавиш сломался ({exc!r})")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


def make_key_state_backend(on_change, on_fail, paths=None):
    """Выбрать backend по платформе: (backend или None, причина отказа).

    paths — конкретные устройства (`--key-state-device`); None — все event*.
    """
    if sys.platform.startswith("linux"):
        return EvdevKeyState(on_change, on_fail, paths), None
    if IS_WINDOWS:
        return WinApiKeyState(on_change, on_fail), None
    return None, "поддерживается только Linux (evdev) и Windows (WinAPI)"


# --------------------------------------------------------------------------- #
# Запуск
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apitor_remote",
        description=tr("Пульт с горячими клавишами для Apitor Robot R (и других Apitor).",
                       "Hotkey remote for the Apitor Robot R (and other Apitors)."),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--product", default="r", help=tr("модель: r, j, s, q, x, w (Wheels)",
                                                          "model: r, j, s, q, x, w (Wheels)"))
    parser.add_argument("--address", default=None,
                        help=tr("адрес Bluetooth (иначе поиск/кэш)", "Bluetooth address (otherwise scan/cache)"))
    parser.add_argument("--speed", type=int, default=DEFAULT_SPEED,
                        help=tr(f"скорость {SPEED_MIN}..{SPEED_MAX}", f"speed {SPEED_MIN}..{SPEED_MAX}"))
    parser.add_argument(
        "--hold-timeout",
        type=float,
        default=DEFAULT_HOLD_TIMEOUT,
        help=tr("через сколько секунд после отпускания клавиши остановиться",
                "seconds after the key is released before stopping"),
    )
    parser.add_argument("--latched", action="store_true",
                        help=tr("стартовать в режиме фиксации", "start in latched mode"))
    parser.add_argument("--simulate", action="store_true",
                        help=tr("без Bluetooth: печатать кадры", "no Bluetooth: print frames"))
    parser.add_argument(
        "--key-state",
        action="store_true",
        help=tr("стоп в момент отпускания клавиши, как в играх (Linux: evdev, "
                "Windows: WinAPI); без флага — авто-стоп по --hold-timeout",
                "stop the moment the key is released, game style (Linux: evdev, "
                "Windows: WinAPI); without the flag — auto-stop by --hold-timeout"),
    )
    parser.add_argument(
        "--key-state-device",
        action="append",
        metavar=tr("ПУТЬ", "PATH"),
        help=tr("следить за клавишами только с этого устройства (можно указать "
                "несколько раз); по умолчанию — все /dev/input/event*",
                "watch keys only on this device (can be given several times); "
                "by default — all /dev/input/event*"),
    )
    parser.add_argument("--no-cache", action="store_true",
                        help=tr("не использовать кэш адреса", "do not use the address cache"))
    parser.add_argument("--scan-timeout", type=float, default=15.0,
                        help=tr("сколько секунд искать робота", "how many seconds to scan for the robot"))
    parser.add_argument("--left-motor", type=int, choices=(1, 2, 3), default=None,
                        help=tr("номер мотора левого колеса", "left wheel motor number"))
    parser.add_argument("--right-motor", type=int, choices=(1, 2, 3), default=None,
                        help=tr("номер мотора правого колеса", "right wheel motor number"))
    parser.add_argument("--flip-left", action="store_true",
                        help=tr("развернуть левое колесо", "flip the left wheel"))
    parser.add_argument("--flip-right", action="store_true",
                        help=tr("развернуть правое колесо", "flip the right wheel"))
    parser.add_argument(
        "--lang",
        choices=("ru", "en"),
        default=None,
        help=tr("язык интерфейса: ru или en (выбор запоминается в config.json)",
                "interface language: ru or en (the choice is remembered in config.json)"),
    )
    parser.add_argument(
        "--program",
        metavar=tr("ФАЙЛ", "FILE"),
        default=None,
        help=tr("загрузить программу из файла при запуске (R — запуск, p — редактор)",
                "load a program file at startup (R — run, p — editor)"),
    )
    parser.add_argument(
        "--program-dir",
        metavar=tr("ПАПКА", "DIR"),
        default=None,
        help=tr(f"папка для файлов программ (по умолчанию {DEFAULT_PROGRAM_DIR})",
                f"folder for program files (default {DEFAULT_PROGRAM_DIR})"),
    )
    parser.add_argument("--step-time", type=float, default=None,
                        help=tr(f"секунд на один шаг вперёд/назад (по умолчанию {DEFAULT_STEP_TIME})",
                                f"seconds per forward/back step (default {DEFAULT_STEP_TIME})"))
    parser.add_argument("--turn-time", type=float, default=None,
                        help=tr(f"секунд на один поворот (по умолчанию {DEFAULT_TURN_TIME})",
                                f"seconds per turn step (default {DEFAULT_TURN_TIME})"))
    parser.add_argument("--pause-time", type=float, default=None,
                        help=tr(f"секунд на одну паузу (по умолчанию {DEFAULT_PAUSE_TIME})",
                                f"seconds per pause unit (default {DEFAULT_PAUSE_TIME})"))
    parser.add_argument("--blink-time", type=float, default=None,
                        help=tr(f"секунд на половину мигания (по умолчанию {DEFAULT_BLINK_TIME})",
                                f"seconds per half blink (default {DEFAULT_BLINK_TIME})"))
    parser.add_argument("--max-steps", type=int, default=None,
                        help=tr("максимум команд в программе (0 — без ограничения)",
                                "maximum program steps (0 — unlimited)"))
    parser.add_argument("--log", dest="log", action="store_true", default=None,
                        help=tr("вести журнал прогонов (~/.config/apitor-control/runs.log)",
                                "keep a run journal (~/.config/apitor-control/runs.log)"))
    parser.add_argument("--no-log", dest="log", action="store_false",
                        help=tr("не вести журнал (даже если включён в config.json)",
                                "no journal (even if enabled in config.json)"))
    parser.add_argument("--verbose", action="store_true",
                        help=tr("подробный журнал (кадры, сканирование)",
                                "verbose log (frames, scanning)"))
    return parser


def _prescan_lang(argv: list[str]) -> str | None:
    """Вынуть --lang из argv до сборки парсера (справка должна быть на нём же)."""
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def main(argv=None) -> int:
    global LANG
    arglist = list(sys.argv[1:] if argv is None else argv)
    config = load_config()
    flag_lang = _prescan_lang(arglist)
    if flag_lang not in ("ru", "en"):
        flag_lang = None
    cached_lang = config.get("lang")
    if cached_lang not in ("ru", "en"):
        cached_lang = None
    LANG = flag_lang or cached_lang or "ru"

    args = build_parser().parse_args(argv)
    if args.lang and config.get("lang") != args.lang:
        config["lang"] = args.lang
        save_config(config)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("bleak").setLevel(logging.WARNING)
    try:
        profile = get_profile(args.product).with_overrides(
            left_motor=args.left_motor,
            right_motor=args.right_motor,
            flip_left=args.flip_left,
            flip_right=args.flip_right,
        )
    except ValueError as exc:
        print(tr(f"Ошибка: {exc}", f"Error: {exc}"), file=sys.stderr)
        return 2
    remote = Remote(args, profile, config)
    if args.program:
        path = Path(args.program).expanduser()
        if not remote.load_program_file(path, announce=False):
            return 2
    try:
        return asyncio.run(remote.run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
