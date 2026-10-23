#!/usr/bin/env bash
# Сборка 3D-просмотрщика в dist/: модели → gltfpack, код → esbuild, обложки → снимок.
#
#   bash sobrat.sh            — собрать dist/
#   bash sobrat.sh --vylozhit — собрать и разложить в сайт (public/model-3d/)
#
# dist/obshchee/        — код и стиль, общие для всех моделей (кешируются один раз)
# dist/<система>/       — index.html, model.glb, oblozhka.webp
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/node/bin:$PATH"
SAYT=/var/www/glavpryg/public/model-3d
SISTEMY=(sportivnaya-sistema lesnik-3)
PY=/home/mokeeva/main/webui/.venv/bin/python

[ -d node_modules ] || npm ci

rm -rf dist && mkdir -p dist/obshchee

# 1. Код: лёгкая страница и отдельный кусок показа, который грузится по кнопке
npx esbuild src/stranica.js --bundle --splitting --format=esm --minify \
  --target=es2020 --outdir=dist/obshchee --chunk-names='[name]-[hash]' --legal-comments=none --log-level=warning
cp src/stil.css dist/obshchee/

gz() { gzip -9 -c "$1" | wc -c; }
KOD=0
for f in dist/obshchee/prosmotr-*.js; do KOD=$((KOD + $(gz "$f"))); done

for s in "${SISTEMY[@]}"; do
  mkdir -p "dist/$s"
  # 2. Модель: геометрия из скрипта, затем сжатие meshopt и квантование
  #    (позиции 12 бит — это 0,4 мм на модели высотой 1,6 м, нормали 8 бит)
  /usr/bin/python3 "../model/$s.py"
  npx gltfpack -i "../model/$s.glb" -o "dist/$s/model.glb" -cc -kn -km -vp 12 -vn 8 >/dev/null

  # 3. Страница: вес 3D по кнопке (код + модель, сжатые) и точки меток
  KB=$(( (KOD + $(gz "dist/$s/model.glb") + 1023) / 1024 ))
  "$PY" - "$s" "$KB" <<'EOF'
import sys
from pathlib import Path
s, kb = sys.argv[1], sys.argv[2]
html = Path(f"src/{s}.html").read_text(encoding="utf-8")
metki = Path(f"../model/{s}.metki.json").read_text(encoding="utf-8")
html = html.replace("__RAZMER__", f"{kb} КБ").replace("__METKI__", metki)
# версия в адресах модели и обложки: новая сборка — новый адрес, и браузер
# не показывает прежнюю модель из кеша (сама страница отдаётся с no-cache)
import hashlib
v = hashlib.md5(Path(f"dist/{s}/model.glb").read_bytes()).hexdigest()[:8]
for a_, b_ in (('data-m3d="model.glb"', f'data-m3d="model.glb?v={v}"'),
               ('src="oblozhka.webp"', f'src="oblozhka.webp?v={v}"')):
    assert html.count(a_) == 1, a_
    html = html.replace(a_, b_)
Path(f"dist/{s}/index.html").write_text(html, encoding="utf-8")
EOF
  # 4. Обложка — снимок первого кадра самой модели
  "$PY" ../tools/oblozhka.py dist "$s"
done

# 5. Готовое сжатие для nginx (gzip_static): сервер не жмёт на каждый запрос
find dist -type f \( -name '*.js' -o -name '*.css' -o -name '*.html' -o -name '*.glb' \) -exec gzip -9 -k -n {} \;

echo "Готово: dist/"
find dist -type f ! -name '*.gz' | sort | while read -r f; do
  printf '  %-36s %7s Б, gzip %7s Б\n' "${f#dist/}" "$(wc -c < "$f")" "$(gz "$f")"
done

if [ "${1:-}" = --vylozhit ]; then
  # Права задаются на dist, а не на сайте: mokeeva не в группе www-data, и любой chmod
  # каталога сайта молча снимает с него setgid — следующее копирование получает группу
  # mokeeva, и nginx отвечает 403. Каталог пересоздаётся и наследует от public/ группу
  # www-data и setgid, вложенное — от него.
  find dist -type d -exec chmod 0750 {} \; && find dist -type f -exec chmod 0640 {} \;
  rm -rf "${SAYT:?}"
  (umask 027; mkdir "$SAYT" && cp -r dist/* "$SAYT"/)
  echo "Выложено: $SAYT"
fi
