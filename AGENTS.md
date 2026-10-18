# Apitor-WASD

Single-file Python CLI remote for Apitor robots (R, J, S, Q, X, Wheels) over Bluetooth LE via the `apitor-ble` library. The whole app is one module, `apitor_remote.py` (~2500 lines). There are **no tests, no CI, no packages, no lint/typecheck/format config** — do not look for `pytest`, `ruff`, `mypy`, or a `pyproject.toml`.

## Commands

- Install: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (Python 3.10+; only dependency: `apitor-ble>=0.3.0`)
- Run: `.venv/bin/python apitor_remote.py` — requires a real terminal (exits 2 if stdin is not a TTY)
- Without a robot: `.venv/bin/python apitor_remote.py --simulate` — prints BLE command frames to stdout instead of connecting (use this to verify changes)
- Run a program file: `.venv/bin/python apitor_remote.py --program examples/квадрат.txt` (`examples/square.txt` is the English version)
- Build the printable kids' manual: `docs/build.sh` (needs `pandoc`, `graphviz`, `calibre`; markdown + `docs/diagrams/*.dot` → `docs/img/*.svg` + `docs/instructions-{ru,en}.pdf`)
- Exit codes: `0` clean quit, `2` error (bad profile, unreadable program file, no TTY), `130` Ctrl+C

## Gotchas

- Key-state (reading real key press/release from `/dev/input/event*`) is always attempted on Linux and is the default hold behavior; it needs the `input` group (`sudo usermod -aG input "$USER"`, then re-log) or root, otherwise the app warns and falls back to auto-stop by `--hold-timeout`. `sudo` works but is not recommended: it creates root-owned state files in `~/.config/apitor-control/`. There is no enable flag; `--key-state-device` restricts which devices are watched, and holding Shift boosts the speed to 12 in remote mode only (restored on release).
- State lives in `~/.config/apitor-control/`: `addresses.json` (one cached Bluetooth address per model), `config.json` (lang, timings, journal), `runs.log`. Program files and the `_draft.txt` autosave live in `programs/` next to the script (overridable with `--program-dir` or `program_dir` in config). Flag priority: CLI flag → `config.json` → default.
- With a cached address, `q` connects directly without scanning; `--no-cache` disables this. If the cached robot is off, the app falls back to scanning and updates the cache.
- Robot drive directions are unverified on hardware for Robot R — after connecting, press `t` (test drive) and use `--flip-left/--flip-right` or `--left-motor/--right-motor` if directions are wrong.
- `Ctrl+C` stops all motors and disconnects before exiting.
- `--tui` draws a full-screen dashboard (status bar, log, program row, hints) on the alternate screen with raw ANSI codes — no external deps. All output goes through `Remote._emit`/`_say` (tag-aware: `Tui.note(tag, text)`), prompts render in the bottom bar from `self.prompt` (`title`/`text` keys), the external `$EDITOR` pauses (leaves the alt screen) and resumes the TUI, and `SIGWINCH` triggers a redraw. Non-TUI output must stay byte-identical to the old plain prints.
- Program files are plain text: RU and EN words both accepted (`вперёд` = `forward`/`up`, `назад` = `back`/`down`, `right` also as `rght`), single-symbol shorthand shown in the editor row is also parsed (`↑` `↓` `←` `→` `‖` `✦` `●3`, e.g. `↑5 →2`), `#` comments, `e`/`ё` and case forgiven, `×`/`*`/`,` as separators.
- `docs/` is the printable RU/EN kids' manual: `instructions-*.md` + `diagrams/*.dot` + `style.css`, built by `docs/build.sh` (pandoc → HTML → calibre `ebook-convert` PDF with `--paper-size a4`, `--page-breaks-before="//*[name()='h1']"` — one page per chapter — and footer numbers via `--pdf-footer-template`). Generated `img/*.svg` and the PDFs are committed; `docs/*.html` is gitignored. No emoji in the text (no font coverage in PDF): use the program symbols `↑ ↓ ← → ‖ ✦ ●` and `★` instead.
