#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты run.sh / run.bat: окружение, зависимости, проброс флагов, запуск.

Никаких сетевых установок: python3 подменяется заглушками в PATH, а .venv —
такой же заглушкой. Проверяем только логику самого скрипта.
"""
import os
import shutil
import subprocess
import sys
import tempfile

from harness import ROOT, APP  # репозиторий, интерпретатор, временные папки
REPO = ROOT
RUN_SH = os.path.join(REPO, "run.sh")
RUN_BAT = os.path.join(REPO, "run.bat")
APP = os.path.join(REPO, "apitor_remote.py")
REQ = os.path.join(REPO, "requirements.txt")

PASS = FAIL = 0


def check(name, ok, info=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("[PASS]", name)
    else:
        FAIL += 1
        print("[FAIL]", name, "--", info)


HOST_PY = """#!/bin/sh
echo "host:$*" >> "{log}"
for a in "$@"; do
  if [ "$a" = "-V" ]; then echo "Python {ver}"; exit 0; fi
done
case "$1" in
  -m)
    shift
    case "$1" in
      venv)
        shift
        dir=""
        for a in "$@"; do
          case "$a" in --*) ;; *) dir="$a" ;; esac
        done
        mkdir -p "$dir/bin"
        cp "{venvpy}" "$dir/bin/python"
        echo "venv-created:$dir" >> "{log}"
        exit 0
        ;;
    esac
    ;;
  -c)
    exit {pyrc}
    ;;
esac
exit 0
"""

VENV_PY = """#!/bin/sh
echo "venv:$*" >> "{log}"
case "$1" in
  -m)
    shift
    case "$1" in
      pip)
        shift
        case "$1" in
          --version) exit {piprc} ;;
          install)
            echo "install:$*" >> "{log}"
            exit {installrc}
            ;;
        esac
        ;;
    esac
    ;;
  -c)
    case "$2" in
      *apitor_ble*) exit {blerc} ;;
    esac
    exit 0
    ;;
  */apitor_remote.py)
    echo "app-start" >> "{log}"
    for a in "$@"; do echo "app-arg:$a" >> "{log}"; done
    echo "app-pwd:$PWD" >> "{log}"
    exit 0
    ;;
