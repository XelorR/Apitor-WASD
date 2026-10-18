#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Прогон всех наборов tests/test_*.py — параллельно, по процессу на набор.

    .venv/bin/python tests/run_tests.py             # всё, по числу ядер
    .venv/bin/python tests/run_tests.py --jobs 1    # последовательно
    .venv/bin/python tests/run_tests.py -k 21 -k 20 # только подходящие по имени
    .venv/bin/python tests/run_tests.py --list      # перечислить наборы
    .venv/bin/python tests/run_tests.py -v          # печатать и вывод наборов

Каждый набор — отдельный процесс со своим временным каталогом (см. harness.py),
поэтому наборы не мешают друг другу и их можно гонять параллельно. В конце —
сводка и код выхода 1, если хоть одна проверка провалилась.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys
import time

import harness  # пути и фейковый HOME (импорт — уже часть общего окружения)

HERE = os.path.dirname(os.path.abspath(__file__))

PASS_RE = re.compile(r"^\[PASS\]", re.M)
FAIL_RE = re.compile(r"^\[FAIL\]", re.M)
SUMMARY_RE = re.compile(r"(failures|ОШИБОК|провалено)\D+(\d+)", re.M)


def suite_key(name: str) -> tuple:
    """Сортировка: test_apitor.py, test_apitor2.py, … без словарного порядка."""
    nums = re.findall(r"\d+", name)
    return (int(nums[0]) if nums else 10**6, name)


def discover() -> list:
    names = [n for n in os.listdir(HERE) if n.startswith("test_") and n.endswith(".py")]
    return [os.path.join(HERE, n) for n in sorted(names, key=suite_key)]


def counts(output: str) -> tuple:
    """Сколько проверок прошло и провалилось по выводу набора."""
    passed = len(PASS_RE.findall(output))
    failed = len(FAIL_RE.findall(output))
    if failed == 0:
        for what, num in SUMMARY_RE.findall(output):
            if what in ("failures", "ОШИБОК", "провалено"):
                failed = max(failed, int(num))
    return passed, failed


def run_one(path: str, timeout: float) -> dict:
    env = dict(os.environ)
    env["APITOR_TEST_PY"] = harness.PY
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [harness.PY, path], cwd=harness.ROOT, env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        output, code = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        code = -1
        output += f"\n[таймаут {timeout:g} с]"
    return {
        "path": path, "name": os.path.basename(path), "code": code,
        "output": output, "seconds": time.monotonic() - started,
    }


def fail_lines(output: str, limit: int = 12) -> str:
    lines = [ln for ln in output.splitlines() if ln.startswith("[FAIL]")]
    if not lines:  # падение без [FAIL]: покажем хвост
        lines = output.splitlines()[-limit:]
    return "\n".join(f"    {ln}" for ln in lines[:limit])


def main() -> int:
    ap = argparse.ArgumentParser(description="Прогон наборов тестов apitor_remote.py")
    ap.add_argument("--jobs", "-j", type=int, default=min(8, os.cpu_count() or 4),
                    help="сколько наборов гонять одновременно (по умолчанию — по числу ядер)")
    ap.add_argument("-k", "--filter", action="append", default=[],
                    help="подстрока имени набора (можно несколько раз)")
    ap.add_argument("--list", action="store_true", help="только перечислить наборы")
    ap.add_argument("--timeout", type=float, default=600,
                    help="таймаут на набор, с (по умолчанию 600)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="печатать полный вывод каждого набора")
    ap.add_argument("--keep", action="store_true",
                    help="не удалять временные каталоги наборов")
    args = ap.parse_args()

    suites = discover()
    if args.filter:
        suites = [p for p in suites if any(f in os.path.basename(p) for f in args.filter)]
    if not suites:
        print("наборы не найдены")
        return 1
    if args.list:
        for path in suites:
            print(os.path.relpath(path, harness.ROOT))
        return 0

    if args.keep:
        os.environ["APITOR_TEST_KEEP"] = "1"

    jobs = max(1, min(args.jobs, len(suites)))
    print(f"наборов: {len(suites)} · параллельно: {jobs} · питон: {harness.PY}")
    print()

    started = time.monotonic()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(run_one, p, args.timeout): p for p in suites}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            passed, failed = counts(res["output"])
            res["passed"], res["failed"] = passed, failed
            if res["code"] == 0 and failed == 0:
                mark = "OK  "
            else:
                mark, res["code"] = "ПРОВАЛ", res["code"] or 1
            print(f"[{mark}] {res['name']:<22} проверок {passed:>3}, "
                  f"провалено {failed}, {res['seconds']:5.1f} с")
            if mark != "OK  ":
                print(fail_lines(res["output"]))
            if args.verbose:
                print(res["output"])
            results.append(res)

    elapsed = time.monotonic() - started
    total_p = sum(r["passed"] for r in results)
    total_f = sum(r["failed"] for r in results)
    bad = [r["name"] for r in results if r["code"] != 0 or r["failed"]]
    print()
    print(f"итого: наборов {len(results)}, проверок {total_p}, провалено {total_f}, "
          f"время {elapsed:.1f} с")
    if bad:
        print("провалились:", ", ".join(sorted(bad)))
        return 1
    print("всё в порядке")
    return 0


if __name__ == "__main__":
    sys.exit(main())
