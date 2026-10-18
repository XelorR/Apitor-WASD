#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Пульт Apitor: запуск одним двойным щелчком.
#
# Скрипт сам всё подготовит рядом с собой:
#   1) если нет .venv — создаст виртуальное окружение;
#   2) если в нём нет библиотеки apitor-ble — поставит её из requirements.txt;
#   3) запустит apitor_remote.py, передав ему все аргументы.
#
# Нужен только Python 3.10+ в системе — больше ничего ставить не надо.
# Двойной щелчок из файлового менеджера открывает терминал сам (если умеет);
# из терминала — просто ./run.sh
#
# Примеры:
#   ./run.sh                                   # обычный пульт
#   ./run.sh --tui                             # полноэкранный интерфейс
#   ./run.sh --simulate                        # без робота: печатать кадры
#   ./run.sh --program examples/квадрат.txt    # программа при старте
#   ./run.sh --lang en                         # английский интерфейс
#
# Переменные окружения:
#   PYTHON=/путь/к/python3   каким Python создавать .venv (по умолчанию python3)
#   APITOR_NO_TERM=1         не открывать терминал самому (для тестов)

ARGS=("$@")
# Свой каталог и своё имя — только средствами bash (никаких dirname/basename:
# в системе может не оказаться вообще ничего, кроме Python).
case "$0" in
  */*) SELF_DIR="${0%/*}" ;;
  *)   SELF_DIR="." ;;
esac
SELF_DIR="$(cd "$SELF_DIR" && pwd)" || exit 1
cd "$SELF_DIR" || exit 1
SELF="$SELF_DIR/${0##*/}"

# ---------------------------------------------------------------------------
# Сообщения: по-русски, если в системе русский язык, иначе по-английски.
# ---------------------------------------------------------------------------
RU_MSG=0
case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
  ru*|*_RU*|*RU*) RU_MSG=1 ;;
esac
msg() {  # msg "текст по-русски" "text in English"
  if [ "$RU_MSG" = 1 ]; then printf '[run] %s\n' "$1"; else printf '[run] %s\n' "$2"; fi
}

# ---------------------------------------------------------------------------
# Двойной щелчок из графики: терминала нет — попробуем открыть его сами.
# ---------------------------------------------------------------------------
if [ ! -t 0 ] && [ -z "${APITOR_NO_TERM:-}" ] \
   && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; }; then
  for term in x-terminal-emulator gnome-terminal konsole xfce4-terminal \
              kitty foot alacritty wezterm xterm; do
    command -v "$term" >/dev/null 2>&1 || continue
    case "$term" in
      gnome-terminal) exec "$term" -- "$SELF" "${ARGS[@]}" ;;
      xfce4-terminal) exec "$term" -x "$SELF" "${ARGS[@]}" ;;
      wezterm)        exec "$term" start -- "$SELF" "${ARGS[@]}" ;;
      kitty|foot)     exec "$term" "$SELF" "${ARGS[@]}" ;;
      *)              exec "$term" -e "$SELF" "${ARGS[@]}" ;;
    esac
  done
  msg "не нашёл терминал: запустите ./run.sh в окне терминала" \
      "no terminal found: please run ./run.sh in a terminal window"
fi

# ---------------------------------------------------------------------------
# Python в системе (ничего, кроме него, не нужно).
# ---------------------------------------------------------------------------
if [ ! -f "$SELF_DIR/apitor_remote.py" ]; then
  msg "рядом со скриптом нет apitor_remote.py — положите run.sh в папку пульта" \
      "apitor_remote.py is missing next to the script — put run.sh in its folder"
  exit 1
fi

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
  done
fi
if [ -z "$PY" ]; then
  msg "Python не найден. Поставьте Python 3.10+ и запустите снова" \
      "Python was not found. Install Python 3.10+ and try again"
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
       >/dev/null 2>&1; then
  msg "нужен Python 3.10 или новее, а в системе $("$PY" -V 2>&1)" \
      "Python 3.10 or newer is required, but the system has $("$PY" -V 2>&1)"
  exit 1
fi

# ---------------------------------------------------------------------------
# Виртуальное окружение .venv рядом со скриптом.
# ---------------------------------------------------------------------------
VENV="$SELF_DIR/.venv"
VPY="$VENV/bin/python"

if [ ! -x "$VPY" ]; then
  msg "первый запуск: готовлю окружение .venv…" \
      "first run: creating the .venv environment…"
  if ! "$PY" -m venv "$VENV"; then
    msg "не получилось создать .venv. В Debian/Ubuntu помогает пакет python3-venv:" \
        "could not create .venv. On Debian/Ubuntu the python3-venv package helps:"
    msg "    sudo apt install python3-venv" \
        "    sudo apt install python3-venv"
    exit 1
  fi
fi

if ! "$VPY" -m pip --version >/dev/null 2>&1; then
  msg "в .venv нет pip — собираю окружение заново…" \
      "no pip inside .venv — rebuilding the environment…"
  "$PY" -m venv --clear "$VENV" || exit 1
fi

# ---------------------------------------------------------------------------
# Единственная зависимость — apitor-ble.
# ---------------------------------------------------------------------------
if ! "$VPY" -c 'import apitor_ble' >/dev/null 2>&1; then
  msg "ставлю библиотеку apitor-ble (один раз, нужен интернет)…" \
      "installing the apitor-ble library (once, needs the internet)…"
  if ! "$VPY" -m pip install --quiet --disable-pip-version-check \
        -r "$SELF_DIR/requirements.txt"; then
    msg "не получилось поставить зависимости: проверьте интернет и запустите снова" \
        "could not install the dependencies: check the internet and try again"
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Запуск пульта со всеми переданными флагами.
# ---------------------------------------------------------------------------
msg "запускаю пульт… (Ctrl+C — выход)" "starting the remote… (Ctrl+C quits)"
exec "$VPY" "$SELF_DIR/apitor_remote.py" "${ARGS[@]}"
