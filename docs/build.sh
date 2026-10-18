#!/usr/bin/env bash
# Сборка печатных инструкций: схемы (graphviz) -> HTML (pandoc) -> PDF (calibre).
#
# Использование:
#     docs/build.sh            # обе инструкции (ru и en)
#     docs/build.sh ru         # только русская
#     docs/build.sh en         # только английская
#
# Требуется: dot (graphviz), pandoc, ebook-convert (calibre), pdftotext (poppler).
# Результат: docs/img/*.svg, docs/instructions-<язык>.html и .pdf
#
# Ссылки на страницы («см. раздел 5, стр. 6»): в тексте стоят метки
# {{page:5}}, а номера страниц подставляет pageref.py. Сборка идёт в два-три
# прохода — fill (метки -> номера), PDF, scan (какие страницы вышли) — пока
# карта страниц не перестанет меняться.
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
need pdftotext "poppler"
need python3 "python3"

# 1. Схемы: каждый diagrams/*.dot -> img/*.svg
mkdir -p img
for src in diagrams/*.dot; do
  name="$(basename "${src%.dot}")"
  dot -Tsvg "$src" -o "img/$name.svg"
  echo "схема:  img/$name.svg"
done

# 2. Одна сборка PDF: готовый текст (после pageref.py fill) -> HTML -> PDF
build_pdf() {
  local lang="$1" title="$2" footer="$3"
  pandoc "instructions-$lang.pages.md" -o "instructions-$lang.html" --standalone \
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
    --pdf-default-font-size 13 \
    --pdf-mono-font-size 11 \
    --pdf-page-margin-left 15 \
    --pdf-page-margin-right 15 \
    --pdf-page-margin-top 16 \
    --pdf-page-margin-bottom 20 \
    --page-breaks-before="//*[name()='h1']" \
    --pdf-footer-template="<div style=\"text-align:center;font-size:9px;color:#55606d\">$footer</div>"
}

# 3. Инструкции: метки страниц -> PDF -> карта страниц, и так до совпадения
for lang in "${LANGS[@]}"; do
  if [ ! -f "instructions-$lang.md" ]; then
    echo "build.sh: нет файла instructions-$lang.md" >&2
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

  map="instructions-$lang.pages.json"
  rm -f "$map"      # сначала карты нет: в тексте будут «??» до первого scan
  for pass in 1 2 3 4; do
    python3 pageref.py fill "$lang" --map "$map"
    build_pdf "$lang" "$title" "$footer"
    python3 pageref.py scan "$lang" --map "$map.new"
    if [ -f "$map" ] && cmp -s "$map" "$map.new"; then
      rm -f "$map.new"
      break
    fi
    if [ "$pass" -eq 4 ]; then
      echo "build.sh: номера страниц всё ещё меняются — проверьте метки" >&2
      rm -f "$map.new"
      break
    fi
    mv "$map.new" "$map"
  done
  echo "готово:  instructions-$lang.pdf"
done
