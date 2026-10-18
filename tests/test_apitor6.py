#!/usr/bin/env python3
"""Programs default to ./programs next to the script; --program-dir still wins."""
import os
import pty
import select
import shutil
import subprocess
import sys
import time

from harness import ROOT, PY, APP, NOKS, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test6")
APPDIR = os.path.join(WORK, "app")
CUSTOM = os.path.join(WORK, "custom")

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(APPDIR)
shutil.copy(os.path.join(ROOT, "apitor_remote.py"), os.path.join(APPDIR, "apitor_remote.py"))
APP = os.path.join(APPDIR, "apitor_remote.py")

env = dict(os.environ)
env["TERM"] = "dumb"


class App:
    def __init__(self, extra=()):
        self.master, slave = pty.openpty()
        self.proc = subprocess.Popen(
            [PY, APP, "--simulate", "--key-state-device", NOKS, *extra],
            stdin=slave, stdout=slave, stderr=slave, cwd=APPDIR, env=env,
            close_fds=True,
        )
        os.close(slave)
        self.buf = b""

    def _read(self, timeout):
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

    def drain(self, timeout=0.35):
        self._read(timeout)
        text, self.buf = self.buf.decode("utf-8", "replace"), b""
        return text

    def send(self, keys, wait=0.35):
        for key in keys:
            os.write(self.master, key.encode("utf-8"))
            time.sleep(0.12)
        self._read(wait)
        return self.drain(0.1)

    def close(self):
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        os.close(self.master)
        return self.proc.returncode


failures = 0


def check(name, cond, info=""):
    global failures
    failures += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {info}" if not cond and info else ""))


# 1. default location: script-adjacent programs/
app = App()
try:
    app.drain(1.0)
    app.send(["q"], 1.2)
    app.send(["p"])
    app.send(["w", "w"])
    out = app.send(["\x03"], wait=1.0)
finally:
    code = app.close()
default_dir = os.path.join(APPDIR, "programs")
draft = os.path.join(default_dir, "_draft.txt")
check("exit 0", code == 0, f"code={code}")
check("programs/ created next to the script", os.path.isdir(default_dir))
check("_draft.txt written there", os.path.exists(draft))
if os.path.exists(draft):
    check("draft content", "вперёд 2" in open(draft).read(), open(draft).read())

# 2. draft comes back on the next run from the same place
app = App()
try:
    app.drain(1.0)
    app.send(["q"], 1.2)
    out = app.send(["p"])
    check("draft loaded from programs/", "↑2" in out, out)
    out = app.send(["x"], wait=0.5)  # clear + drop draft
    app.send(["\x03"], wait=1.0)
finally:
    code = app.close()
check("exit 0 (2)", code == 0, f"code={code}")
check("draft removed by clear", not os.path.exists(draft))

# 3. --program-dir overrides the default
app = App(["--program-dir", CUSTOM])
try:
    app.drain(1.0)
    app.send(["q"], 1.2)
    app.send(["p"])
    app.send(["a"])
    app.send(["\x03"], wait=1.0)
finally:
    code = app.close()
check("exit 0 (3)", code == 0, f"code={code}")
check("custom dir used", os.path.isdir(CUSTOM) and
      os.path.exists(os.path.join(CUSTOM, "_draft.txt")))
check("script-adjacent dir untouched", not os.path.exists(draft))

# 4. --help shows the new default
help_out = subprocess.run([PY, APP, "--help"], capture_output=True, text=True).stdout
# справка переносит длинные строки, да ещё и режет слова — сравниваем без пробелов
help_flat = "".join(help_out.split())
check("--help mentions script-adjacent default",
      "".join(os.path.join(APPDIR, "programs").split()) in help_flat, help_out[-400:])

print(f"failures: {failures}")
sys.exit(1 if failures else 0)
