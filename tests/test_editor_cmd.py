#!/usr/bin/env python3
"""Check _editor_command precedence on linux and windows paths."""
import importlib.util
import os
import shutil
import sys
import tempfile

from harness import ROOT  # репозиторий, интерпретатор, временные папки
spec = importlib.util.spec_from_file_location(
    "apitor_remote", os.path.join(ROOT, "apitor_remote.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["apitor_remote"] = mod
spec.loader.exec_module(mod)

Remote = mod.Remote
dummy = Remote.__new__(Remote)

tmp = tempfile.mkdtemp(prefix="editorcmd-")
bins = os.path.join(tmp, "bin")
os.makedirs(bins)
for name in ("nvim", "nano", "vi", "edit", "notepad"):
    p = os.path.join(bins, name)
    with open(p, "w") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(p, 0o755)


def resolve(editor, visual, path, windows=False):
    saved = {k: os.environ.get(k) for k in ("EDITOR", "VISUAL", "PATH")}
    saved_win = mod.IS_WINDOWS
    try:
        for env, val in (("EDITOR", editor), ("VISUAL", visual), ("PATH", path)):
            if val is None:
                os.environ.pop(env, None)
            else:
                os.environ[env] = val
        mod.IS_WINDOWS = windows
        return dummy._editor_command()
    finally:
        for env, val in saved.items():
            if val is None:
                os.environ.pop(env, None)
            else:
                os.environ[env] = val
        mod.IS_WINDOWS = saved_win


failures = 0


def check(name, got, want):
    global failures
    ok = got == want
    failures += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {got!r}" + ("" if ok else f" != {want!r}"))


check("$EDITOR with args", resolve("myedit --inline", None, bins),
      ["myedit", "--inline"])
check("$EDITOR empty -> $VISUAL", resolve("", "vis", bins), ["vis"])
check("no env -> nvim", resolve(None, None, bins), [os.path.join(bins, "nvim")])
os.unlink(os.path.join(bins, "nvim"))
check("no nvim -> nano", resolve(None, None, bins), [os.path.join(bins, "nano")])
os.unlink(os.path.join(bins, "nano"))
check("no nano -> vi", resolve(None, None, bins), [os.path.join(bins, "vi")])
os.unlink(os.path.join(bins, "vi"))
check("nothing found -> None", resolve(None, None, bins), None)

# windows branch
check("windows: edit", resolve(None, None, bins, windows=True),
      [os.path.join(bins, "edit")])
os.unlink(os.path.join(bins, "edit"))
check("windows: edit missing -> notepad", resolve(None, None, bins, windows=True),
      [os.path.join(bins, "notepad")])
os.unlink(os.path.join(bins, "notepad"))
check("windows: none -> None", resolve(None, None, bins, windows=True), None)

# $EDITOR wins over windows fallback
check("windows: $EDITOR wins", resolve("vim", None, bins, windows=True), ["vim"])

shutil.rmtree(tmp, ignore_errors=True)
print(f"failures: {failures}")
sys.exit(1 if failures else 0)
