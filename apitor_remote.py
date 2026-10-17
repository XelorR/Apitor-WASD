#!/usr/bin/env python3
"""apitor_remote.py — пульт с горячими клавишами для Apitor Robot R.

Управляет роботом по Bluetooth LE через библиотеку `apitor-ble`.
Клавиши нажимаются по одной, Enter не нужен:

    q ............ подключиться         Shift+Q ...... отключиться
    w a s d ...... ехать                пробел / Esc . стоп
    ] [  (+ -) ... скорость (1..12)     1..8 ......... цвет подсветки
    0 ............ выключить подсветку
    e / Shift+E .. мотор 3 (аксессуар): вперёд / назад (тумблером)
    t ............ тест-поездка (проверить направления)
    i ............ моторы по одному (калибровка)
    l ............ режим: удержание / фиксация
    h, ? ......... справка              Ctrl+C ....... выход

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
    .venv/bin/python apitor_remote.py --address AA:BB:CC:DD:EE:FF

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
import struct
import sys
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

IS_WINDOWS = os.name == "nt"

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

COLOR_BY_KEY = {
    "1": (Color.RED, "красный"),
    "2": (Color.ORANGE, "оранжевый"),
    "3": (Color.YELLOW, "жёлтый"),
    "4": (Color.GREEN, "зелёный"),
    "5": (Color.CYAN, "голубой"),
    "6": (Color.BLUE, "синий"),
    "7": (Color.PURPLE, "фиолетовый"),
    "8": (Color.WHITE, "белый"),
}

# Символ -> действие. Стрелки приходят как "up"/"down"/"left"/"right".
KEYMAP: dict[str, str] = {
    "q": "connect",
    "Q": "disconnect",  # Shift+Q
    "w": "fwd", "s": "back", "a": "left", "d": "right",
    "up": "fwd", "down": "back", "left": "left", "right": "right",
    " ": "stop", "esc": "stop", "\r": "stop", "\n": "stop",
    "]": "speed_up", "=": "speed_up", "+": "speed_up",
    "[": "speed_down", "-": "speed_down", "_": "speed_down",
    "0": "lights_off",
    "e": "m3_fwd", "E": "m3_rev",
    "t": "test", "i": "identify", "l": "latch", "h": "help", "?": "help",
    "\x03": "quit",  # Ctrl+C (терминал в "сыром" режиме)
}
KEYMAP.update({key: f"color:{key}" for key in COLOR_BY_KEY})

# Русская раскладка: те же физические клавиши приходят кириллицей.
_LAYOUT = {
    "й": "q", "ц": "w", "у": "e", "ф": "a", "ы": "s", "в": "d", "е": "t",
    "р": "h", "д": "l",
    "Й": "Q", "Ц": "W", "У": "E", "Ф": "A", "Ы": "S", "В": "D", "Е": "T",
    "Р": "H", "Д": "L",
}


def _to_latin_layout(char: str) -> str:
    """Перевести кириллическую букву в ту же физическую клавишу QWERTY."""
    return _LAYOUT.get(char, char)


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
    """Прочитать одно нажатие; None — неинтересная последовательность."""
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
    if first[0] >= 0x80:
        first = _read_utf8_tail(fd, first)
    return _to_latin_layout(first.decode("utf-8", "replace"))

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

    def __init__(self, args: argparse.Namespace, profile) -> None:
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

        self.robot = None
        self.move = "stop"
        self.m3_dir: Direction | None = None
        self.last_input = 0.0
        self.low_power_warned = False
        self.key_state = False            # --key-state: слежение за клавишами работает
        self._held_moves: list[str] = []  # зажатые сейчас направления (key-state)
        self._keys_backend = None

        self.keys: asyncio.Queue = asyncio.Queue()
        self._connect_task: asyncio.Task | None = None
        self._send_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- вывод --------------------------------------------------------------- #
    def _say(self, tag: str, message: str) -> None:
        line = f"[{tag}] {message}"
        try:
            print(line, flush=True)
        except UnicodeEncodeError:  # старые консоли Windows
            print(line.encode("ascii", "replace").decode("ascii"), flush=True)

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
        self._say("err", f"потеряна связь с роботом ({exc}) — нажмите q, чтобы подключиться снова")

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
            self._say("warn", "уже подключено (Shift+Q — отключиться)")
            return
        if self._is_connecting():
            self._say("warn", "подключение уже идёт, подождите...")
            return
        if self.sim:
            self._say("robot", "подключаюсь (режим --simulate, без Bluetooth)...")
        else:
            self._say("robot", "ищу робота (включён и не занят телефоном?)...")
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
                self._say("robot", f"пробую подключиться к {promised}...")
                try:
                    await self._connect_to(promised, timeout=self.CONNECT_TIMEOUT)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._dbg(f"прямой коннект не удался: {exc!r}")
                    if from_cache:
                        self._cache_forget()
                    self._say("warn", "адрес не ответил — ищу заново...")

            # 2) Поиск в эфире (своё сканирование, без фильтра по UUID).
            self._say("robot", f"сканирую Bluetooth ~{self.scan_timeout:.0f} с...")
            address, name = await self._scan_for_robot()
            self._say("robot", f"нашёл {name} ({address}), подключаюсь...")
            if promised and address != promised:
                where = "был в кэше" if from_cache else "указан в --address"
                self._say("warn", f"внимание: это ДРУГОЙ робот — не тот, что {where} ({promised})")
                self._say("warn", "подключаюсь к нему; кэш будет обновлён "
                                  "(вернуть прежнего: включить только его и снова нажать q)")
            elif not promised and self.use_cache:
                self._say("info", "кэш был пуст — адрес этого робота будет запомнен")
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
            raise DiscoveryError(f"не удалось просканировать эфир: {last_error}")
        raise DiscoveryError("робот не найден — проверьте, что он включён и не подключён к телефону")

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
            self._say("warn", "подключение ещё идёт, отменяю...")
            self._connect_task.cancel()
            return
        if not self._is_connected():
            self._say("warn", "не подключено")
            return
        await self._stop("перед отключением")
        with contextlib.suppress(Exception):
            await self.robot.disconnect()
        self.robot = None
        self._say("ok", "отключено. Нажмите q, чтобы подключиться снова")

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
        self._say("motor", f"{MOVE_LABELS[move]} — скорость {self.speed}")

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
                self._say("warn", "подождите, идёт подключение...")
            else:
                self._say("warn", "нет подключения — нажмите q")
            return
        self.last_input = time.monotonic()
        if move == self.move:
            return  # автоповтор удержания: только продлеваем таймер
        self.move = move
        self._schedule_send()

    async def _stop(self, reason: str) -> None:
        if not self._is_connected():
            self._say("warn", "нет подключения — нажмите q")
            return
        self.move = "stop"
        self.m3_dir = None
        if await self._call(self.robot.stop_all_motors):
            self._say("motor", f"стоп ({reason})")

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
            self._say("warn", "нет подключения — нажмите q")
            return
        self.move = "stop"  # чтобы сторож не мешал последовательности
        self._say("test", "тест-поездка (скорость 4). Смотрите на робота:")
        for move in ("fwd", "back", "left", "right"):
            self._say("test", f"-> {MOVE_LABELS[move]}")
            if not await self._raw_drive(move, 4):
                return
            await asyncio.sleep(1.2)
            if not await self._call(self.robot.stop_all_motors):
                return
            await asyncio.sleep(0.5)
        self._say("test", "готово. Если направления неверные — см. раздел калибровки (h или README)")

    async def _identify(self) -> None:
        if not self._is_connected():
            self._say("warn", "нет подключения — нажмите q")
            return
        self.move = "stop"
        self._say("test", "по очереди кручу моторы 1, 2, 3 (скорость 4):")
        for number in (1, 2, 3):
            motor = motor_from_number(number)
            self._say("test", f"-> мотор {number}")
            if not await self._call(self.robot.run_motor, motor, Direction.D1, 4):
                return
            await asyncio.sleep(1.2)
            if not await self._call(self.robot.stop_motor, motor):
                return
            await asyncio.sleep(0.4)
        self._say("test", "готово. Запомните, какой порт крутит какое колесо (--left-motor/--right-motor)")

    # -- свет и мотор 3 ------------------------------------------------------ #
    async def _set_led(self, color: Color, name: str) -> None:
        if not self._is_connected():
            self._say("warn", "нет подключения — нажмите q")
            return
        if await self._call(self.robot.all_leds, color):
            self._say("led", f"подсветка: {name}")

    async def _on_m3(self, direction: Direction, label: str) -> None:
        if not self._is_connected():
            self._say("warn", "нет подключения — нажмите q")
            return
        if self.m3_dir == direction:
            self.m3_dir = None
            if await self._call(self.robot.stop_motor, Motor.M3):
                self._say("motor", "мотор 3: стоп")
        else:
            self.m3_dir = direction
            if await self._call(self.robot.run_motor, Motor.M3, direction, self.speed):
                self._say("motor", f"мотор 3: {label} — скорость {self.speed}")

    # -- скорость и режим ---------------------------------------------------- #
    async def _on_speed(self, delta: int) -> None:
        new_speed = max(SPEED_MIN, min(SPEED_MAX, self.speed + delta))
        if new_speed == self.speed:
            self._say("speed", f"скорость уже {self.speed} (предел {SPEED_MIN}..{SPEED_MAX})")
            return
        self.speed = new_speed
        self._say("speed", f"скорость {self.speed}")
        if self._is_connected() and self.move != "stop":
            self._schedule_send()  # применить новую скорость на ходу

    def _on_latch(self) -> None:
        self.latched = not self.latched
        if self.latched:
            self._say("mode", "фиксация: робот едет, пока не нажмёте пробел/другое")
        elif self.key_state:
            self._say("mode", "удержание: стоп в момент отпускания клавиши (key-state)")
        else:
            self._say("mode", f"удержание: авто-стоп через {self.hold_timeout:g} с после отпускания")

    # -- сторож (авто-стоп в режиме удержания) ------------------------------- #
    async def _watchdog(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.05)
                if self.latched or self.move == "stop" or not self._is_connected() or self.key_state:
                    continue
                if time.monotonic() - self.last_input > self.hold_timeout:
                    await self._stop("клавиша отпущена")
        except asyncio.CancelledError:
            pass

    # -- key-state: реальное состояние клавиш (--key-state) ------------------ #
    async def _enable_key_state(self) -> None:
        backend, error = make_key_state_backend(self._on_key_state, self._key_state_lost)
        if backend is None:
            self._say("warn", f"--key-state недоступен: {error}; работает обычное удержание")
            return
        error = await backend.start()
        if error is not None:
            self._say("warn", f"--key-state не включился: {error}; работает обычное удержание")
            return
        self._keys_backend = backend
        self.key_state = True
        self._say("info", f"key-state ({backend.name}): стоп в момент отпускания клавиши")
        self._say("hint", "клавиши ловятся глобально — не печатайте WASD в других окнах")

    async def _on_key_state(self, action: str, pressed: bool) -> None:
        """Нажал/отпустил с реальной клавиатуры (режим --key-state)."""
        if pressed:
            if action in self._held_moves:
                self._held_moves.remove(action)
            self._held_moves.append(action)
            await self._on_move(action)
            return
        if action in self._held_moves:
            self._held_moves.remove(action)
        if self.latched:
            return  # фиксация: отпускание не останавливает
        if self._held_moves:
            await self._on_move(self._held_moves[-1])  # вернуться к другой зажатой
        elif self.move != "stop":
            await self._stop("клавиша отпущена")

    def _key_state_lost(self, reason: str) -> None:
        """Backend сломался на ходу: остановиться и вернуться к таймауту."""
        if not self.key_state:
            return
        self.key_state = False
        self._held_moves.clear()
        self.last_input = time.monotonic()
        self._say("warn", f"key-state отключился ({reason}) — дальше обычное удержание")
        if self._is_connected() and self.move != "stop" and self._loop is not None:
            self._loop.create_task(self._stop("key-state отключился"))

    # -- справка и статус ---------------------------------------------------- #
    def _print_banner(self) -> None:
        self._say("info", f"пульт Apitor — {self.profile.name} (product '{self.profile.product}')")
        mode = (
            "фиксация (робот едет, пока не остановите)"
            if self.latched
            else (
                "удержание (стоп в момент отпускания, key-state)"
                if self.want_key_state
                else f"удержание (авто-стоп через {self.hold_timeout:g} с)"
            )
        )
        self._say("info", f"скорость {self.speed}, режим: {mode}")
        self._say(
            "hint",
            "q — подключиться · Shift+Q — отключиться · w/a/s/d — ехать · "
            "пробел — стоп · h — все клавиши · Ctrl+C — выход",
        )

    def _print_help(self) -> None:
        self._say("help", "клавиши пульта:")
        for line in (
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
        ):
            print(line, flush=True)

    # -- обработка клавиш и событий ------------------------------------------ #
    def _handle_event(self, item: tuple) -> None:
        _, name, payload = item
        if name == "connected":
            self._drain_keys()
            self.move = "stop"
            self.last_input = time.monotonic()
            self._say("ok", f"подключено: {self.profile.name} ({payload})")
            if self.key_state and self._held_moves and self._loop is not None:
                # Клавиша была зажата ещё до коннекта — продолжить движение.
                self._loop.create_task(self._on_move(self._held_moves[-1]))
            if not self.sim and not self.profile.calibrated:
                self._say(
                    "hint",
                    "направления для этой модели не проверены на железе: "
                    "нажмите t (тест) и при необходимости --flip-left/--flip-right",
                )
        elif name == "connect_failed":
            self._say("err", f"подключиться не удалось: {payload}")

    async def _handle_action(self, action: str) -> bool:
        if action == "quit":
            return False
        if action == "connect":
            await self._on_connect_key()
        elif action == "disconnect":
            await self._on_disconnect_key()
        elif action in MOVE_VECTORS:
            if not self.key_state:  # при key-state движение ведёт backend
                await self._on_move(action)
        elif action == "stop":
            await self._stop("клавиша стоп")
        elif action == "speed_up":
            await self._on_speed(+1)
        elif action == "speed_down":
            await self._on_speed(-1)
        elif action == "lights_off":
            await self._set_led(Color.OFF, "выключена")
        elif action.startswith("color:"):
            color, name = COLOR_BY_KEY[action.split(":", 1)[1]]
            await self._set_led(color, name)
        elif action == "m3_fwd":
            await self._on_m3(Direction.D1, "вперёд")
        elif action == "m3_rev":
            await self._on_m3(Direction.D2, "назад")
        elif action == "latch":
            self._on_latch()
        elif action == "test":
            await self._test_drive()
            self._drain_keys()
        elif action == "identify":
            await self._identify()
            self._drain_keys()
        elif action == "help":
            self._print_help()
        return True

    # -- потоки чтения клавиатуры -------------------------------------------- #
    def _reader_thread_posix(self) -> None:
        fd = sys.stdin.fileno()
        while True:
            try:
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
            self._put(_to_latin_layout(char))

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
                "Ошибка: пульту нужен настоящий терминал (запустите его в окне терминала).",
                file=sys.stderr,
            )
            return 2
        self._loop = asyncio.get_running_loop()
        self._print_banner()
        if self.want_key_state:
            await self._enable_key_state()
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
                    action = KEYMAP.get(item)
                    if action is None:
                        continue
                    if not await self._handle_action(action):
                        break
            except KeyboardInterrupt:  # на всякий случай (например, сигнал извне)
                pass
            finally:
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
                self._say("ok", "робот остановлен и отключён" if was_connected else "выход")
        print("Пока!", flush=True)
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

    def __init__(self, on_change, on_fail) -> None:
        self._on_change = on_change  # async (действие, нажато?)
        self._on_fail = on_fail      # sync (причина), если пропали все устройства
        self._loop: asyncio.AbstractEventLoop | None = None
        self._fds: dict[int, str] = {}
        self._rescan_task: asyncio.Task | None = None

    async def start(self) -> str | None:
        self._loop = asyncio.get_running_loop()
        denied = self._open_devices()
        if not self._fds:
            if denied:
                return ("нет доступа к /dev/input/event* — добавьте пользователя "
                        "в группу input (sudo usermod -aG input $USER) и войдите заново")
            return "не найдено устройств /dev/input/event*"
        self._rescan_task = self._loop.create_task(self._rescan())
        return None

    def _open_devices(self) -> int:
        """Открыть новые event-устройства; вернуть число отказов в доступе."""
        denied = 0
        for path in sorted(Path("/dev/input").glob("event*")):
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
            if not data:
                return
            self._dispatch(data)

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


def make_key_state_backend(on_change, on_fail):
    """Выбрать backend по платформе: (backend или None, причина отказа)."""
    if sys.platform.startswith("linux"):
        return EvdevKeyState(on_change, on_fail), None
    if IS_WINDOWS:
        return WinApiKeyState(on_change, on_fail), None
    return None, "поддерживается только Linux (evdev) и Windows (WinAPI)"


# --------------------------------------------------------------------------- #
# Запуск
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apitor_remote",
        description="Пульт с горячими клавишами для Apitor Robot R (и других Apitor).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--product", default="r", help="модель: r, j, s, q, x, w (Wheels)")
    parser.add_argument("--address", default=None, help="адрес Bluetooth (иначе поиск/кэш)")
    parser.add_argument("--speed", type=int, default=DEFAULT_SPEED, help=f"скорость {SPEED_MIN}..{SPEED_MAX}")
    parser.add_argument(
        "--hold-timeout",
        type=float,
        default=DEFAULT_HOLD_TIMEOUT,
        help="через сколько секунд после отпускания клавиши остановиться",
    )
    parser.add_argument("--latched", action="store_true", help="стартовать в режиме фиксации")
    parser.add_argument("--simulate", action="store_true", help="без Bluetooth: печатать кадры")
    parser.add_argument(
        "--key-state",
        action="store_true",
        help="стоп в момент отпускания клавиши, как в играх (Linux: evdev, "
             "Windows: WinAPI); без флага — авто-стоп по --hold-timeout",
    )
    parser.add_argument("--no-cache", action="store_true", help="не использовать кэш адреса")
    parser.add_argument("--scan-timeout", type=float, default=15.0, help="сколько секунд искать робота")
    parser.add_argument("--left-motor", type=int, choices=(1, 2, 3), default=None,
                        help="номер мотора левого колеса")
    parser.add_argument("--right-motor", type=int, choices=(1, 2, 3), default=None,
                        help="номер мотора правого колеса")
    parser.add_argument("--flip-left", action="store_true", help="развернуть левое колесо")
    parser.add_argument("--flip-right", action="store_true", help="развернуть правое колесо")
    parser.add_argument("--verbose", action="store_true", help="подробный журнал (кадры, сканирование)")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
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
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    remote = Remote(args, profile)
    try:
        return asyncio.run(remote.run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
