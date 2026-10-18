#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Общее окружение для наборов тестов apitor_remote.py.

Один набор можно запустить отдельно:

    .venv/bin/python tests/test_apitor5.py

Все наборы разом (параллельно, по числу ядер):

    .venv/bin/python tests/run_tests.py

Каждый набор — отдельный процесс, поэтому у каждого свой свежий временный
каталог: фейковый домашний каталог (пульт пишет настройки в
~/.config/apitor-control), папка программ, FIFO-клавиатуры для key-state.
Настоящий ~/.config, репозиторий и настоящие /dev/input не затрагиваются.

Переменные окружения:
  APITOR_TEST_PY=...   каким питоном запускать пульт (по умолчанию — тот,
                       которым запущен сам тест)
  APITOR_TEST_KEEP=1   не удалять временный каталог после прогона
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile

# Корень репозитория: tests/ лежит на уровень ниже
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "apitor_remote.py")

# Интерпретатор для запуска пульта. Все проверки идут в --simulate,
# поэтому apitor-ble не нужен и подойдёт системный python 3.10+.
PY = os.environ.get("APITOR_TEST_PY") or sys.executable

# Свежий временный корень на каждый процесс набора (имя покороче: длинные
# пути ломают перенос строк в --help, который проверяют тесты)
TMP_ROOT = tempfile.mkdtemp(prefix="apitor-")

# Фейковый домашний каталог: настоящий не трогаем
HOME = os.path.join(TMP_ROOT, "home")
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
os.environ.pop("XDG_CONFIG_HOME", None)

# Путь, которого заведомо нет: «устройство клавиатуры» для запасного режима
NOKS = os.path.join(TMP_ROOT, "no-such-event-device")


def fresh_work(name: str) -> str:
    """Свежая (ещё не созданная) временная папка для набора."""
    return os.path.join(TMP_ROOT, name)


if not os.environ.get("APITOR_TEST_KEEP"):
    atexit.register(shutil.rmtree, TMP_ROOT, ignore_errors=True)
