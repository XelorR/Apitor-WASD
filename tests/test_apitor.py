#!/usr/bin/env python3
"""PTY integration test for apitor_remote.py program-mode keys."""
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from harness import ROOT, PY, APP, NOKS, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test1")
PROGDIR = os.path.join(WORK, "programs")


def make_stub_editor():
    path = os.path.join(WORK, "stub_editor.sh")
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\n")
        fh.write("printf 'вперёд 5\\nвправо 2\\n' > \"$1\"\n")
    os.chmod(path, 0o755)
    return path


class App:
    def __init__(self, env_extra=None):
        env = dict(os.environ)
        env["TERM"] = "dumb"
        env.pop("VISUAL", None)
        if env_extra:
            env.update(env_extra)
        self.master, slave = pty.openpty()
        self.proc = subprocess.Popen(
            [PY, APP, "--simulate", "--key-state-device", NOKS, "--program-dir", PROGDIR],
            stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env,
            close_fds=True,
        )
        os.close(slave)
        self.out = b""

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
                self.out += data

    def drain(self, timeout=0.35):
        self._read(timeout)
        text, self.out = self.out.decode("utf-8", "replace"), b""
        return text

    def send(self, keys, wait=0.35):
        for key in keys:
            os.write(self.master, key.encode("utf-8"))
            time.sleep(0.12)
        self._read(wait)
        return self.drain(0.1)

    def close(self):
        try:
            self.proc.terminate()
        except ProcessLookupError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        os.close(self.master)
        return self.proc.returncode


def check(name, cond, info=""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f"  -- {info}" if info and not cond else ""))
    return cond


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(PROGDIR)
    stub = make_stub_editor()
    failures = 0

    app = App({"EDITOR": stub})
    try:
        time.sleep(1.0)
        out = app.drain()
        failures += not check("banner", "[info]" in out)

        out = app.send(["q"], wait=1.2)
        failures += not check("connect (sim)", "подключено" in out, out)

        # --- programming: P enables, program persists across Esc ---
        out = app.send(["p"])
        failures += not check("P enters program mode", "[prog]" in out and "пусто" in out, out)

        out = app.send(["]"])
        failures += not check("] changes the speed even on an empty program",
                              "скор. 7" in out and "пусто" in out, out)
        out = app.send(["["])
        failures += not check("[ changes it back on an empty program",
                              "скор. 6" in out, out)

        out = app.send(["w", "w", "a", "s"])
        failures += not check("steps added", "↑2" in out and "←" in out, out)

        out = app.send(["\x1b"], wait=0.5)  # Esc -> remote
        failures += not check("Esc -> remote", "пульт" in out, out)

        out = app.send(["p"])
        failures += not check("P returns to editor, program kept",
                              "↑2" in out, out)

        # --- Esc must never clear the program ---
        out = app.send(["\x1b"], wait=0.4)
        out += app.send(["\x1b"], wait=0.4)
        failures += not check("Esc never clears", "очищена" not in out, out)
        out = app.send(["p"])
        failures += not check("program intact after Esc x2", "↑2" in out, out)

        # --- x clears and keeps the mode ---
        out = app.send(["x"])
        failures += not check("x clears", "очищена" in out, out)
        failures += not check("x keeps editor mode", "пусто" in out, out)

        # --- external editor ($EDITOR) ---
        out = app.send(["E"], wait=1.2)
        failures += not check("E runs editor and reloads",
                              "↑5" in out and "→2" in out, out)
        failures += not check("E stays in program mode", "пусто" not in out, out)

        # Esc after editor closes -> remote
        out = app.send(["\x1b"], wait=0.5)
        failures += not check("Esc after editor -> remote", "пульт" in out, out)

        # --- run + abort semantics ---
        out = app.send(["p"])
        out = app.send(["\r"], wait=0.6)  # Enter -> run
        failures += not check("run starts", "старт" in out, out)

        out = app.send(["\x1b"], wait=0.8)  # Esc -> abort to remote
        failures += not check("Esc aborts run to remote",
                              "прервано" in out and "пульт" in out, out)

        # P during run -> program mode (r re-runs the current program from remote)
        out = app.send(["r"], wait=0.5)
        failures += not check("run again with r", "старт" in out, out)
        out = app.send(["p"], wait=0.8)
        failures += not check("P aborts run to program mode",
                              "прервано" in out and "режим программы" in out, out)

        # program survives the abort
        failures += not check("program kept after abort", "↑5" in out, out)

        # --- quit ---
        out = app.send(["\x03"], wait=1.0)
        failures += not check("quit message", "Пока" in out, out)
    finally:
        code = app.close()

    print(f"\nexit code: {code}")
    if code != 0:
        failures += 1
    print(f"failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
