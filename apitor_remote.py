#!/usr/bin/env python3
"""apitor_remote.py — пульт с горячими клавишами для Apitor Robot R.

Управляет роботом по Bluetooth LE через библиотеку `apitor-ble`.
Клавиши нажимаются по одной, Enter не нужен:

    q ............ подключиться         Shift+Q ...... отключиться
    w a s d ...... ехать                пробел / Esc . стоп
    ] [  (+ -) ... скорость (1..12)     1..8 ......... цвет подсветки
    0 ............ выключить подсветку
    b / B ........ мигнуть подсветкой (цвет при этом не меняется)
    e / Shift+E .. мотор 3 (аксессуар): вперёд / назад (тумблером)
    Enter ........ выполнить программу (записанный макрос или файл)
    Shift+Enter .. то же, но без пауз (Shift виден только с key-state)
    p ............ режим программы (шаги, как у Big Trak / Лунохода)
    m ............ записать макрос: делайте что угодно, Esc — стоп
    r / R ........ проехать маршрут обратно задним ходом (R — без пауз)
    t / T ........ робота развернули рукой: проехать обратно передом
    F / G ........ сохранить / загрузить программу файлом
    J ............ журнал прогонов вкл/выкл
    y ............ тест-поездка (проверить направления)
    i ............ моторы по одному (калибровка)
    k / l ........ режим движения: удержание / фиксация
    h, ? ......... справка              Ctrl+C ....... выход

Режим программы: нажмите `p` — набирайте шаги (w/a/s/d — вперёд/назад/
влево/вправо, пробел — пауза, c — цвет, b — мигнуть, цифры — число шага),
Enter — запуск. Программа пишется живой строкой; f/g — сохранить/загрузить.
Esc — вернуться в пульт (программа остаётся), x — очистить программу,
E — правка во внешнем редакторе ($EDITOR/$VISUAL, иначе nvim/nano/vi;
на время редактора горячие клавиши пульта выключены).
Файлы простые: «вперёд 5», «вправо 2», понимаются и по-русски, и по-английски.

Макрос: нажмите `m` в пульте — пульт запомнит всё, что вы делаете (движение,
свет, мигание, смену скорости), а паузы запишет ожиданием. Esc (или `m`
ещё раз) — остановить запись: макрос становится программой, его можно сразу
выполнить (Enter), сохранить файлом (f/g) и править (p, Backspace, E). Это
тот же формат программы, только у действий есть точная длительность: «вперёд
1.2с» (или «вперёд 1.2s» — пульт понимает с, s, сек, sec, секунды, seconds в
любом интерфейсе), «пауза 0.4с», а «скорость 8» в середине файла меняет
скорость по ходу. В редакторе такие шаги видны как ↑1.2с, ‖0.4с и »8; шаги и
секунды спокойно соседствуют в одной программе.

Обратный проезд: `r` — робот едет по тому же маршруту в обратном порядке
задним ходом (реверс и вперёд/назад, и влево/вправо), `t` — то же, но робота
развернули рукой на 180°, поэтому реверсится только влево/вправо. R и T (с
Shift) — то же самое, но без пауз: маршрут проезжается без остановок. Длитель-
ности каждого действия сохраняются, свет и скорость расставляются так, чтобы
каждый участок пути проехать при том же свете и на той же скорости, что и
вперёд. Программа при этом не меняется: Enter потом проедет её как обычно.

Язык интерфейса: --lang en (один раз, запоминается в config.json) или --lang ru.
Настройки (длительности шагов, журнал и т. п.) — в
~/.config/apitor-control/config.json, примеры есть в README.

Режим по умолчанию — "удержание": движок крутится, пока клавиша повторяется
(автоповтор операционной системы), и робот сам останавливается через
--hold-timeout секунд после отпускания; короткое нажатие = толчок.
Клавиши `k`/`l` выбирают режим движения (это не тумблер): `k` — удержание,
`l` — "фиксация": робот едет, пока не нажмёте стоп/другое.

Удержание работает "как в играх": пульт сам читает реальное состояние клавиш
(Linux: evdev, Windows: WinAPI) и останавливает робота в момент отпускания,
автоповтор и таймаут не нужны. Если состояние клавиш недоступно (нет прав на
/dev/input и т. п.), пульт предупреждает и переходит на авто-стоп по
--hold-timeout.

Пока клавиши читаются напрямую, зажатый Shift — буст: на время удержания
скорость становится 12, а после отпускания возвращается прежняя (Shift+Q
при этом по-прежнему отключает робота).

С флагом --tui пульт занимает весь экран: сверху состояние (робот, связь,
скорость, режим, свет), в середине — лог событий, снизу — строка программы
и подсказки. Клавиши и поведение те же; при выходе терминал возвращается
как был. Внешний редактор ($EDITOR, клавиша E) на время работы забирает
экран себе.

Примеры:

    .venv/bin/python apitor_remote.py                # Robot R, скорость 6
    .venv/bin/python apitor_remote.py --speed 9      # быстрее
    .venv/bin/python apitor_remote.py --simulate     # без Bluetooth: печать кадров
    .venv/bin/python apitor_remote.py --tui          # полноэкранный интерфейс
    .venv/bin/python apitor_remote.py --key-state-device /dev/input/event7  # одна клавиатура
    .venv/bin/python apitor_remote.py --address AA:BB:CC:DD:EE:FF
    .venv/bin/python apitor_remote.py --program programs/квадрат.txt
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
import signal
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from collections import deque
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
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PROGRAM_DIR = SCRIPT_DIR / "programs"
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
# Обратный словарь для статуса в TUI (Color -> «красный»/«red»).
COLOR_NAMES = {color: (ru, en) for color, ru, en in COLOR_BY_KEY.values()}
COLOR_NAMES[Color.OFF] = ("выкл.", "off")

# Шаг «цвет» хранит НОМЕР цвета (0 — выключить, 1..8 — клавиши подсветки):
# у Color.WHITE в библиотеке значение 10, поэтому нужен свой пересчёт.
COLOR_BY_NUMBER = {0: Color.OFF}
COLOR_BY_NUMBER.update({int(key): entry[0] for key, entry in COLOR_BY_KEY.items()})
NUMBER_BY_COLOR = {color: number for number, color in COLOR_BY_NUMBER.items()}

# Символ -> действие. Стрелки приходят как "up"/"down"/"left"/"right".
KEYMAP: dict[str, str] = {
    "q": "connect",
    "Q": "disconnect",  # Shift+Q
    "w": "fwd", "s": "back", "a": "left", "d": "right",
    "up": "fwd", "down": "back", "left": "left", "right": "right",
    " ": "stop", "esc": "stop",
    "enter": "run",  # Enter — выполнить программу (и в пульте тоже)
    "]": "speed_up", "=": "speed_up", "+": "speed_up",
    "[": "speed_down", "-": "speed_down", "_": "speed_down",
    "0": "lights_off",
    "b": "blink_led", "B": "blink_led",  # мигнуть подсветкой (в редакторе b — шаг)
    "e": "m3_fwd", "E": "m3_rev",
    "p": "prog", "P": "prog",
    "m": "record_macro", "M": "record_macro",
    # обратный проезд: строчная — с паузами, заглавная (с Shift) — без пауз
    "r": "rev_back", "R": "rev_back_np",
    "t": "rev_front", "T": "rev_front_np",
    "f": "save_prog", "F": "save_prog",
    "g": "load_prog", "G": "load_prog",
    "j": "journal", "J": "journal",
    "x": "clear_prog", "X": "clear_prog",
    "y": "test", "Y": "test",  # тест-поездка (переехала с t: t — обратный проезд)
    "i": "identify", "h": "help", "?": "help",
    "k": "hold", "K": "hold", "l": "latch", "L": "latch",
    "\x03": "quit",  # Ctrl+C (терминал в "сыром" режиме)
}
KEYMAP.update({key: f"color:{key}" for key in COLOR_BY_KEY})

# Русская раскладка: те же физические клавиши приходят кириллицей.
_LAYOUT = {
    "й": "q", "ц": "w", "у": "e", "ф": "a", "ы": "s", "в": "d", "е": "t",
    "р": "h", "д": "l", "л": "k", "о": "j", "ш": "i", "к": "r", "а": "f", "п": "g",
    "с": "c", "и": "b", "ч": "x", "з": "p", "ь": "m", "н": "y",
    "х": "[", "ъ": "]",
    "Й": "Q", "Ц": "W", "У": "E", "Ф": "A", "Ы": "S", "В": "D", "Е": "T",
    "Р": "H", "Д": "L", "Л": "K", "О": "J", "Ш": "I", "К": "R", "А": "F", "П": "G",
    "С": "C", "И": "B", "Ч": "X", "З": "P", "Ь": "M", "Н": "Y",
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
#   speed  — «скорость 8» в середине файла: сменить скорость по ходу
# У шага может быть seconds вместо числа: «вперёд 1.2с» — макрос, где действие
# длится ровно столько (шаги и секунды спокойно соседствуют в одной программе).
COUNT_KINDS = ("fwd", "back", "left", "right", "pause", "blink")

MIN_STEP_SECONDS = 0.05   # «вперёд 0.05с» — короче уже не действие
MAX_STEP_SECONDS = 600.0  # и длиннее тоже (10 минут)
STEP_PRECISION = 3        # секунды храним до миллисекунд (1.234)

_STEP_WORDS = {
    "fwd": {"ru": "вперёд", "en": "forward"},
    "back": {"ru": "назад", "en": "back"},
    "left": {"ru": "влево", "en": "left"},
    "right": {"ru": "вправо", "en": "right"},
    "pause": {"ru": "пауза", "en": "pause"},
    "color": {"ru": "цвет", "en": "color"},
    "blink": {"ru": "мигнуть", "en": "blink"},
    "speed": {"ru": "скорость", "en": "speed"},
}

# Значки для живой строки редактора: у каждого действия ровно один символ.
# Их же принимает парсер файла: «↑5 →2» == «вперёд 5 · вправо 2».
_STEP_SYMBOLS = {
    "fwd": "↑",
    "back": "↓",
    "left": "←",
    "right": "→",
    "pause": "‖",
    "blink": "✦",
    "color": "●",
    "speed": "»",
}

# Прощающий парсер: команды на русском и английском (можно вперемешку).
_STEP_SYNONYMS = {
    "вперёд": "fwd", "вперед": "fwd", "forward": "fwd", "forwards": "fwd", "ahead": "fwd",
    "up": "fwd",
    "назад": "back", "back": "back", "backward": "back", "backwards": "back",
    "down": "back",
    "влево": "left", "left": "left",
    "вправо": "right", "right": "right", "rght": "right",
    "пауза": "pause", "pause": "pause", "wait": "pause",
    "цвет": "color", "color": "color", "colour": "color",
    "мигнуть": "blink", "blink": "blink", "flash": "blink",
    # те же действия значками: «↑5» == «вперёд 5» (см. _STEP_SYMBOLS)
    "↑": "fwd", "↓": "back", "←": "left", "→": "right",
    "‖": "pause", "✦": "blink", "●": "color", "»": "speed",
}
_HEADER_SYNONYMS = {
    "повтор": "repeat", "repeat": "repeat",
    "скорость": "speed", "speed": "speed",
}

# Число в файле: «5» — пять шагов, «1.2с» (1.2s, 1.2сек, 1.2секунды) — секунды.
_NUMBER_RE = re.compile(
    r"^(\d+(?:[.,]\d+)?)(\s*(?:секунд\w*|seconds?|сек|sec|с\b|s\b))?$"
)
# Токены строки: слова, числа (с единицей времени) и значки действий.
_TOKEN_RE = re.compile(
    r"[а-яa-z]+"
    r"|\d+(?:[.,]\d+)?(?:\s*(?:секунд\w*|seconds?|сек|sec|с\b|s\b))?"
    r"|[↑↓←→‖✦●»]"
)


class Step:
    """Шаг программы (обычный класс: тесты грузят модуль через importlib).

    seconds — длительность вместо числа шагов (шаг макроса): «вперёд 1.2с».
    У color/speed/digit-шагов seconds нет.
    """
    __slots__ = ("kind", "value", "seconds")

    def __init__(self, kind: str, value: int = 1, seconds: float | None = None) -> None:
        self.kind = kind
        self.value = value
        self.seconds = seconds


def split_number(token: str) -> tuple[int | None, float | None]:
    """Токен числа: «5» → (5, None) шагов, «1.2с» → (None, 1.2) секунды."""
    match = _NUMBER_RE.match(token)
    if match is None:
        return None, None
    text, unit = match.group(1), match.group(2)
    if unit is not None or "." in text or "," in text:
        return None, float(text.replace(",", "."))
    return int(text), None


def secs_text(seconds: float) -> str:
    """Длительность для строки и файла: «1.234», «0.5», «2» (до миллисекунд)."""
    return f"{seconds:.3f}".rstrip("0").rstrip(".")


def steps_are_timed(steps) -> bool:
    """Макрос ли это: есть шаги с секундами или смена скорости по ходу."""
    return any(step.seconds is not None or step.kind == "speed" for step in steps)


def step_text(step: Step) -> str:
    """Шаг значком для строки редактора: ↑5, ‖, ●3, ↑1.2с, »12."""
    symbol = _STEP_SYMBOLS[step.kind]
    if step.seconds is not None:
        return f"{symbol}{secs_text(step.seconds)}{tr('с', 's')}"
    if step.kind in ("color", "speed") or step.value != 1:
        return f"{symbol}{step.value}"
    return symbol


# Обратный проезд: маршрут в обратном порядке с теми же длительностями.
#   back — робот едет задним ходом: реверс и «вперёд/назад», и «влево/вправо»;
#   front — робота развернули рукой: реверс только «влево/вправо».
REVERSE_MIRROR = {
    "back": {"fwd": "back", "back": "fwd", "left": "right", "right": "left"},
    "front": {"fwd": "fwd", "back": "back", "left": "right", "right": "left"},
}


def reversed_steps(editor, mode: str, *, drop_pauses: bool = False) -> list[Step]:
    """Программа обратного проезда: те же участки пути в обратном порядке.

    Длительности каждого действия сохраняются (шаги с числом превращаются в
    секунды), паузы тоже — если не попросили обратное (drop_pauses).

    Свет и скорость расставляются заново: перед каждым участком стоит ровно
    та подсветка и та скорость, при которых этот участок проезжали вперёд,
    поэтому в обратную сторону путь проезжается при том же свете.
    """
    mirror = REVERSE_MIRROR[mode]
    route: list[tuple[Step, float, int | None, int]] = []
    light: int | None = None
    speed = editor.speed
    for step in editor.steps:
        if step.kind == "color":
            light = step.value          # свет горит до следующей смены
            continue
        if step.kind == "speed":
            speed = max(SPEED_MIN, min(SPEED_MAX, step.value))
            continue
        route.append((step, editor._step_seconds(step), light, speed))
    out: list[Step] = []
    cur_light: int | None = None
    cur_speed = editor.speed
    for step, seconds, light, speed in reversed(route):
        if step.kind == "pause" and drop_pauses:
            continue
        if light is not None and light != cur_light:
            out.append(Step("color", light))
            cur_light = light
        if speed != cur_speed:
            out.append(Step("speed", speed))
            cur_speed = speed
        if step.kind == "blink":
            out.append(Step("blink", step.value))  # мигание остаётся миганием
        else:
            out.append(Step(mirror.get(step.kind, step.kind), 1,
                            round(seconds, STEP_PRECISION)))
    return out


class EditorResult:
    """Ответ редактора на клавишу: что напечатать или что сделать."""
    __slots__ = ("action", "text")

    def __init__(self, action: str, text: str = "") -> None:
        self.action = action  # line | note | warn | run | save | load | remote
        self.text = text


class _RunAbort(Exception):
    """Программа прервана (Esc — в пульт, p — в режим программы, отключение или потеря связи)."""


class RunPlan:
    """Что запускаем: готовые шаги, скорость, повтор и вид прогона.

    rev — None (обычный прогон), "back" (обратно задним ходом) или "front"
    (робота развернули рукой); drop_pauses — прогон без пауз.
    """
    __slots__ = ("steps", "speed", "repeat", "rev", "drop_pauses")

    def __init__(self, steps: list[Step], speed: int, repeat: int,
                 rev: str | None = None, drop_pauses: bool = False) -> None:
        self.steps = steps
        self.speed = speed
        self.repeat = repeat
        self.rev = rev
        self.drop_pauses = drop_pauses


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
        self.steps = [Step(s.kind, s.value, s.seconds) for s in steps]
        self.repeat = max(1, min(99, int(repeat or 1)))
        if speed is not None:
            self.speed = max(SPEED_MIN, min(SPEED_MAX, int(speed)))
        self._capture = None
        self._digit_run = ""

    def has_timed(self) -> bool:
        """Есть ли в программе шаги макроса (с секундами или сменой скорости)."""
        return steps_are_timed(self.steps)

    def _step_seconds(self, step: Step) -> float:
        if step.seconds is not None:
            return step.seconds      # макрос: точная длительность
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
        status = f"{count} · ~{secs_text(self.estimate())} {tr('с', 's')} · {tr('скор.', 'speed')} {self.speed}"
        if self.repeat > 1:
            status += f" · {tr('повтор', 'repeat')} {self.repeat}"
        return " · ".join(words) + f" ({status})"

    def serialize(self) -> str:
        """Файл программы: просто и без лишних знаков («вперёд 5», «вперёд 1.2с»)."""
        lines: list[str] = []
        if self.repeat > 1:
            lines.append(f"{tr('повтор', 'repeat')} {self.repeat}")
        lines.append(f"{tr('скорость', 'speed')} {self.speed}")
        for step in self.steps:
            word = _STEP_WORDS[step.kind][LANG]
            if step.seconds is not None:
                lines.append(f"{word} {secs_text(step.seconds)}{tr('с', 's')}")
            elif step.kind in ("color", "speed") or step.value != 1:
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
        if self.steps[-1].seconds is not None:
            self._digit_run = ""
            return EditorResult("warn", tr(
                "этот шаг задан в секундах — число его не меняет "
                "(уберите Backspace или добавьте новый шаг)",
                "this step is set in seconds — a number does not change it "
                "(remove it with Backspace or add a new step)",
            ))
        self.steps[-1].value = max(1, min(99, value))
        return EditorResult("line", self.line())

    def _add_step(self, kind: str, now: float) -> EditorResult:
        last = self.steps[-1] if self.steps else None
        if last is not None and last.kind == kind and last.seconds is None:
            last.value = min(99, last.value + 1)
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

    Понимает русский и английский, е/ё, регистр, «× x *», запятые,
    значки действий (↑↓←→‖✦●»); «#» — комментарий. Ошибки — строки с номером строки.
    Число — это шаги, а «1.2с» / «1.2s» / «1.2сек» — секунды (шаг макроса);
    «скорость N» в середине файла — смена скорости по ходу.
    """
    steps: list[Step] = []
    repeat = 1
    speed: int | None = None
    errors: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if lineno == 1:
            raw = raw.lstrip("\ufeff")
        line = raw.split("#", 1)[0].lower().replace("ё", "е")
        line = re.sub(r"(?<=\d),(?=\d)", ".", line)  # «1,2с» — десятичная запятая
        line = line.replace("×", " ").replace("*", " ").replace(",", " ")
        line = re.sub(r"x(?=\d)", " ", line)  # «вперёд x5» == «вперёд 5»
        tokens = _TOKEN_RE.findall(line)
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            kind = _STEP_SYNONYMS.get(tok)
            header = _HEADER_SYNONYMS.get(tok)
            if kind is None and header is None:
                num, secs = split_number(tok)
                if num is not None or secs is not None:
                    errors.append(tr(f"строка {lineno}: число {tok} без команды",
                                     f"line {lineno}: number {tok} without a command"))
                else:
                    errors.append(tr(f"строка {lineno}: не понимаю «{tok}»",
                                     f"line {lineno}: don't understand «{tok}»"))
                i += 1
                continue
            number: int | None = None
            seconds: float | None = None
            if i + 1 < len(tokens):
                number, seconds = split_number(tokens[i + 1])
                if number is not None or seconds is not None:
                    i += 1
            i += 1
            if header == "repeat":
                if number is None or not 1 <= number <= 99:
                    errors.append(tr(f"строка {lineno}: «{tok}» требует число 1..99",
                                     f"line {lineno}: «{tok}» needs a number 1..99"))
                else:
                    repeat = number
                continue
            if header == "speed" or kind == "speed":
                if number is None or not 1 <= number <= SPEED_MAX:
                    errors.append(tr(f"строка {lineno}: «{tok}» требует число 1..{SPEED_MAX}",
                                     f"line {lineno}: «{tok}» needs a number 1..{SPEED_MAX}"))
                elif steps:
                    steps.append(Step("speed", number))  # смена скорости по ходу
                else:
                    speed = number                       # скорость всей программы
                continue
            if kind == "color":
                if seconds is not None:
                    errors.append(tr(f"строка {lineno}: «цвет» не бывает в секундах",
                                     f"line {lineno}: «color» is not measured in seconds"))
                    continue
                if number is None or not 0 <= number <= 8:
                    errors.append(tr(f"строка {lineno}: «{tok}» требует число 0..8",
                                     f"line {lineno}: «{tok}» needs a number 0..8"))
                    continue
            elif seconds is not None:
                if kind == "blink":
                    errors.append(tr(
                        f"строка {lineno}: «мигнуть» не бывает в секундах",
                        f"line {lineno}: «blink» is not measured in seconds",
                    ))
                    continue
                if not MIN_STEP_SECONDS <= seconds <= MAX_STEP_SECONDS:
                    errors.append(tr(
                        f"строка {lineno}: «{tok} {secs_text(seconds)}с» — от "
                        f"{secs_text(MIN_STEP_SECONDS)} до {secs_text(MAX_STEP_SECONDS)} с",
                        f"line {lineno}: «{tok} {secs_text(seconds)}s» — from "
                        f"{secs_text(MIN_STEP_SECONDS)} to {secs_text(MAX_STEP_SECONDS)} s",
                    ))
                    continue
                steps.append(Step(kind, 1, round(seconds, STEP_PRECISION)))
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
# Макрос: те же действия, что в программе, но с длительностями
# --------------------------------------------------------------------------- #


