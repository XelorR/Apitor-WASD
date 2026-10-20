#!/usr/bin/env python3
"""--tui: full-screen interface — status header, log, program row, prompts."""
import fcntl
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import sys
import termios
import time

from harness import ROOT, PY, APP, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test13")
PROGDIR = os.path.join(WORK, "programs")
FAKEHOME = os.path.join(WORK, "home")
EDITOR = os.path.join(WORK, "fake-editor.sh")

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(PROGDIR)
os.makedirs(FAKEHOME)

with open(EDITOR, "w", encoding="utf-8") as fh:
    fh.write("#!/bin/sh\nprintf 'вперёд 3\\n' > \"$1\"\n")
os.chmod(EDITOR, 0o755)

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
ROW = re.compile(r"\x1b\[(\d+);1H\x1b\[2K(.*?)(?=\x1b\[[0-9]+;1H|\x1b\[\?25l|\Z)", re.S)
# ED (CSI J) с курсором в начале строки стирает её и всё ниже: так видно,
# что последняя строка кадра (программа/приглашение) реально на экране.
ERASE_DOWN = re.compile(r"\x1b\[(\d+);1H\x1b\[J")


def screens(out):
    """Все нарисованные кадры: номер строки -> текст без ANSI-кодов."""
    result = []
    for segment in out.split("\x1b[1;1H")[1:]:
        rows = {int(n): ANSI.sub("", text)
                for n, text in ROW.findall("\x1b[1;1H" + segment)}
        for n, _ in ERASE_DOWN.findall(segment):
            for number in [k for k in rows if k >= int(n)]:
                rows.pop(number, None)
        if rows:
            result.append(rows)
    return result


STEP_ROW = re.compile(r"^[\u2191\u2193\u2190\u2192\u2016\u2726\u25cf]")


def prog_row(frame):
    """Содержимое рамки программы (начинается со значка шага) или пусто."""
    for number in sorted(frame):
        row = frame[number]
        if row.startswith("│"):
            row = row[1:]
            if row.endswith("│"):
                row = row[:-1]
        if STEP_ROW.match(row):
            return row
    return ""


def prog_body(frame):
    """Любое содержимое рамки программы (даже «(пусто)») или пусто."""
    for number in sorted(frame):
        row = frame[number]
        if row.startswith("│"):
            row = row[1:]
            if row.endswith("│"):
                row = row[:-1]
            return row
    return ""


def prog_title(frame):
    """Строка-заголовок рамки программы (число шагов, скорость) или пусто."""
    for number in sorted(frame):
        if frame[number].startswith("┌─") and "программа ·" in frame[number]:
            return frame[number]
    return ""


def last_screen(out):
    all_screens = screens(out)
    return all_screens[-1] if all_screens else {}


env = dict(os.environ)
env["TERM"] = "xterm-256color"
env["HOME"] = FAKEHOME
env["EDITOR"] = EDITOR
master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 76, 0, 0))
proc = subprocess.Popen(
    [PY, APP, "--simulate", "--tui", "--key-state-device", os.path.join(WORK, "nope"),
     "--program-dir", PROGDIR],
    stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, close_fds=True,
)
os.close(slave)
buf = b""
session: list[str] = []


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
    session.append(out)
    return out


def key(text, wait=0.5):
    os.write(master, text.encode())
    read(wait)
    return take()


