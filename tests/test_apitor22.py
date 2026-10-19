#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Флаги запуска, коды выхода, config.json, калибровка и сверка документации.

Из соседних наборов сюда не дублируется ничего: здесь то, что раньше не
проверялось вовсе — --cruise (прежнее имя --latched), коды выхода 2/130,
запоминание языка в config.json, --flip-left, i (моторы), журнал прогонов
(только флаг --log, хоткея нет) и правило «каждая клавиша описана во всех
документах».
"""
import fcntl
import importlib.util
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time

from harness import ROOT, PY, APP, NOKS, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test22")
FAKEHOME = os.path.join(WORK, "home")
PROGDIR = os.path.join(WORK, "programs")

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(FAKEHOME)
os.makedirs(PROGDIR)

env = dict(os.environ)
env["TERM"] = "dumb"
env["HOME"] = FAKEHOME


def run(args, **kw):
    return subprocess.run([PY, APP, *args], capture_output=True, text=True,
                          cwd=ROOT, env=env, stdin=subprocess.DEVNULL, timeout=30, **kw)


def parser_args(argv):
    spec = importlib.util.spec_from_file_location("apitor_remote22", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["apitor_remote22"] = mod
    spec.loader.exec_module(mod)
    return mod.build_parser().parse_args(argv), mod


# ── режим движения: --cruise (и прежнее имя --latched) ─────────────────────── #
args, mod = parser_args([])
check("по умолчанию круиз-контроль выключен", args.latched is False)
args, _ = parser_args(["--cruise"])
check("--cruise принимается", args.latched is True)
args, _ = parser_args(["--latched"])
check("--latched (прежнее имя) тоже принимается", args.latched is True)
help_text = " ".join((mod.build_parser().format_help() + mod.build_parser().format_usage()).split())
check("--cruise есть в --help", "--cruise" in help_text, help_text[:200])
check("--latched спрятан из --help", "--latched" not in help_text, help_text[:200])

# ── коды выхода 2: без TTY, плохая модель, плохой файл программы ───────────── #
r = run([])
check("без терминала: код 2", r.returncode == 2, r.returncode)
check("без терминала: понятное сообщение",
      "нужен настоящий терминал" in r.stderr, r.stderr[:120])

r = run(["--product", "z"])
check("--product z: код 2", r.returncode == 2, r.returncode)
check("--product z: перечень моделей в ошибке",
      "robot" in r.stderr and "'j'" in r.stderr, r.stderr[:160])

r = run(["--program", os.path.join(WORK, "нет-такого.txt")])
check("--program без файла: код 2", r.returncode == 2, r.returncode)

bad = os.path.join(WORK, "с-опечаткой.txt")
open(bad, "w", encoding="utf-8").write("вперёд 4\nфигня\n")
r = run(["--program", bad])
check("--program с опечаткой: код 2", r.returncode == 2, r.returncode)

good = os.path.join(WORK, "ок.txt")
open(good, "w", encoding="utf-8").write("вперёд 4\n")
r = run(["--program", os.path.join(good, "подкаталог.txt")])
check("--program с каталогом вместо файла: код 2", r.returncode == 2, r.returncode)

# ── живой пульт: --cruise, i, --flip-left ──────────────────────────────────── #
def pty_app(extra=(), wait=1.4):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
    proc = subprocess.Popen(
        [PY, APP, "--simulate", "--key-state-device", NOKS, "--program-dir", PROGDIR, *extra],
        stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
    )
    os.close(slave)
    buf = b""

    def read(seconds):
        nonlocal buf
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

    read(wait)

    def take():
        nonlocal buf
        out = buf.decode("utf-8", "replace")
        buf = b""
        return out

    def key(text, wait=0.6):
        os.write(master, {"enter": b"\r", "esc": b"\x1b"}.get(text, text.encode()))
        read(wait)
        return take()

    return proc, master, take, key


def quit_app(proc, master):
    os.write(master, b"\x03")
    try:
        return proc.wait(timeout=6)
    except subprocess.TimeoutExpired:
        proc.kill()
        return None


proc, master, take, key = pty_app(["--cruise"])
out = take()
check("--cruise: баннер сообщает о круиз-контроле",
      "режим: круиз-контроль" in out, out)
key("q")
out = key("w")
check("--cruise: робот едет, клавишу можно отпустить", "вперёд" in out, out)
out = key("пробел")
check("--cruise: пробел — тормоз", "стоп" in out, out)
code = quit_app(proc, master)
check("выход по Ctrl+C: код 0", code == 0, code)

# SIGINT снаружи: код 130 (тот же смысл, что «Ctrl+C из терминала»)
proc, master, take, key = pty_app([])
proc.send_signal(signal.SIGINT)
try:
    code = proc.wait(timeout=6)
except subprocess.TimeoutExpired:
    proc.kill()
    code = None
check("SIGINT: код 130", code == 130, code)

# i — моторы по одному
proc, master, take, key = pty_app([])
key("q")
out = key("i", 1.0)
check("i: объявляет моторы 1, 2, 3", "моторы 1, 2, 3" in out, out)
check("i: начинает с мотора 1", "мотор 1" in out, out)
quit_app(proc, master)

# --flip-left: кадр движения отличается (колесо развёрнуто)
def frames_for(extra):
    proc, master, take, key = pty_app(extra)
    key("q")
    data = key("w") + take()  # кадры приходят на само нажатие
    quit_app(proc, master)
    return [ln.strip() for ln in data.splitlines() if "[sim]" in ln]


normal = frames_for([])
flipped = frames_for(["--flip-left"])
check("кадры движения идут", bool(normal) and bool(flipped), (normal[:2], flipped[:2]))
check("--flip-left меняет кадр движения", normal != flipped, (normal[:2], flipped[:2]))

# ── config.json: язык и папка программ запоминаются ────────────────────────── #
cfg_path = os.path.join(FAKEHOME, ".config", "apitor-control", "config.json")
proc, master, take, key = pty_app([], wait=1.0)  # первый запуск: ещё русский
out = take()
check("первый запуск: русский интерфейс", "скорость 6" in out, out)
quit_app(proc, master)
cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {}
check("config.json создан", isinstance(cfg, dict), cfg)

proc, master, take, key = pty_app(["--lang", "en"], wait=1.0)
quit_app(proc, master)
cfg = json.load(open(cfg_path, encoding="utf-8"))
check("--lang en запоминается", cfg.get("lang") == "en", cfg)

proc, master, take, key = pty_app([], wait=1.0)  # без флага — но уже по-английски
out = take()
check("второй запуск: язык взят из config.json", "speed 6" in out and "mode:" in out, out)
quit_app(proc, master)

proc, master, take, key = pty_app(["--lang", "ru"], wait=1.0)
quit_app(proc, master)
cfg = json.load(open(cfg_path, encoding="utf-8"))
check("--lang ru возвращает русский", cfg.get("lang") == "ru", cfg)

cfg["program_dir"] = PROGDIR
open(cfg_path, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False))
before = set(os.listdir(PROGDIR))
proc, master, take, key = pty_app([], wait=1.0)
key("p")
key("w")
out = key("f")
check("сохранение спрашивает имя файла", "[save]" in out, out)
key("enter", 1.0)
quit_app(proc, master)
new_files = {n for n in set(os.listdir(PROGDIR)) - before if n.endswith(".txt")}
check("файл сохранён в папку из config.json", bool(new_files), os.listdir(PROGDIR))

# ── журнал: включается только флагом, хоткея нет ───────────────────────────── #
help_full = run(["--help"]).stdout
check("в справке нет хоткея журнала",
      not re.search(r"^\s+J\s{2,}\S", help_full, re.M),
      [ln for ln in help_full.splitlines() if ln.strip().startswith("J")])
check("в справке есть флаг --log", "--log" in help_full)

logfile = os.path.join(FAKEHOME, ".config", "apitor-control", "runs.log")
if os.path.exists(logfile):
    os.remove(logfile)


def run_program(extra=()):
    """Прогнать программу из одного шага; вернуть вывод на нажатие j."""
    proc, master, take, key = pty_app(extra, wait=1.0)
    key("q")
    out = key("j")            # раньше здесь был журнал, теперь — режим удержания
    key("p")
    key("w")
    key("enter", 2.4)
    quit_app(proc, master)
    return out


out = run_program()
check("без --log журнал не пишется", not os.path.exists(logfile), out)
check("j переключает удержание, а не журнал",
      "удержание" in out and "журнал" not in out.lower(), out)

out = run_program(["--log"])
check("--log: прогон попал в журнал", os.path.exists(logfile), out)
log_text = open(logfile, encoding="utf-8").read() if os.path.exists(logfile) else ""
check("в журнале строка о прогоне", "план" in log_text and "готово" in log_text, log_text)

# ── правило проекта: клавиши описаны во всех документах ────────────────────── #
RU_KEYS = ["`q`", "`Shift+Q`", "`w`", "`a`", "`s`", "`d`", "`пробел`", "`Esc`",
           "`Enter`", "`Shift+Enter`", "`r`", "`t`", "`R`", "`T`", "`m`", "`n`",
           "`y`", "`i`", "`j`", "`k`", "`b`", "`B`", "`c`", "`*`", "`v`", "`V`",
           "`e`", "`E`", "`f`", "`g`", "`x`", "`p`", "`h`", "`Ctrl+C`"]
EN_KEYS = ["`q`", "`Shift+Q`", "`w`", "`a`", "`s`", "`d`", "`space`", "`Esc`",
           "`Enter`", "`Shift+Enter`", "`r`", "`t`", "`R`", "`T`", "`m`", "`n`",
           "`y`", "`i`", "`j`", "`k`", "`b`", "`B`", "`c`", "`*`", "`v`", "`V`",
           "`e`", "`E`", "`f`", "`g`", "`x`", "`p`", "`h`", "`Ctrl+C`"]

for name, keys in (("README.md", RU_KEYS),
                   ("docs/instructions-ru.md", RU_KEYS),
                   ("docs/instructions-en.md", EN_KEYS)):
    text = open(os.path.join(ROOT, name), encoding="utf-8").read()
    missing = [k for k in keys if k not in text]
    check(f"{name}: все клавиши описаны", not missing, missing)

# флаг --cruise описан во всех трёх, а освободившаяся клавиша l — нигде
for name in ("README.md", "docs/instructions-ru.md", "docs/instructions-en.md"):
    text = open(os.path.join(ROOT, name), encoding="utf-8").read()
    check(f"{name}: описан --cruise", "--cruise" in text)
    check(f"{name}: клавиша l нигде не рекламируется", "`l`" not in text,
          [ln for ln in text.splitlines() if "`l`" in ln][:2])

print()
print("ОШИБОК:", failures)
sys.exit(1 if failures else 0)