class MacroRecorder:
    """Запись макроса: пульт зовёт recorder на каждое действие.

    Движение пишется отрезками: пока робот едет, отрезок открыт, а на
    остановке закрывается с точной длительностью («вперёд 1.2с»). Паузы
    между действиями становятся «ожиданием», свет и мигание — обычными
    шагами, смена скорости на ходу рвёт отрезок и попадает в макрос.
    """

    MIN_ACTION = 0.05  # 50 мс: короче — дребезг, а не действие
    MIN_WAIT = 0.1     # паузы короче 100 мс не пишем: только шумят
    PRECISION = 3      # до миллисекунд: у key-state точность ввода как раз ~1 мс

    def __init__(self) -> None:
        self.steps: list[Step] = []
        self._speed = DEFAULT_SPEED
        self._kind: str | None = None   # открытый отрезок движения
        self._started = 0.0             # когда он начался
        self._idle_since: float | None = None  # с какого момента стоим

    def start(self, speed: int) -> None:
        """Начать запись заново (текущая скорость — стартовая)."""
        self.steps = []
        self._speed = speed
        self._kind = None
        self._started = 0.0
        self._idle_since = None

    def move(self, kind: str | None, now: float, speed: int) -> None:
        """Поехали (kind — fwd/back/left/right) или остановились (None)."""
        was_moving = self._close(now)
        if kind is None:
            return
        if not was_moving:
            self._flush_wait(now)  # стояли — это ожидание
        self._note_speed(speed)
        self._kind = kind
        self._started = now

    def event(self, kind: str, value: int, now: float) -> None:
        """Мгновенное действие (цвет, мигание): движение при этом не рвётся."""
        moving = self._kind
        if not self._close(now):
            self._flush_wait(now)
        self.steps.append(Step(kind, value))
        if moving is not None:
            self._kind = moving     # свет сменился на ходу — едем дальше
            self._started = now
            self._idle_since = None
        else:
            self._idle_since = now

    def speed_changed(self, speed: int, now: float) -> None:
        """Скорость поменяли на ходу: отрезок рвётся на этом месте."""
        if self._kind is None or speed == self._speed:
            return
        moving = self._kind
        self._close(now)
        self.steps.append(Step("speed", speed))
        self._speed = speed
        self._kind = moving
        self._started = now
        self._idle_since = None

    def stop(self, now: float) -> list[Step]:
        """Остановить запись: отрезок закрывается, пауза в конце не пишется."""
        self._close(now)
        self._idle_since = None
        return self.steps

    # -- внутреннее ---------------------------------------------------------- #
    def _note_speed(self, speed: int) -> None:
        """Скорость меняли, пока стояли: шаг ставится перед движением."""
        if speed != self._speed:
            self.steps.append(Step("speed", speed))
            self._speed = speed

    def _close(self, now: float) -> bool:
        """Закрыть отрезок движения; True — он был (и, может быть, записан)."""
        if self._kind is None:
            return False
        kind, started = self._kind, self._started
        self._kind = None
        self._idle_since = now
        duration = now - started
        if duration >= self.MIN_ACTION:
            self.steps.append(Step(kind, 1, round(duration, self.PRECISION)))
        return True

    def _flush_wait(self, now: float) -> None:
        if self._idle_since is None:
            return
        duration = now - self._idle_since
        self._idle_since = None
        if duration >= self.MIN_WAIT:
            self.steps.append(Step("pause", 1, round(duration, self.PRECISION)))


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

    def __init__(self, echo=None) -> None:
        self._connected = False
        # echo — чем печатать кадры (в TUI они попадают в лог, а не в терминал)
        self._echo = echo or (lambda text: print(text, flush=True))

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
        self._echo(f"  [sim] -> {data.hex()}")

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
# Полноэкранный интерфейс (--tui)
# --------------------------------------------------------------------------- #


