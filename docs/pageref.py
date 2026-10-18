#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Номера страниц для ссылок в инструкциях («см. раздел 5, стр. 6»).

В тексте инструкций стоят метки вида ``{{page:12}}`` — это «номер страницы
главы 12 в собранном PDF». Заранее он неизвестен: pagination зависит от
вёрстки, картинок и правок текста. Поэтому сборка идёт в два-три прохода
(см. ``build.sh``):

1. ``pageref.py fill ru`` — подставить номера из карты (первый проход без
   карты ставит ``??``);
2. pandoc + calibre собирают ``instructions-ru.pages.md`` -> PDF;
3. ``pageref.py scan ru`` — прочитать PDF через ``pdftotext`` (poppler)
   и записать карту «глава -> страница»;
4. повторить, пока карта не перестанет меняться.

Глава считается найденной, если её заголовок стоит в начале страницы:
перед каждой главой в build.sh включён разрыв страницы, а на странице
содержания заголовки идут не первыми.

Использование:
    docs/pageref.py fill ru [--map instructions-ru.pages.json]
    docs/pageref.py scan ru [--map instructions-ru.pages.json]
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
PLACEHOLDER = re.compile(r"\{\{page:(\d+)\}\}")
HEADING = re.compile(r"^#\s+(\d+)\.\s+(.+?)\s*$")


def source(lang: str) -> pathlib.Path:
    return ROOT / f"instructions-{lang}.md"


def filled(lang: str) -> pathlib.Path:
    return ROOT / f"instructions-{lang}.pages.md"


def read_map(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    pages = {}
    for key, value in data.items():
        try:
            pages[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return pages


def headings(lang: str) -> dict:
    """Заголовки глав так, как они печатаются: «12» -> «12. Макрос и обратный проезд»."""
    titles = {}
    for line in source(lang).read_text(encoding="utf-8").splitlines():
        match = HEADING.match(line)
        if match:
            titles[match.group(1)] = f"{match.group(1)}. {match.group(2)}"
    return titles


def cmd_fill(args) -> int:
    text = source(args.lang).read_text(encoding="utf-8")
    pages = read_map(args.map)
    unknown = set()

    def substitute(match: re.Match) -> str:
        number = match.group(1)
        page = pages.get(number)
        if page is None:
            unknown.add(number)
            return "??"
        return str(page)

    result, count = PLACEHOLDER.subn(substitute, text)
    filled(args.lang).write_text(result, encoding="utf-8")
    print(f"{filled(args.lang).name}: меток {count}, глав в карте {len(pages)}")
    if unknown:
        print("  без номера: " + ", ".join(f"раздел {n}" for n in sorted(unknown, key=int)))
    return 0


def page_texts(pdf: pathlib.Path) -> list:
    try:
        done = subprocess.run(
            ["pdftotext", "-layout", str(pdf), "-"],
            capture_output=True, check=True,
        )
    except FileNotFoundError:
        print("pageref.py: нужен pdftotext (пакет poppler)", file=sys.stderr)
        raise SystemExit(1)
    except subprocess.CalledProcessError as exc:
        print(f"pageref.py: pdftotext не смог прочитать {pdf}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    return done.stdout.decode("utf-8", "replace").split("\f")


def cmd_scan(args) -> int:
    titles = headings(args.lang)
    pdf = ROOT / f"instructions-{args.lang}.pdf"
    pages = page_texts(pdf)
    found = {}
    for index, text in enumerate(pages, start=1):
        lines = [line.strip() for line in text.splitlines()]
        first = next((line for line in lines if line), "")
        if not first:
            continue
        for number, title in titles.items():
            if number in found:
                continue
            if first == title or first.startswith(title):
                found[number] = index
    missing = [number for number in titles if number not in found]
    ordered = {number: found[number] for number in sorted(found, key=int)}
    try:
        args.map.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"pageref.py: не записать карту {args.map}: {exc}", file=sys.stderr)
        return 1
    layout = ", ".join(f"{number}->{found[number]}" for number in sorted(found, key=int))
    print(f"{args.map.name}: {len(found)} глав ({layout})")
    if missing:
        print("  не найдены на страницах: " + ", ".join(sorted(missing, key=int)))
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="номера страниц для инструкций")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("fill", "scan"):
        item = sub.add_parser(name, help={"fill": "подставить номера в текст",
                                          "scan": "прочитать номера из PDF"}[name])
        item.add_argument("lang", help="язык инструкции (ru, en)")
        item.add_argument("--map", type=pathlib.Path,
                          help="файл карты (по умолчанию instructions-<lang>.pages.json)")
    args = parser.parse_args(argv)
    if args.map is None:
        args.map = ROOT / f"instructions-{args.lang}.pages.json"
    if not source(args.lang).exists():
        print(f"pageref.py: нет файла {source(args.lang)}", file=sys.stderr)
        return 1
    return cmd_fill(args) if args.command == "fill" else cmd_scan(args)


if __name__ == "__main__":
    sys.exit(main())
