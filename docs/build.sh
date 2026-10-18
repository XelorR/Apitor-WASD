#!/usr/bin/env bash
# Сборка печатных инструкций: схемы (graphviz) -> HTML (pandoc) -> PDF (calibre).
#
# Использование:
#     docs/build.sh            # обе инструкции (ru и en)
#     docs/build.sh ru         # только русская
#     docs/build.sh en         # только английская
#
# Требуется: dot (graphviz), pandoc, ebook-convert (calibre).
# Результат: docs/img/*.svg, docs/instructions-<язык>.html и .pdf
set -euo pipefail
cd "$(dirname "$0")"

LANGS=("$@")
if [ "${#LANGS[@]}" -eq 0 ]; then
  LANGS=(ru en)
fi

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "build.sh: не найдено «$1» — установите $2" >&2
    exit 1
  fi
}
need dot "graphviz"
need pandoc "pandoc"
need ebook-convert "calibre"

# 1. Схемы: каждый diagrams/*.dot -> img/*.svg
mkdir -p img
for src in diagrams/*.dot; do
  name="$(basename "${src%.dot}")"
  dot -Tsvg "$src" -o "img/$name.svg"
  echo "схема:  img/$name.svg"
done

# 2. Инструкции: markdown -> HTML -> PDF
for lang in "${LANGS[@]}"; do
  md="instructions-$lang.md"
  if [ ! -f "$md" ]; then
    echo "build.sh: нет файла $md" >&2
    exit 1
  fi
  case "$lang" in
    ru)
      title="Пульт Apitor — инструкция для юных пилотов"
      footer="Пульт Apitor · стр. _PAGENUM_"
      ;;
    en)
      title="Apitor Remote — manual for young pilots"
      footer="Apitor Remote · page _PAGENUM_"
      ;;
    *)
      title="$lang"
      footer="_PAGENUM_"
      ;;
  esac

  pandoc "$md" -o "instructions-$lang.html" --standalone \
    --css style.css \
    --metadata title="$title" --metadata lang="$lang"
  echo "страница: instructions-$lang.html"

  # A4, номера страниц внизу, разрыв перед каждой главой (h1),
  # шрифты с кириллицей. Разрывы перед h2 выключены: подглавки
  # идут внутри главы.
  ebook-convert "instructions-$lang.html" "instructions-$lang.pdf" \
    --paper-size a4 \
    --pdf-standard-font sans \
    --pdf-sans-family "Noto Sans" \
    --pdf-mono-family "Noto Sans Mono" \
    --pdf-default-font-size 11 \
    --pdf-mono-font-size 9 \
    --pdf-page-margin-left 15 \
    --pdf-page-margin-right 15 \
    --pdf-page-margin-top 16 \
    --pdf-page-margin-bottom 20 \
    --page-breaks-before="//*[name()='h1']" \
    --pdf-footer-template="<div style=\"text-align:center;font-size:9px;color:#55606d\">$footer</div>"
  echo "готово:  instructions-$lang.pdf"
done