def _truncate(text: str, width: int) -> str:
    """Обрезать строку по ширине терминала (место на многоточие оставляем)."""
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def _enable_windows_ansi() -> None:
    """Включить ANSI-последовательности в консоли Windows (иначе — мусор)."""
    if not IS_WINDOWS:
        return
    with contextlib.suppress(Exception):
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # ENABLE_PROCESSED_OUTPUT | ENABLE_WRAP_AT_EOL_OUTPUT | VT-последовательности
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)


class Tui:
    """Полноэкранный интерфейс пульта (--tui): статус, лог, подсказки.

    Рисуется ANSI-последовательностями на альтернативном экране: сверху
    состояние (робот, связь, скорость, режим, свет), в середине — лог
    событий, снизу — строка программы и подсказки (или приглашение ввода).
    Сообщения приходят в note() вместо обычной печати, поэтому вывод не
    разъезжается по экрану; при выходе терминал возвращается как был.
    """

    MAX_LOG = 400  # сколько строк лога помнить
    TAG_COLORS = {
        "err": "31", "warn": "33", "ok": "32", "info": "36", "hint": "2;37",
        "robot": "36", "motor": "35", "test": "36", "led": "1;33",
        "speed": "1;36", "mode": "1;36", "help": "2;37", "prog": "1;34",
        "save": "34", "load": "34", "log": "2;37", "run": "1;35", "dbg": "2;37",
        "rec": "1;31",
    }

    def __init__(self, remote: Remote) -> None:
        self.remote = remote
        self.log: deque[tuple[str | None, str]] = deque(maxlen=self.MAX_LOG)
        self.active = False
        self._resized = False
        self._tick: asyncio.Task | None = None
        self._old_winch = None
        self._lock = threading.Lock()  # кадр рисуется целиком (в т. ч. из потоков)

    # -- экран --------------------------------------------------------------- #
    def start(self) -> None:
        """Занять экран терминала (альтернативный экран) и нарисовать кадр."""
        if self.active:
            return
        _enable_windows_ansi()
        with self._lock:
            sys.stdout.write("\x1b[?1049h\x1b[?25l")  # альтернативный экран, курсор скрыт
            sys.stdout.flush()
        self.active = True
        if hasattr(signal, "SIGWINCH"):
            with contextlib.suppress(ValueError, OSError):
                self._old_winch = signal.signal(signal.SIGWINCH, self._on_winch)
        try:
            self._tick = asyncio.get_running_loop().create_task(self._ticker())
        except RuntimeError:  # вне цикла событий: TUI просто не следит за размером
            self._tick = None
        self.redraw()

    def stop(self) -> None:
        """Вернуть обычный экран терминала и видимый курсор."""
        if not self.active:
            return
        self.active = False
        if self._tick is not None:
            self._tick.cancel()
            self._tick = None
        if self._old_winch is not None and hasattr(signal, "SIGWINCH"):
            with contextlib.suppress(ValueError, OSError):
                signal.signal(signal.SIGWINCH, self._old_winch)
            self._old_winch = None
        with self._lock:
            sys.stdout.write("\x1b[?25h\x1b[?1049l")
            sys.stdout.flush()

    def _on_winch(self, *_args) -> None:
        self._resized = True

    async def _ticker(self) -> None:
        """Перерисовать кадр, если терминал поменял размер."""
        with contextlib.suppress(asyncio.CancelledError):
            while True:
                await asyncio.sleep(0.2)
                if self._resized:
                    self._resized = False
                    self.redraw()

    def note(self, tag: str | None, text: str) -> None:
        """Положить сообщение в лог TUI и сразу показать его."""
        self.note_lines(((tag, text),))

    def note_lines(self, lines) -> None:
        """Добавить в лог сразу несколько строк (справка) — одна перерисовка."""
        for tag, text in lines:
            self.log.append((tag, text))
        self.redraw()

    def redraw(self) -> None:
        """Нарисовать кадр целиком: шапка, лог, программа, подсказки."""
        if not self.active:
            return
        size = shutil.get_terminal_size((80, 24))
        width = max(20, size.columns)
        height = max(4, size.lines)
        rows = self._render(width, height)
        chunks = []
        for number, row in enumerate(rows[:height], 1):
            chunks.append(f"\x1b[{number};1H\x1b[2K{row}")
        chunks.append(f"\x1b[{height};1H\x1b[J\x1b[?25l")
        with self._lock:
            try:
                sys.stdout.write("".join(chunks))
                sys.stdout.flush()
            except (OSError, ValueError):  # терминал пропал — печатать больше некуда
                self.active = False

    # -- сборка кадра -------------------------------------------------------- #
    def _render(self, width: int, height: int) -> list[str]:
        program = self._program_line()
        log_rows = max(1, height - 2 - (1 if program else 0))
        log = self._log_lines(width)[-log_rows:]
        rows = [self._bar(self._status_line(), width, "7")]
        rows += [""] * max(0, log_rows - len(log))  # лог растёт снизу
        rows += log
        if program:
            rows.append(f"\x1b[2m{_truncate(program, width)}\x1b[0m")
        rows.append(self._bar(self._prompt_line(), width,
                              "7" if self.remote.prompt is not None else "2"))
        return rows

    @staticmethod
    def _bar(text: str, width: int, style: str) -> str:
        """Строка во всю ширину — шапка и подвал TUI."""
        return f"\x1b[{style}m{_truncate(text, width).ljust(width)}\x1b[0m"

    def _status_line(self) -> str:
        remote = self.remote
        link = (tr("подключён", "connected") if remote._is_connected()
                else tr("нет связи", "no link"))
        parts = [f"Apitor {remote.profile.name}", link,
                 tr(f"скор. {remote.speed}", f"speed {remote.speed}")
                 + ("+" if remote._boost_speed is not None else "")]
        if remote.mode == "remote":
            parts.append(tr("фиксация", "latched") if remote.latched
                         else tr("удержание", "hold"))
        else:
            parts.append(tr("программа", "program") if remote.mode == "editor"
                         else tr("прогон", "run"))
        if remote.recording:
            parts.append(tr(f"запись {len(remote.macro.steps)}",
                            f"rec {len(remote.macro.steps)}"))
        if remote.key_state:
            parts.append("key-state")
        if remote.mode == "run" and remote._run_total:
            parts.append(f"{remote._run_step}/{remote._run_total}")
        name = COLOR_NAMES.get(remote.led_color)
        if name:
            parts.append(tr(f"свет: {name[0]}", f"light: {name[1]}"))
        return " · ".join(parts)

    def _program_line(self) -> str | None:
        """Строка программы: в редакторе — живая, иначе — что загружено."""
        remote = self.remote
        if remote.recording:
            steps = remote.macro.steps
            if not steps:
                return tr("[rec] … делайте что-нибудь (Esc — стоп)",
                          "[rec] … do something (Esc — stop)")
            text = " · ".join(step_text(step) for step in steps[-8:])
            return f"[rec] {text} ({len(steps)} {steps_word(len(steps))})"
        if not remote.editor.steps:
            return None
        if remote.mode == "editor":
            return remote.editor.line()
        n = len(remote.editor.steps)
        text = " · ".join(step_text(step) for step in remote.editor.steps)
        return f"[prog] {text} ({n} {steps_word(n)})"

    def _prompt_line(self) -> str:
        """Нижняя строка: приглашение ввода или подсказки режима."""
        remote = self.remote
        prompt = remote.prompt
        if prompt is None:
            return remote._keys_hint()
        tag = "load" if prompt.get("kind") == "load" else "save"
        title = prompt.get("title") or ""
        if prompt.get("kind") == "confirm":
            return f"[{tag}] {title}"
        return f"[{tag}] {title}: {prompt.get('text', '')}▏"

    def _log_lines(self, width: int) -> list[str]:
        """Строки лога с переносом по ширине и цветом по тегу."""
        wrapper = textwrap.TextWrapper(
            width=width, subsequent_indent="  ",
            replace_whitespace=False, drop_whitespace=False, break_long_words=True,
        )
        out: list[str] = []
        for tag, text in self.log:
            prefix = f"[{tag}] " if tag else ""
            color = self.TAG_COLORS.get(tag or "")
            start, reset = (f"\x1b[{color}m", "\x1b[0m") if color else ("", "")
            for line in wrapper.wrap(prefix + text) or [prefix]:
                out.append(f"{start}{_truncate(line, width)}{reset}")
        return out


