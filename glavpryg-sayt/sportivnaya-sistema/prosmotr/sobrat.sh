#!/usr/bin/env bash
# Сборка 3D-просмотрщика в dist/: модель → gltfpack, код → esbuild, обложка → снимок.
#
#   bash sobrat.sh            — собрать dist/
#   bash sobrat.sh --vylozhit — собрать и разложить в сайт (public/model-3d/sportivnaya-sistema/)
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/node/bin:$PATH"
SAYT=/var/www/glavpryg/public/model-3d/sportivnaya-sistema

[ -d node_modules ] || npm ci

rm -rf dist && mkdir -p dist

# 1. Модель: геометрия из скрипта, затем сжатие meshopt и квантование
#    (позиции 12 бит — это 0,4 мм на модели высотой 1,6 м, нормали 8 бит)
/usr/bin/python3 ../model/postroit-model.py
npx gltfpack -i ../model/ranec-syroy.glb -o dist/ranec.glb -cc -kn -km -vp 12 -vn 8 >/dev/null

# 2. Код: лёгкая страница и отдельный кусок с three.js, который грузится по кнопке
npx esbuild src/stranica.js --bundle --splitting --format=esm --minify \
  --target=es2020 --outdir=dist --chunk-names='[name]-[hash]' --legal-comments=none --log-level=warning
cp src/stil.css dist/

# 3. Сколько весит 3D после сжатия при передаче — пишется на кнопке
gz() { gzip -9 -c "$1" | wc -c; }
TYAZH=0
for f in dist/*.js dist/ranec.glb; do
  [ "$(basename "$f")" = stranica.js ] && continue
  TYAZH=$((TYAZH + $(gz "$f")))
done
KB=$(( (TYAZH + 1023) / 1024 ))
sed "s/__RAZMER__/${KB} КБ/" src/index.html > dist/index.html

# 4. Обложка — снимок первого кадра самой модели
/home/mokeeva/main/webui/.venv/bin/python ../tools/oblozhka.py dist

# 5. Готовое сжатие для nginx (gzip_static): сервер не жмёт на каждый запрос
for f in dist/*.js dist/*.css dist/*.html dist/*.glb; do gzip -9 -k -n "$f"; done

echo "Готово: dist/"
for f in dist/*; do
  case "$f" in *.gz) continue ;; esac
  printf '  %-28s %7s Б, gzip %7s Б\n' "$(basename "$f")" "$(wc -c < "$f")" "$(gz "$f")"
done
echo "  3D по кнопке (gzip): ${KB} КБ"

if [ "${1:-}" = --vylozhit ]; then
  mkdir -p "$SAYT"
  rm -f "$SAYT"/*
  cp dist/* "$SAYT"/
  chmod 0640 "$SAYT"/* && chmod 2750 "$SAYT"
  echo "Выложено: $SAYT"
fi