esac
exit 0
"""

TERM = """#!/bin/sh
echo "term:$*" >> "{log}"
exit 0
"""


def sandbox(*, with_venv=False, blerc=1, piprc=0, installrc=0, pyrc=0,
            pyver="3.12.4", with_app=True, with_python=True):
    """Папка с run.sh, заглушками python3/.venv и логом вызовов."""
    tmp = tempfile.mkdtemp(prefix="runsh-")
    log = os.path.join(tmp, "calls.log")
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir)
    with open(log, "w") as fh:
        fh.write("")
    with open(RUN_SH, "rb") as src:
        script = src.read()
    with open(os.path.join(tmp, "run.sh"), "wb") as dst:
        dst.write(script)
    os.chmod(os.path.join(tmp, "run.sh"), 0o755)
    shutil.copy(REQ, tmp)
    if with_app:
        shutil.copy(APP, tmp)

    venvpy = os.path.join(bindir, "venv-python")
    with open(venvpy, "w") as fh:
        fh.write(VENV_PY.format(log=log, blerc=blerc, piprc=piprc,
                                installrc=installrc))
    os.chmod(venvpy, 0o755)

    if with_python:
        py = os.path.join(bindir, "python3")
        with open(py, "w") as fh:
            fh.write(HOST_PY.format(log=log, ver=pyver, pyrc=pyrc,
                                    venvpy=venvpy))
        os.chmod(py, 0o755)

    if with_venv:
        vdir = os.path.join(tmp, ".venv", "bin")
        os.makedirs(vdir)
        shutil.copy(venvpy, os.path.join(vdir, "python"))

    return tmp, log, bindir


def run(tmp, bindir, args=(), *, term=False, bare=False):
    env = dict(os.environ)
    env["PATH"] = bindir if bare else bindir + ":" + os.environ["PATH"]
    if not term:
        env["APITOR_NO_TERM"] = "1"
    else:
        env["DISPLAY"] = ":0"
    env["HOME"] = tmp
    env.pop("LC_ALL", None)
    env.pop("LANG", None)
    env["LC_MESSAGES"] = "ru_RU.UTF-8"
    return subprocess.run(["/bin/bash", os.path.join(tmp, "run.sh"), *args],
                          cwd=tmp, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, timeout=120)


def log_lines(log):
    with open(log) as fh:
        return fh.read().splitlines()


print("== run.sh: файл и права ==")
check("run.sh лежит в корне и исполняемый",
      os.access(RUN_SH, os.X_OK) and open(RUN_SH, "rb").read(2) == b"#!",
      oct(os.stat(RUN_SH).st_mode))
check("run.bat лежит в корне, с CRLF",
      os.path.exists(RUN_BAT) and b"\r\n" in open(RUN_BAT, "rb").read(),
      "нет файла или переводов строк")
bat = open(RUN_BAT, "rb").read().decode("utf-8")
check("run.bat только ASCII (консоль Windows не сломает вывод)",
      all(ord(ch) < 128 for ch in bat), "есть не-ASCII символы")

print("== run.sh: .venv уже есть, зависимость стоит ==")
tmp, log, bindir = sandbox(with_venv=True, blerc=0)
out = run(tmp, bindir, ["--simulate", "--lang", "en"])
calls = log_lines(log)
check("запуск: код 0 и никаких установок",
      out.returncode == 0
      and not any(c.startswith("install:") for c in calls), (out.returncode, calls))
check("запуск: флаги ушли пульту по одному",
      "app-arg:--simulate" in calls and "app-arg:--lang" in calls
      and "app-arg:en" in calls, calls)
check("запуск: сообщение о старте на русском",
      "[run] запускаю пульт…" in out.stdout, out.stdout)

print("== run.sh: .venv есть, зависимости нет ==")
tmp, log, bindir = sandbox(with_venv=True, blerc=1)
out = run(tmp, bindir, ["--tui"])
calls = log_lines(log)
check("ставит apitor-ble из requirements.txt",
      any(c.startswith("install:install --quiet")
          and "requirements.txt" in c for c in calls), calls)
check("после установки пульт всё равно запущен",
      out.returncode == 0 and "app-start" in calls, (out.returncode, calls))

print("== run.sh: .venv нет — создаём ==")
tmp, log, bindir = sandbox(with_venv=False, blerc=1)
out = run(tmp, bindir)
calls = log_lines(log)
check("создаёт .venv и в нём python",
      any(c.startswith("venv-created:") for c in calls)
      and os.access(os.path.join(tmp, ".venv", "bin", "python"), os.X_OK), calls)
check("venv: создание, установка, запуск — по порядку",
      [c.split(":")[0] for c in calls
       if c.startswith(("venv-created", "install", "app-start"))]
      == ["venv-created", "install", "app-start"], calls)
check("сообщение про первый запуск", "первый запуск" in out.stdout, out.stdout)

print("== run.sh: установка не удалась ==")
tmp, log, bindir = sandbox(with_venv=True, blerc=1, installrc=1)
out = run(tmp, bindir)
calls = log_lines(log)
check("код 1, пульт не запущен, понятное сообщение",
      out.returncode == 1 and "app-start" not in calls
      and "проверьте интернет" in out.stdout, (out.returncode, out.stdout))

print("== run.sh: pip внутри .venv сломан ==")
tmp, log, bindir = sandbox(with_venv=True, blerc=0, piprc=1)
out = run(tmp, bindir)
calls = log_lines(log)
check("пересобирает окружение через venv --clear",
      any("venv:--clear" in c or "host:-m venv --clear" in c for c in calls), calls)

print("== run.sh: нет Python / старый Python ==")
tmp, log, bindir = sandbox(with_python=False)
out = run(tmp, bindir, bare=True)
check("без Python — понятное сообщение и код 1",
      out.returncode == 1 and "Python не найден" in out.stdout,
      (out.returncode, out.stdout))
tmp, log, bindir = sandbox(pyrc=1, pyver="3.8.10")
out = run(tmp, bindir)
check("старый Python — сообщение про 3.10",
      out.returncode == 1 and "3.10" in out.stdout and "3.8.10" in out.stdout,
      (out.returncode, out.stdout))

print("== run.sh: двойной щелчок без терминала ==")
tmp, log, bindir = sandbox(with_venv=True, blerc=0)
termstub = os.path.join(bindir, "x-terminal-emulator")
with open(termstub, "w") as fh:
    fh.write(TERM.format(log=log))
os.chmod(termstub, 0o755)
out = run(tmp, bindir, ["--simulate"], term=True)
calls = log_lines(log)
check("без TTY открывает терминал с той же командой и флагами",
      any(c.startswith("term:-e ") and "run.sh --simulate" in c for c in calls)
      and "app-start" not in calls, (out.returncode, calls))

print("== run.sh: прочее ==")
tmp, log, bindir = sandbox(with_venv=True, blerc=0)
out = run(tmp, bindir, ["--program", "моя программа.txt"])
calls = log_lines(log)
check("путь с пробелом остаётся одним аргументом",
      "app-arg:моя программа.txt" in calls, calls)
check("пульт запускается из папки скрипта, а не из текущей",
      "app-pwd:" + tmp in calls, calls)
# запуск «откуда угодно»: cwd=/tmp
proc = subprocess.run(["/bin/bash", os.path.join(tmp, "run.sh"), "--help"],
                      cwd="/tmp", env={**os.environ, "APITOR_NO_TERM": "1",
                                       "HOME": tmp,
                                       "PATH": bindir + ":" + os.environ["PATH"]},
                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                      stderr=subprocess.STDOUT, text=True, timeout=120)
check("скрипт находит свои файлы из любого каталога",
      "app-start" in log_lines(log), proc.stdout)
# нет apitor_remote.py рядом
tmp, log, bindir = sandbox(with_venv=True, blerc=0, with_app=False)
out = run(tmp, bindir)
check("без apitor_remote.py — понятная ошибка",
      out.returncode == 1 and "apitor_remote.py" in out.stdout,
      (out.returncode, out.stdout))

print(f"\nитог: {PASS} проверок пройдено, {FAIL} провалено")
sys.exit(1 if FAIL else 0)