# --------------------------------------------------------------------------- #
# Пульт
# --------------------------------------------------------------------------- #


class Remote:
    """Состояние пульта: подключение, движение, свет, режим и обработка клавиш."""

    CONNECT_TIMEOUT = 8.0  # сколько ждать прямой коннект по известному адресу
    SEND_DEBOUNCE = 0.06  # антидребезг команд движения, с
    RUN_TICK = 0.02       # шаг проверки паузы/прерывания во время прогона, с

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
        self.want_tui = bool(getattr(args, "tui", False))  # --tui: полноэкранный режим
        self.tui: Tui | None = None

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
        self.key_state = False            # слежение за реальными клавишами включилось
        self.key_state_devices = [        # --key-state-device: слушать только эти пути
            str(p) for p in (getattr(args, "key_state_device", None) or [])
        ]
        self._held_moves: list[str] = []  # зажатые сейчас направления (key-state)
        self._boost_speed: int | None = None  # Shift-буст: скорость до нажатия
        self._boost_held = 0                  # сколько Shift-клавиш сейчас зажато
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
        self.macro = MacroRecorder()  # запись макроса (m … Esc)
        self.recording = False
        self._rec_shown = 0           # сколько шагов макроса уже показано в логе
        self._run_task: asyncio.Task | None = None
        self._run_plan: RunPlan | None = None  # что именно запущено (шаги, повтор, вид)
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
    def _emit(self, text: str, end: str = "\n", tag: str | None = None) -> None:
        """Печать; в TUI — в лог, во время внешнего редактора — в буфер.

        С тегом (tag) печатается «[тег] текст», а в TUI тег идёт в цвет
        и в префикс строки лога.
        """
        if self._external_editor.is_set():
            self._pending_output.append((text, end, tag))
            return
        if self.tui is not None and self.tui.active:
            if end != "":  # куски приглашения TUI рисует сама
                self.tui.note(tag, text)
            return
        self._print_line(f"[{tag}] {text}" if tag else text, end)

    @staticmethod
    def _print_line(text: str, end: str = "\n") -> None:
        try:
            print(text, end=end, flush=True)
        except UnicodeEncodeError:  # старые консоли Windows
            print(text.encode("ascii", "replace").decode("ascii"), end=end, flush=True)

    def _flush_pending_output(self) -> None:
        pending, self._pending_output = self._pending_output, []
        for text, end, tag in pending:
            if self.tui is not None and self.tui.active:
                if end != "":
                    self.tui.note(tag, text)
            else:
                self._print_line(f"[{tag}] {text}" if tag else text, end)

    def _out(self, text: str, end: str = "\n") -> None:
        """Печать без [тега] (строки приглашений, эхо ввода)."""
        self._emit(text, end=end)

    def _say(self, tag: str, message: str) -> None:
        self._emit(message, tag=tag)

    def _dbg(self, message: str) -> None:
        if not self.verbose:
            return
        if self.tui is not None and self.tui.active:  # не рвать кадр TUI
            self.tui.note("dbg", message)
            return
        print(f"[dbg] {message}", file=sys.stderr, flush=True)

    def _sim_echo(self, text: str) -> None:
        """Кадры --simulate: как обычная строка вывода (в TUI — в лог)."""
        self._emit(text)

    # -- полноэкранный интерфейс (--tui) ------------------------------------- #
    def _tui_start(self) -> None:
        """Включить TUI, если он запрошен (--tui)."""
        if not self.want_tui or self.tui is not None:
            return
        self.tui = Tui(self)
        self.tui.start()

    def _tui_stop(self) -> None:
        """Убрать TUI: терминал возвращается к обычному виду."""
        if self.tui is not None:
            self.tui.stop()
            self.tui = None

    def _tui_pause(self) -> None:
        """Временно уйти с альтернативного экрана (внешний редактор)."""
        if self.tui is not None and self.tui.active:
            self.tui.stop()

    def _tui_resume(self) -> None:
        """Вернуться в TUI после паузы (лог сохраняется)."""
        if self.tui is not None and not self.tui.active:
            self.tui.start()

    def _tui_touch(self) -> None:
        """Перерисовать TUI после обработки клавиши."""
        if self.tui is not None and self.tui.active:
            self.tui.redraw()

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
            if item in ("quit", "\x03"):
                quit_seen = True
        if quit_seen:
            self.keys.put_nowait("\x03")  # Ctrl+C не теряется на долгой операции

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
        if self.recording:
            self.macro.move(None, time.monotonic(), self.speed)  # закрыть отрезок
            self._stop_recording()
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
                robot = SimRobot(self._sim_echo)
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
        self._stop_recording()  # макрос, если записывали, останется в пульте
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
        if self.recording:
            self.macro.move(move, self.last_input, self.speed)
            self._show_recorded()
        self._schedule_send()

    async def _stop(self, reason: str) -> None:
        if not self._is_connected():
            self._say("warn", tr("нет подключения — нажмите q",
                                 "not connected — press q"))
            return
        self.move = "stop"
        self.m3_dir = None
        if self.recording:
            self.macro.move(None, time.monotonic(), self.speed)
            self._show_recorded()
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
            number = NUMBER_BY_COLOR.get(color)
            if number is not None:
                self._rec_event("color", number)

    async def _led_blink(self) -> None:
        """B: мигнуть подсветкой, не меняя её состояние («выкл.» так и остаётся)."""
        if not self._is_connected():
            self._say("warn", tr("нет подключения — нажмите q",
                                 "not connected — press q"))
            return
        base = self.led_color
        flash = Color.WHITE if base == Color.OFF else Color.OFF
        if not await self._call(self.robot.all_leds, flash):
            return
        await asyncio.sleep(self.blink_time)
        if await self._call(self.robot.all_leds, base):
            self._say("led", tr("подсветка мигнула", "the light blinked"))
            self._rec_event("blink", 1)

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

    def _on_latch(self, latched: bool) -> None:
        """k/l: выбрать режим движения — удержание (k) или фиксацию (l)."""
        self.latched = latched
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

    # -- key-state: реальное состояние клавиш -------------------------------- #
    async def _enable_key_state(self) -> None:
        """Включить слежение за реальными клавишами (пробуем всегда при старте).

        Если не вышло (нет доступа к /dev/input, другая ОС) — предупреждаем
        и работаем как раньше: удержание с авто-стопом по --hold-timeout.
        """
        backend, error = make_key_state_backend(
            self._on_key_state, self._key_state_lost, self.key_state_devices or None
        )
        if backend is None:
            self._say("warn", tr(f"key-state недоступен: {error}; работает обычное удержание",
                                 f"key-state unavailable: {error}; using the usual hold mode"))
            return
        error = await backend.start()
        if error is not None:
            self._say("warn", tr(f"key-state не включился: {error}; работает обычное удержание",
                                 f"key-state did not start: {error}; using the usual hold mode"))
            return
        self._keys_backend = backend
        self.key_state = True

    async def _on_key_state(self, action: str, pressed: bool) -> None:
        """Нажал/отпустил с реальной клавиатуры (key-state)."""
        if action == "boost":
            self._on_boost(pressed)
            return
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

    def _on_boost(self, pressed: bool) -> None:
        """Shift: пока зажат — скорость 12 (только в пульте), отпустил — прежняя.

        Shift-клавиш две; буст держится, пока зажата хотя бы одна.
        """
        if not pressed:
            self._boost_held = max(0, self._boost_held - 1)
            if self._boost_held == 0:
                self._boost_release()
            return
        self._boost_held += 1
        if self._boost_speed is not None:
            return  # буст уже идёт — второй Shift ничего не меняет
        if self.mode != "remote" or self.prompt is not None:
            return  # буст — только в пульте
        self._boost_speed = self.speed
        if self.speed != SPEED_MAX:
            self.speed = SPEED_MAX
            self._say("speed", tr(
                f"буст: скорость {SPEED_MAX} (отпустите Shift — вернётся {self._boost_speed})",
                f"boost: speed {SPEED_MAX} (release Shift — back to {self._boost_speed})",
            ))
            self._apply_speed_if_moving()

    def _boost_release(self) -> None:
        """Отпустить буст: вернуть скорость, если её не меняли руками при зажатом Shift."""
        if self._boost_speed is None:
            return
        was = self._boost_speed
        self._boost_speed = None
        if self.speed == SPEED_MAX and was != SPEED_MAX:
            self.speed = was
            self._say("speed", tr(f"скорость как была: {was}",
                                  f"speed is back to {was}"))
            self._apply_speed_if_moving()

    def _shift_held(self) -> bool:
        """Зажат ли Shift (виден только с key-state: это клавиша буста).

        Нужен для Shift+Enter: прогон программы без пауз.
        """
        return self._boost_held > 0

    def _apply_speed_if_moving(self) -> None:
        if self._is_connected() and self.move != "stop":
            self._schedule_send()  # применить новую скорость на ходу
        if self.recording:
            # смена скорости на ходу попадает в макрос (стоя — перед движением)
            self.macro.speed_changed(self.speed, time.monotonic())
            self._show_recorded()

    def _key_state_lost(self, reason: str) -> None:
        """Backend сломался на ходу: остановиться и вернуться к таймауту."""
        if not self.key_state:
            return
        self.key_state = False
        self._held_moves.clear()
        self._boost_held = 0
        self._boost_release()
        self.last_input = time.monotonic()
        self._say("warn", tr(f"key-state отключился ({reason}) — дальше обычное удержание",
                             f"key-state stopped ({reason}) — falling back to the usual hold mode"))
        if self._is_connected() and self.move != "stop" and self._loop is not None:
            self._loop.create_task(self._stop(tr("key-state отключился", "key-state stopped")))

    # -- запись макроса ------------------------------------------------------ #
    async def _toggle_recording(self) -> None:
        """M: начать запись макроса или закончить её."""
        if self.recording:
            self._stop_recording()
            return
        if self.mode != "remote":
            self._say("warn", tr("запись макроса — только в пульте (Esc — назад)",
                                 "macro recording works only in remote mode (Esc — back)"))
            return
        if not self._is_connected():
            self._say("warn", tr("запись макроса: сначала подключитесь (q)",
                                 "recording a macro: connect first (q)"))
            return
        self.macro.start(self.speed)
        self.recording = True
        self._rec_shown = 0
        self._say("rec", tr(
            "запись макроса: езда, свет, скорость — всё запишется, паузы станут "
            "ожиданием; Esc или m — стоп",
            "recording a macro: driving, light, speed are all recorded, pauses "
            "become waits; Esc or m — stop",
        ))

    def _stop_recording(self) -> None:
        """Закончить запись: макрос становится «последней программой» (R)."""
        if not self.recording:
            return
        steps = self.macro.stop(time.monotonic())
        self.recording = False
        if not steps:
            self._say("rec", tr("запись остановлена — ничего не записалось",
                                "recording stopped — nothing was recorded"))
            return
        self.editor.set_program(steps, 1, self.speed)
        self._draft_loaded = True
        self.program_name = None  # это новый макрос, а не прежний файл
        n = len(steps)
        self._say("rec", tr(
            f"макрос записан: {n} {steps_word(n)} · {secs_text(self.editor.estimate())} с — "
            "Enter — проехать, r/t — обратно, f — сохранить, p — править",
            f"macro recorded: {n} {steps_word(n)} · {secs_text(self.editor.estimate())} s — "
            "Enter — drive, r/t — back, f — save, p — edit",
        ))
        self._say("prog", self.editor.line())

    def _rec_event(self, kind: str, value: int) -> None:
        """Свет/мигание во время записи — шаг макроса."""
        if not self.recording:
            return
        self.macro.event(kind, value, time.monotonic())
        self._show_recorded()

    def _show_recorded(self) -> None:
        """Показать в логе то, что уже записалось (живая лента записи)."""
        steps = self.macro.steps
        while self._rec_shown < len(steps):
            self._say("rec", step_text(steps[self._rec_shown]))
            self._rec_shown += 1

    def _keys_hint(self) -> str:
        """Короткая строка подсказок для текущего режима (баннер и TUI)."""
        if self.recording:
            return tr(
                "запись макроса: ездите и светите как обычно · Esc или m — стоп",
                "recording a macro: drive and light as usual · Esc or m — stop",
            )
        if self.mode == "editor":
            return self._prog_hint()
        if self.mode == "run":
            return tr("пробел — пауза/продолжить · Esc — стоп · p — редактор программы",
                      "space — pause/resume · Esc — stop · p — program editor")
        return tr("q — подключиться · Shift+Q — отключиться · w/a/s/d — ехать · "
                  "Enter — пуск · пробел — стоп · m — макрос · p — программа · "
                  "r/t — обратно · h — все клавиши · Ctrl+C — выход",
                  "q — connect · Shift+Q — disconnect · w/a/s/d — drive · "
                  "Enter — run · space — stop · m — macro · p — program · "
                  "r/t — drive back · h — all keys · Ctrl+C — quit")

    def _print_lines(self, lines) -> None:
        """Напечатать готовые строки (справка): в TUI они идут в лог."""
        if self.tui is not None and self.tui.active:
            self.tui.note_lines((None, line) for line in lines)
            return
        for line in lines:
            print(line, flush=True)

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
                if self.key_state
                else tr(f"удержание (авто-стоп через {self.hold_timeout:g} с)",
                        f"hold (auto-stop {self.hold_timeout:g} s after release)")
            )
        )
        self._say("info", tr(f"скорость {self.speed}, режим: {mode}",
                             f"speed {self.speed}, mode: {mode}"))
        self._say("hint", self._keys_hint())

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
                "  Enter         run the program (a recorded macro or a loaded file)",
                "  Shift+Enter   run it without pauses (Shift is only visible)",
                "                with key-state on)",
                "  ] [  or + -  speed up / down (1..12)",
                "  Shift (hold)  boost: speed 12, release — the previous speed",
                "                (needs key-state; Shift+Q still disconnects)",
                "  1..8          light: 1 red, 2 orange, 3 yellow, 4 green,",
                "                5 cyan, 6 blue, 7 purple, 8 white",
                "  0             lights off",
                "  b / B         blink the light (its color is kept)",
                "  e / Shift+E   motor 3 (accessory): forward / back — toggle",
                "  p             program mode: enter steps, run, files",
                "  m             record a macro: press m, do anything, Esc — stop",
                "                (actions are timed, pauses become waits)",
                "  x             clear the program (stay in the current mode)",
                "  r / R         drive the route back: r — driving backwards,",
                "                R — the same without pauses",
                "  t / T         the robot was turned around by hand: t — drive it",
                "                back, T — the same without pauses",
                "  F / G         save / load a program file",
                "  J             toggle the run journal",
                "  y             test drive: forward, back, left, right",
                "  i             spin motors 1, 2, 3 one by one (calibration)",
                "  k / l         mode: hold (auto-stop) / latched",
                "  h, ?          this help              Ctrl+C — quit",
                "",
                "calibration (if the robot drives the wrong way), at launch:",
                "  --flip-left / --flip-right      flip the corresponding wheel",
                "  --left-motor 2 --right-motor 1  swap the wheels",
                "",
                "hold mode: keys are read directly (game style) — the robot",
                "stops the moment the key is released; without access to",
                "/dev/input (Linux) or WinAPI (Windows) — auto-stop by --hold-timeout",
                "  --key-state-device /dev/input/event7  watch one keyboard only",
            )
        else:
            lines = (
                "  q             подключиться (поиск или кэш адреса)",
                "  Shift+Q       отключиться",
                "  w / s         вперёд / назад          (стрелки ↑ ↓ тоже)",
                "  a / d         разворот влево/вправо   (стрелки ← → тоже)",
                "  пробел, Esc   СТОП (мгновенно всё)",
                "  Enter         выполнить программу (записанный макрос или файл)",
                "  Shift+Enter   то же, но без пауз (Shift виден только с key-state)",
                "  ] [  или + -  скорость больше / меньше (1..12)",
                "  Shift зажать  буст: скорость 12, отпустить — прежняя скорость",
                "                (нужен key-state; Shift+Q по-прежнему отключает)",
                "  1..8          подсветка: 1 красный, 2 оранжевый, 3 жёлтый,",
                "                4 зелёный, 5 голубой, 6 синий, 7 фиолетовый, 8 белый",
                "  0             выключить подсветку",
                "  b / B         мигнуть подсветкой (цвет не меняется)",
                "  e / Shift+E   мотор 3 (аксессуар, если есть): вперёд / назад — тумблер",
                "  p             режим программы: набор шагов, запуск, файлы",
                "  m             записать макрос: нажмите m, делайте что угодно, Esc — стоп",
                "                (действия записываются с секундами, паузы — как ожидание)",
                "  x             очистить программу (режим не меняется)",
                "  r / R         проехать маршрут обратно: r — задним ходом,",
                "                R — то же самое, но без пауз",
                "  t / T         робота развернули рукой: t — проехать обратно передом,",
                "                T — то же самое, но без пауз",
                "  F / G         сохранить / загрузить программу файлом",
                "  J             журнал прогонов вкл/выкл",
                "  y             тест-поездка: вперёд, назад, влево, вправо",
                "  i             крутить моторы 1, 2, 3 по очереди (калибровка)",
                "  k / l         режим: удержание (авто-стоп) / фиксация",
                "  h, ?          эта справка            Ctrl+C — выход",
                "",
                "калибровка (если робот едет не туда), указывается при запуске:",
                "  --flip-left / --flip-right      развернуть соответствующее колесо",
                "  --left-motor 2 --right-motor 1  поменять колёса местами",
                "",
                "удержание: клавиши читаются напрямую (как в играх) — робот",
                "встаёт в момент отпускания; без доступа к /dev/input (Linux) или",
                "WinAPI (Windows) — авто-стоп по --hold-timeout",
                "  --key-state-device /dev/input/event7  слушать одну клавиатуру",
            )
        self._print_lines(lines)

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
                "  (macro)       timed steps: ↑1.2s — forward 1.2 s (1.2с, 1.2sec too);",
                "                »8 — change the speed from here (a recorded macro)",
                "  ] [ + - = _   speed; digits right after set it exactly: ]12",
                "  r             program repeat +1 (r5 — exactly 5 times)",
                "  Backspace     delete the last step",
                "  x             clear the program (stay in this mode)",
                "  E             edit the program in $EDITOR",
                "  Enter         run",
                "  Shift+Enter   run without pauses (needs key-state)",
                "  R / T         drive the route back: backwards / robot turned",
                "                (with Shift — the same without pauses)",
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
                "  (макрос)      шаги с секундами: ↑1.2с — вперёд 1.2 с (можно 1.2s, 1.2сек);",
                "                »8 — сменить скорость с этого места (запись макроса)",
                "  ] [ + - = _   скорость; цифры сразу после — точное значение: ]12",
                "  r             повтор программы +1 (r5 — ровно 5 раз)",
                "  Backspace     удалить последний шаг",
                "  x             очистить программу (остаться в этом режиме)",
                "  E             редактировать программу в $EDITOR",
                "  Enter         запустить",
                "  Shift+Enter   запустить без пауз (нужен key-state)",
                "  R / T         проехать маршрут обратно: задним ходом / развернув",
                "                робота (с Shift — то же самое, но без пауз)",
                "  f / g         сохранить / загрузить программу",
                "  Esc           назад в пульт (программа остаётся)",
                "  h, ?          эта справка (Ctrl+C — выход)",
            )
        self._print_lines(lines)

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
        self._print_lines(lines)

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
        if self.mode == "editor" and action in ("test", "identify", "m3_fwd", "m3_rev",
                                                "hold", "latch", "blink_led"):
            return True
        # Во время записи макроса программа, файлы и калибровка не трогаются:
        # сначала надо остановить запись (Esc или m).
        if self.recording and action in ("prog", "run", "save_prog", "load_prog",
                                         "clear_prog", "test", "identify",
                                         "rev_back", "rev_back_np",
                                         "rev_front", "rev_front_np"):
            self._say("rec", tr("идёт запись макроса — сначала Esc (стоп)",
                                "a macro is being recorded — press Esc first"))
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
        elif action == "blink_led":
            await self._led_blink()
        elif action.startswith("color:"):
            entry = COLOR_BY_KEY[action.split(":", 1)[1]]
            await self._set_led(entry[0], entry[2] if LANG == "en" else entry[1])
        elif action == "m3_fwd":
            await self._on_m3(Direction.D1, "вперёд", "forward")
        elif action == "m3_rev":
            await self._on_m3(Direction.D2, "назад", "back")
        elif action == "hold":
            self._on_latch(False)
        elif action == "latch":
            self._on_latch(True)
        elif action == "prog":
            await self._on_prog_key()
        elif action == "record_macro":
            await self._toggle_recording()
        elif action == "run":
            await self._on_run_key()
        elif action.startswith("rev_"):
            await self._on_reverse_key(action)
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
            "Enter — запуск (с Shift — без пауз) · R/T — обратно · x — очистить · "
            "E — редактор ($EDITOR) · Esc — пульт · f/g — файл · h — справка",
            "w/a/s/d — steps · 0..9 — number · c color · b blink · space pause · "
            "] [ — speed (digits right after: ]12) · r — repeat · Backspace — delete step · "
            "Enter — run (Shift — without pauses) · R/T — drive back · x — clear · "
            "E — editor ($EDITOR) · Esc — remote · f/g — file · h — help",
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
        self._tui_pause()  # внешнему редактору нужен обычный экран
        try:
            await asyncio.to_thread(subprocess.run, cmd + [str(path)])
        except Exception as exc:  # noqa: BLE001 — редактор может не запуститься
            self._tui_resume()
            self._say("err", tr(f"редактор не запустился: {exc}",
                                f"the editor did not start: {exc}"))
            self._resume_terminal_after_editor(raw)
            self._external_editor.clear()
            self._flush_pending_output()
            with contextlib.suppress(OSError):
                path.unlink()
            return
        self._tui_resume()
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
        if self.recording and key == "esc":
            await self._stop_if_moving(tr("запись макроса", "macro recording"))
            self._stop_recording()  # Esc (или m) — стоп, и макрос готов
            return True
        if key == "enter" and self._shift_held():
            await self._on_run_key(drop_pauses=True)  # Shift+Enter — без пауз
            return True
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
        if self.tui is not None and self.tui.active:
            self.prompt = None
            self.tui.redraw()
            return
        print(flush=True)
        self.prompt = None

    async def _open_save_prompt(self) -> None:
        if self.editor.is_empty():
            self._say("warn", tr("нечего сохранять — программа пуста",
                                 "nothing to save — the program is empty"))
            return
        await self._stop_if_moving(tr("сохранение программы", "saving the program"))
        stamp = time.strftime("%Y-%m-%d-%H%M")
        default = self.program_name or self._default_file_name(stamp)
        self.prompt = {"kind": "save", "text": "", "default": default,
                       "title": f"{tr('имя файла', 'file name')} [{default}]"}
        self._prompt_write(f"[save] {tr('имя файла', 'file name')} [{default}]: ")

    def _default_file_name(self, stamp: str) -> str:
        """Имя по умолчанию: у макроса — «макрос-…», у программы — «программа-…»."""
        if self.editor.has_timed():
            return tr(f"макрос-{stamp}.txt", f"macro-{stamp}.txt")
        return tr(f"программа-{stamp}.txt", f"program-{stamp}.txt")

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
                self._say("hint", tr("Enter — запустить · r/t — обратно · p — редактор",
                                     "Enter — run · r/t — drive back · p — editor"))
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
        self.prompt = {"kind": "load", "files": shown, "text": "",
                       "title": tr("номер", "number")}
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
        if steps_are_timed(steps):
            return tr(f"макрос · {len(steps)} {steps_word(len(steps))}",
                      f"macro · {len(steps)} {steps_word(len(steps))}")
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
                    self.prompt = {"kind": "confirm", "name": name,
                                   "title": tr(f"«{name}» уже есть — перезаписать? y/n",
                                               f"«{name}» already exists — overwrite? y/n")}
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
                    f"{tr('план', 'plan')} {planned:.2f} {tr('с', 's')} · "
                    f"{tr('факт', 'actual')} {actual:.2f} {tr('с', 's')} · {result}")
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
    async def _on_run_key(self, *, drop_pauses: bool = False) -> None:
        """Enter: выполнить программу (в пульте — «последнюю»: макрос или файл).

        drop_pauses — Shift+Enter: проехать без остановок (паузы выброшены).
        """
        if self.editor.is_empty():
            self._say("warn", tr(
                "программы нет — запишите макрос (m) или наберите шаги (p)",
                "no program — record a macro (m) or enter steps (p)",
            ))
            return
        await self._start_program_run(from_editor=False, drop_pauses=drop_pauses)

    async def _on_reverse_key(self, action: str) -> None:
        """r/R и t/T: проехать маршрут обратно (r — задним ходом, t — передом).

        Заглавные (с Shift) — то же самое, но без пауз: маршрут проезжается
        без остановок. Реверс считается от текущей программы, сама программа
        не меняется: Enter потом проедет её как обычно.
        """
        if self.editor.is_empty():
            self._say("warn", tr(
                "обратный проезд нечего выполнять — сначала запишите макрос (m) "
                "или программу (p)",
                "nothing to reverse — record a macro (m) or make a program (p) first",
            ))
            return
        mode = "back" if action.startswith("rev_back") else "front"
        await self._start_program_run(from_editor=False, rev=mode,
                                      drop_pauses=action.endswith("_np"))

    async def _start_program_run(self, *, from_editor: bool, rev: str | None = None,
                                 drop_pauses: bool = False) -> None:
        if self._run_task is not None and not self._run_task.done():
            return
        if self.recording:
            self._say("rec", tr("идёт запись макроса — сначала Esc (стоп)",
                                "a macro is being recorded — press Esc first"))
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
        steps = [Step(s.kind, s.value, s.seconds) for s in self.editor.steps]
        if rev is not None:
            steps = reversed_steps(self.editor, rev, drop_pauses=drop_pauses)
            if not steps:
                self._say("warn", tr(
                    "обратный проезд пуст: в программе одни паузы",
                    "nothing to drive back: the program is all pauses",
                ))
                return
        elif drop_pauses:
            steps = [s for s in steps if s.kind != "pause"]
            if not steps:
                self._say("warn", tr("в программе одни паузы — ехать некуда",
                                     "the program is all pauses — nothing to drive"))
                return
        self._run_plan = RunPlan(
            steps, self.editor.speed,
            1 if rev is not None else max(1, self.editor.repeat),
            rev, drop_pauses,
        )
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
        """Пауза: срок по часам (без накопления ошибки), на паузе прогона время не идёт."""
        left = duration
        deadline = time.monotonic() + left
        while left > 0:
            self._check_run()
            if self._run_paused:
                left = max(0.0, deadline - time.monotonic())
                await asyncio.sleep(self.RUN_TICK)
                deadline = time.monotonic() + left
                continue
            left = deadline - time.monotonic()
            if left > 0:
                await asyncio.sleep(min(self.RUN_TICK, left))

    async def _run_motion(self, move: str, duration: float, speed: int) -> None:
        """Ехать duration секунд: срок по часам, пауза время движения не тратит."""
        left = duration
        sent = False
        deadline = 0.0
        try:
            while left > 0:
                self._check_run()
                if self._run_paused:
                    if sent:
                        await self._call(self.robot.stop_all_motors)
                        sent = False
                        left = max(0.0, deadline - time.monotonic())
                    await asyncio.sleep(self.RUN_TICK)
                    continue
                if not sent:
                    if not await self._raw_drive(move, speed):
                        self._run_abort = "remote"
                        raise _RunAbort
                    sent = True
                    deadline = time.monotonic() + left
                left = deadline - time.monotonic()
                if left > 0:
                    await asyncio.sleep(min(self.RUN_TICK, left))
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
        plan = self._run_plan
        steps = plan.steps
        total = len(steps)
        repeat = plan.repeat
        speed = plan.speed
        planned = sum(self.editor._step_seconds(s) for s in steps) * repeat
        prev_led = self.led_color
        run_led = self.led_color
        self._run_total = total
        self._run_step = 0
        head = tr(f"старт: {total} {steps_word(total)} · скор. {speed}",
                  f"start: {total} {steps_word(total)} · speed {speed}")
        if plan.rev == "back":
            head += tr(" · реверс задним ходом", " · reversed (driving backwards)")
        elif plan.rev == "front":
            head += tr(" · реверс передом (робот развёрнут)", " · reversed (robot turned around)")
        elif steps_are_timed(steps):
            head += tr(" · макрос", " · macro")
        if plan.drop_pauses:
            head += tr(" · без пауз", " · without pauses")
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
                        run_led = COLOR_BY_NUMBER.get(step.value, Color.OFF)
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
                    elif step.kind == "speed":
                        speed = max(SPEED_MIN, min(SPEED_MAX, step.value))
                        self.speed = speed
                    elif step.kind == "pause":
                        await self._sleep_checked(self.editor._step_seconds(step))
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
                f"готово: {total} {steps_word(total)} за {elapsed:.2f} с (план {planned:.2f} с)",
                f"done: {total} {steps_word(total)} in {elapsed:.2f} s (planned {planned:.2f} s)",
            ))
            self._say("hint", tr(
                "Enter — ещё раз · r — назад · t — развернув робота · p — редактор",
                "Enter — again · r — back · t — robot turned · p — editor",
            ))
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
        self._run_plan = None
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
        self._tui_start()
        try:
            code = await self._run_screen()
        finally:
            self._tui_stop()
        if code == 0:
            print(tr("Пока!", "Bye!"), flush=True)
        return code

    async def _run_screen(self) -> int:
        await self._enable_key_state()
        self._print_banner()
        if self.key_state:
            self._say("hint", tr(
                f"key-state ({self._keys_backend.name}): клавиши ловятся глобально — "
                "не печатайте WASD в других окнах",
                f"key-state ({self._keys_backend.name}): keys are captured globally — "
                "don't type WASD in other windows",
            ))
        if not self.editor.is_empty() and self.program_name is not None:
            n = len(self.editor.steps)
            self._say("load", tr(
                f"программа «{self.program_name}»: {n} {steps_word(n)} · скор. {self.editor.speed}",
                f"program «{self.program_name}»: {n} {steps_word(n)} · speed {self.editor.speed}",
            ))
            self._say("hint", tr("Enter — запустить · r/t — обратно · p — редактор",
                                 "Enter — run · r/t — drive back · p — editor"))
        if self.journal:
            self._say("log", tr(f"журнал включён: {self.journal_path}",
                                f"journal is on: {self.journal_path}"))
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
                    elif not await self._handle_key(item):
                        break
                    self._tui_touch()
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
                self._tui_stop()  # итог и «Пока!» — уже на обычном экране
                self._say("ok", tr("робот остановлен и отключён", "the robot is stopped and disconnected")
                          if was_connected else tr("выход", "exiting"))
        return 0


