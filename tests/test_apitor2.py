#!/usr/bin/env python3
"""Edge-case PTY tests: x in remote, x during run, parse errors, fallback editors."""
import os
import pty
import select
import shutil
import subprocess
import sys
import time

from harness import ROOT, PY, APP, NOKS, fresh_work  # репозиторий, интерпретатор, временные папки
WORK = fresh_work("test2")
PROGDIR = os.path.join(WORK, "programs")


def make_stub_editor(body):
    path = os.path.join(WORK, "stub_editor.sh")
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\n")
        fh.write(body)
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
    print(f"[{mark}] {name}" + (f"  -- {info}" if not cond and info else ""))
    return cond


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(PROGDIR)
    failures = 0

    # ============ 1. x clears in remote mode and stays remote ============ #
    stub = make_stub_editor("printf 'вперёд 3\\n' > \"$1\"\n")
    app = App({"EDITOR": stub})
    try:
        app.drain(1.0)
        app.send(["q"], wait=1.2)
        app.send(["p"])
        app.send(["w", "w", "w"])
        app.send(["\x1b"], wait=0.5)  # -> remote
        out = app.send(["x"], wait=0.5)
        failures += not check("x clears in remote mode", "очищена" in out, out)
        # still remote? then w drives the robot (sim frames) instead of adding a step
        out = app.send(["w"], wait=0.6)
        failures += not check("x does NOT switch mode (still remote)",
                              "55aa" in out, out)
        failures += not check("x does NOT switch to program line",
                              "шаг" not in out, out)
        # (Esc stops in remote and must not clear anything)
        out = app.send(["\x1b"], wait=0.4)
        failures += not check("Esc in remote doesn't clear", "очищена" not in out, out)
        out = app.send(["p"])
        failures += not check("cleared program stays empty", "пусто" in out, out)
        app.send(["\x1b"], wait=0.4)

        # ============ 2. x during a run is ignored ============ #
        app.send(["p"])
        out = app.send(["w", "w", "w", "w", "w"])  # вперёд 5 ~3 s
        failures += not check("long program built", "↑5" in out, out)
        out = app.send(["\r"], wait=0.3)  # Enter in editor -> run
        failures += not check("run from editor", "старт" in out, out)
        out = app.send(["x"], wait=0.3)
        failures += not check("x ignored during run", "очищена" not in out, out)
        out = app.send(["\x1b"], wait=0.8)  # abort
        failures += not check("run aborted via Esc", "прервано" in out, out)
        out = app.send(["p"])
        failures += not check("program intact after ignored x", "↑5" in out, out)

        # ============ 3. parse errors keep the old program ============ #
        app.send(["\x1b"], wait=0.4)
        make_stub_editor("printf 'бредятина\\n' > \"$1\"\n")
        # the stub script is read at exec time, so rewriting works
        out = app.send(["p"])
        out = app.send(["E"], wait=1.2)
        failures += not check("parse error reported", "ошибк" in out.lower(), out)
        failures += not check("old program kept after parse error",
                              "↑5" in out, out)
        failures += not check("stays in program mode after parse error",
                              "редактор" in out or "[prog]" in out, out)

        # ============ 4. empty editor: Enter and E give friendly warns ============ #
        app.send(["x"], wait=0.4)
        out = app.send(["\r"], wait=0.4)
        failures += not check("Enter on empty program warns",
                              "пуст" in out, out)
        out = app.send(["\x03"], wait=1.0)
        failures += not check("quit", "Пока" in out, out)
    finally:
        code = app.close()
    failures += not check("exit code 0", code == 0, f"code={code}")

    print(f"failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
