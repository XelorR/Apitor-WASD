#!/usr/bin/env python3
"""--tui edge cases: narrow terminal, resize (SIGWINCH), English interface."""
import fcntl
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

from harness import ROOT, PY, APP, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test14")

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK + "/home")
os.makedirs(WORK + "/programs")

failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
ROW = re.compile(r"\x1b\[(\d+);1H\x1b\[2K(.*?)(?=\x1b\[[0-9]+;1H|\Z)", re.S)


def screens(out):
    result = []
    for segment in out.split("\x1b[1;1H")[1:]:
        rows = {int(n): ANSI.sub("", t) for n, t in ROW.findall("\x1b[1;1H" + segment)}
        if rows:
            result.append(rows)
    return result


def last_screen(out):
    all_screens = screens(out)
    return all_screens[-1] if all_screens else {}


class Session:
    def __init__(self, cols, rows, extra=()):
        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        env["HOME"] = WORK + "/home"
        self.master, self.slave = pty.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.proc = subprocess.Popen(
            [PY, APP, "--simulate", "--tui", "--key-state-device", WORK + "/nope",
             "--program-dir", WORK + "/programs", *extra],
            stdin=self.slave, stdout=self.slave, stderr=self.slave,
            cwd=ROOT, env=env, close_fds=True,
        )
        self.buf = b""

    def read(self, timeout):
        end = time.time() + timeout
        while time.time() < end:
            ready, _, _ = select.select([self.master], [], [], 0.05)
            if ready:
                try:
                    data = os.read(self.master, 65536)
                except OSError:
                    return
                if not data:
                    return
                self.buf += data

    def take(self):
        out, self.buf = self.buf.decode("utf-8", "replace"), b""
        return out

    def key(self, text, wait=0.5):
        os.write(self.master, text.encode())
        self.read(wait)
        return self.take()

    def resize(self, cols, rows):
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.proc.send_signal(signal.SIGWINCH)

    def finish(self):
        os.write(self.master, b"\x03")
        self.read(1.5)
        out = self.take()
        try:
            self.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.read(0.3)
        out += self.take()
        os.close(self.master)
        os.close(self.slave)
        return out


# -- 1. narrow terminal (34x10) ------------------------------------------------- #
s = Session(34, 10)
s.read(1.5)
out = s.take()
s.key("h")
s.key("p")
out += s.key("w")
out += s.key("]")
s.read(0.4)
out += s.take()
tail = s.finish()
out += tail
check("narrow terminal: no traceback", "Traceback" not in out, out[-400:])
rows_seen = [row for screen in screens(out) for row in screen.values()]
check("narrow terminal: every row fits 34 columns",
      max((len(r) for r in rows_seen), default=0) <= 34,
      max((len(r) for r in rows_seen), default=0))
frame = last_screen(out)
check("narrow terminal: header still drawn", "Apitor" in frame.get(1, ""), frame.get(1, ""))
check("narrow terminal: mode keys in the banner",
      any("w/a/s/d — шаги" in row for row in frame.values()), frame)
check("narrow terminal: exit 0", s.proc.returncode == 0, s.proc.returncode)

# -- 2. resize without a key press (SIGWINCH) ---------------------------------- #
s = Session(40, 12)
s.read(1.2)
s.take()
s.resize(64, 18)
s.read(1.0)
out = s.take()
frame = last_screen(out)
check("resize: redrawn after SIGWINCH without keys", bool(frame), out[:200])
check("resize: new width is used", frame.get(1, "") and len(frame[1]) == 64, len(frame.get(1, "")))
check("resize: new height is used", max(frame) == 18, max(frame))
out = s.finish()
check("resize: exit 0", s.proc.returncode == 0, s.proc.returncode)

# -- 3. English interface ------------------------------------------------------ #
s = Session(76, 24, extra=("--lang", "en"))
s.read(1.5)
out = s.take()
frame = last_screen(out)
header = frame.get(1, "")
check("en: header in English",
      "no link" in header and "speed 6" in header and "hold" in header
      and "light: white" in header, header)
check("en: banner on top in English",
      any("q — connect" in row for row in frame.values()), frame)
out = s.key("q", 0.8)
check("en: connected header", "connected" in last_screen(out).get(1, ""),
      last_screen(out).get(1, ""))
check("en: log in English", "[ok] connected: Robot R" in out, out)
out = s.key("p", 0.5)
check("en: program banner in English",
      any("w/a/s/d — steps" in row for row in last_screen(out).values()),
      last_screen(out))
out = s.finish()
check("en: goodbye in English", "Bye!" in out, out[-200:])
check("en: exit 0", s.proc.returncode == 0, s.proc.returncode)

print(f"failures: {failures}")
sys.exit(1 if failures else 0)