# --------------------------------------------------------------------------- #
# Состояние клавиш (key-state)
# --------------------------------------------------------------------------- #
# Настоящие "нажал/отпустил" в обход автоповтора, как в играх: движение
# начинается в момент нажатия и прекращается в момент отпускания. Платформа
# определяется автоматически: Linux — evdev (/dev/input/event*), Windows —
# WinAPI (GetAsyncKeyState). Включается при старте; если не получилось —
# предупреждение и обычный режим (автоповтор и авто-стоп по --hold-timeout).

_EVDEV_KEY_ACTION = {  # коды клавиш Linux -> действие (физические WASD, стрелки)
    17: "fwd", 103: "fwd",      # W, ↑
    31: "back", 108: "back",    # S, ↓
    30: "left", 105: "left",    # A, ←
    32: "right", 106: "right",  # D, →
    42: "boost", 54: "boost",   # Shift (левый/правый) — буст скорости в пульте
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
    BOOST_VK = (0xA0, 0xA1)  # VK_LSHIFT, VK_RSHIFT — буст скорости в пульте

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
        vk_by_action["boost"] = self.BOOST_VK
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
        # без сокращений: «--key-state» не должен притворяться «--key-state-device»
        allow_abbrev=False,
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
    parser.add_argument("--tui", action="store_true",
                        help=tr("полноэкранный интерфейс: статус сверху, лог, подсказки",
                                "full-screen interface: status bar, log, hints"))
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