try:
    read(1.5)
    out = take()
    check("enters the alternate screen and hides the cursor",
          "\x1b[?1049h" in out and "\x1b[?25l" in out, repr(out[:60]))
    first = last_screen(out)
    header = first.get(1, "")
    check("header shows robot, link, speed, mode, light",
          all(word in header for word in ("Apitor Robot R", "нет связи", "скор. 6",
                                          "удержание", "свет: белый")), header)
    check("header fills the whole width", len(header) == 76, f"{len(header)}: {header!r}")
    check("banner on top shows the mode and its keys",
          all(any(fragment in row for row in first.values())
              for fragment in ("пульт:", "q — подключиться")), first)
    check("key-state warning in the log once",
          sum("[warn] key-state не включился" in row for row in first.values()) == 1, first)
    check("no doubled tags anywhere", not re.search(r"\[[a-z]+\] \[[a-z]+\]", out), out)

    out = key("q", 0.8)
    check("header switches to connected", "подключён" in last_screen(out).get(1, ""),
          last_screen(out).get(1, ""))
    check("log has [ok] connected", "[ok] подключено: Robot R" in out, out)

    out = key("w")
    check("log shows driving", "[motor] вперёд — скорость 6" in out, out)
    check("sim frames still go through the log", "[sim] -> 55aa" in out, out)
    key(" ")

    out = key("6", 0.4)
    check("light in the header follows 6 -> синий",
          "свет: синий" in last_screen(out).get(1, ""), last_screen(out).get(1, ""))

    out = key("]", 0.4)
    check("speed in the header follows ]",
          "скор. 7" in last_screen(out).get(1, ""), last_screen(out).get(1, ""))
    key("[", 0.4)

    out = key("p")
    state = last_screen(out)
    check("banner switches to program mode keys",
          ("режим программы:" in state.get(2, "") and "шаги" in state.get(2, "")), state.get(2, ""))
    check("mode segment shows программа", "программа" in state.get(1, ""), state.get(1, ""))
    check("empty program -> empty frame body", prog_row(state) == "", state.get(23, ""))
    check("empty program: frame title shows count and speed",
          "0 шагов" in prog_title(state) and "скор. 6" in prog_title(state),
          prog_title(state))
    check("program frame is drawn",
          any(row.startswith("┌─") for row in state.values())
          and any(row.startswith("└") for row in state.values()), state)

    out = key("]")
    state = last_screen(out)
    check("] reaches the editor header", "скор. 7" in state.get(1, ""), state.get(1, ""))
    check("] reaches the empty program frame",
          "скор. 7" in prog_title(state) and "пусто" in prog_body(state),
          (prog_title(state), prog_body(state)))
    key("[", 0.4)

    key("w")
    out = key("w")
    state = last_screen(out)
    check("program frame shows ↑2 live", "↑2" in prog_row(state), prog_row(state))
    check("program frame title counts the step",
          "1 шаг" in prog_title(state), prog_title(state))
    check("no doubled [prog] tag in the program row", "[prog] [prog]" not in out, out)

    out = key("h")
    check("help goes to the log", "[help] клавиши режима программы:" in out, out)
    check("help lines keep their indentation",
          "  o             разовая программа (как p, но не сохраняется)" in out, out)
    check("no doubled [help] tag in the log", "[help] [help]" not in out, out)

    out = key("F")
    state = last_screen(out)
    check("save prompt in the bottom line",
          "[save] имя файла [" in state.get(24, "") and state.get(24, "").strip().endswith(": ▏"),
          state.get(24, ""))
    out = key("робот-1")
    check("typed name is echoed in the bottom line",
          "робот-1▏" in last_screen(out).get(24, ""), last_screen(out).get(24, ""))
    out = key("\r", 0.7)
    check("saved to the program dir",
          os.path.exists(os.path.join(PROGDIR, "робот-1.txt")), sorted(os.listdir(PROGDIR)))
    check("log confirms the save", "[save] сохранено:" in out, out)
    check("prompt cleared from the bottom line",
          "[save]" not in last_screen(out).get(24, ""), last_screen(out).get(24, ""))

    out = key("g", 0.7)
    check("load prompt lists programs", "[load] программы (" in out, out)
    check("load prompt in the bottom line",
          "номер" in last_screen(out).get(24, "") and "▏" in last_screen(out).get(24, ""),
          last_screen(out).get(24, ""))
    key("1", 0.5)
    out = key("\r", 0.8)
    check("loading by number", "[load] загружено: робот-1.txt" in out, out)
    check("program row after load", "↑2" in prog_row(last_screen(out)),
          prog_row(last_screen(out)))

    out = key("x", 0.5)
    check("cleared program removes the row", prog_row(last_screen(out)) == "",
          prog_row(last_screen(out)))

    out = key("E", 1.5)
    check("external editor leaves the alt screen", out.count("\x1b[?1049l") == 1,
          out.count("\x1b[?1049l"))
    check("external editor re-enters the alt screen", out.count("\x1b[?1049h") == 1,
          out.count("\x1b[?1049h"))
    check("program from the editor is loaded", "[prog] обновлено из редактора" in out, out)
    check("program row shows ↑3 after the editor",
          "↑3" in prog_row(last_screen(out)), prog_row(last_screen(out)))

    key("\x1b")  # back to remote
    out = key("y", 1.0)
    check("test drive logs into the TUI", "[test] тест-поездка" in out, out)
    deadline = time.time() + 20
    while "готово. Если направления неверные" not in out and time.time() < deadline:
        read(0.5)
        out += take()
    check("test drive finished in the TUI", "готово. Если направления неверные" in out,
          out[-200:])
    check("header still whole after test drive", len(last_screen(out).get(1, "")) == 76,
          last_screen(out).get(1, ""))

    os.write(master, b"\x03")
    read(1.5)
    take()
finally:
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    read(0.5)
    out = "".join(session) + take()
    enters = out.count("\x1b[?1049h")
    leaves = out.count("\x1b[?1049l")
    check("alternate screen entered/left in pairs (start, editor, quit)",
          enters == leaves == 2 and out.rindex("\x1b[?1049l") > out.rindex("\x1b[?1049h"),
          f"enters={enters} leaves={leaves}")
    check("goodbye on the normal screen", "Пока!" in out, out[-300:])
    check("exit 0", proc.returncode == 0, f"code={proc.returncode}")
    os.close(master)

print(f"failures: {failures}")
sys.exit(1 if failures else 0)
