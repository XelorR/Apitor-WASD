#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows-бэкенд key-state (WinAPI): D обязана поворачивать робота вправо.

Регрессия: в MapVirtualKeyExW передавался uMapType=2 — это MAPVK_VK_TO_CHAR,
а не MAPVK_VSC_TO_VK_EX (=3). Скан-код клавиши D (0x20) читался как VK_SPACE,
GetAsyncKeyState вместо D следил за пробелом и стрелкой — и D в пульте
на Windows не работала (а пробел «поворачивал» робота направо).

Настоящий WinAPI тут не нужен: бэкенд принимает подменный user32, который
повторяет семантику Windows (uMapType=3 — скан-код в VK, uMapType=2 — VK
в символ). Набор работает и на Linux — это чистая логика бэкенда.
"""
import asyncio
import importlib.util
import sys

from harness import APP  # путь к apitor_remote.py

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


spec = importlib.util.spec_from_file_location("apitor_remote23", APP)
mod = importlib.util.module_from_spec(spec)
sys.modules["apitor_remote23"] = mod
spec.loader.exec_module(mod)

# Скан-коды Set 1 и виртуальные клавиши Windows (Virtual-Key Codes).
W, A, S, D = 0x57, 0x41, 0x53, 0x44
SCAN = {"fwd": 0x11, "left": 0x1E, "back": 0x1F, "right": 0x20}  # W A S D
ARROW = {"fwd": 0x26, "back": 0x28, "left": 0x25, "right": 0x27}
SCAN_TO_VK = {0x11: W, 0x1E: A, 0x1F: S, 0x20: D}  # US и RU раскладки совпадают
VK_TO_CHAR = {0x20: 0x20}  # VK_SPACE -> символ " " (чем и «славился» uMapType=2)


class FakeUser32:
    """Подменный user32: held — нажатые VK, map_calls — история MapVirtualKeyExW."""

    def __init__(self, held=(), layout=None):
        self.held = set(held)
        self.layout = dict(SCAN_TO_VK if layout is None else layout)
        self.map_calls = []

    def GetKeyboardLayout(self, thread):
        return 0x0409  # безразлично: раскладку задаёт self.layout

    def MapVirtualKeyExW(self, code, maptype, hkl):
        self.map_calls.append((code, maptype))
        if maptype == 3:  # MAPVK_VSC_TO_VK_EX — код это скан-код
            return self.layout.get(code, 0)
        if maptype == 2:  # MAPVK_VK_TO_CHAR — код это VK, ответ — символ
            return VK_TO_CHAR.get(code, 0)
        return 0

    def GetAsyncKeyState(self, vk):
        return -32768 if vk in self.held else 0  # старший бит = клавиша нажата


async def drive_step(fake, held):
    """Подержать клавиши нажатыми (POLL_SECONDS у бэкенда — 10 мс)."""
    fake.held = set(held)
    await asyncio.sleep(0.08)


async def drive(held, layout=None, release=()):
    """Включить бэкенд на подменном user32 и вернуть (события, fake, кандидаты VK)."""
    events = []
    fake = FakeUser32(layout=layout)

    async def on_change(action, pressed):
        events.append((action, pressed))

    backend = mod.WinApiKeyState(on_change, lambda why: None, user32=fake)
    error = await backend.start()
    assert error is None, error
    await drive_step(fake, held)
    await drive_step(fake, release)  # отпускаем: часть клавиш остаётся нажатой
    await backend.stop()
    return events, fake, backend._vk_by_action


# ── главная регрессия: D — это «вправо» ────────────────────────────────────── #
events, fake, vks = asyncio.run(drive([D]))
check("скан-код в VK просят через MAPVK_VSC_TO_VK_EX (=3)",
      all(mt == 3 for _, mt in fake.map_calls), fake.map_calls)
check("нажатие D даёт «поворот вправо»", ("right", True) in events, events)
check("среди кандидатов «вправо» есть VK_D (0x44)", D in vks["right"], vks["right"])
check("среди кандидатов «вправо» есть стрелка вправо (0x27)",
      ARROW["right"] in vks["right"], vks["right"])
check("среди кандидатов «вправо» НЕТ пробела (0x20)", 0x20 not in vks["right"], vks["right"])
check("отпускание D останавливает поворот", ("right", False) in events, events)
check("лишних событий нет", events == [("right", True), ("right", False)], events)

# пробел — это тормоз, и он не должен «поворачивать» робота вправо
events, _, _ = asyncio.run(drive([0x20]))
check("пробел не считается поворотом вправо", events == [], events)

# ── WASD и стрелки целиком ─────────────────────────────────────────────────── #
for action, vk in (("fwd", W), ("left", A), ("back", S), ("right", D)):
    events, _, _ = asyncio.run(drive([vk]))
    check(f"буква {action} (VK 0x{vk:02X}) ловится", (action, True) in events, events)

for action, vk in ARROW.items():
    events, _, _ = asyncio.run(drive([vk]))
    check(f"стрелка {action} (VK 0x{vk:02X}) ловится", (action, True) in events, events)

# раскладка, которая не знает скан-коды: работает запасной латинский VK
events, _, vks = asyncio.run(drive([D], layout={}))
check("без перевода раскладки остаётся латинский VK_D", vks["right"][0] == D, vks["right"])
check("и D всё равно поворачивает вправо", ("right", True) in events, events)

# буст по Shift: обе Shift и общий VK_SHIFT
for vk in (0x10, 0xA0, 0xA1):
    events, _, _ = asyncio.run(drive([vk]))
    check(f"Shift (VK 0x{vk:02X}) даёт буст", ("boost", True) in events, events)

# переключение на ходу: D нажата, потом W — оба события, в удержании остаётся W
events, _, _ = asyncio.run(drive([D, W], release=[W]))
check("две клавиши сразу дают оба движения",
      ("right", True) in events and ("fwd", True) in events, events)
check("отпустили D — в удержании осталась W",
      ("right", False) in events and ("fwd", False) not in events, events)

print()
print("ОШИБОК:", failures)
sys.exit(1 if failures else 0)
