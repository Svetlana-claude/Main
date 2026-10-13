# Шапка «Спортивных» (компьютер): загруженный ролик video_2026-10-12_00-15-22_1.mp4 (720×1280) —
# полоса 16:9 по группе (720×405, y=497), увеличение Real-ESRGAN realesr-general-x4v3 → 1920×1080.
# Нейросеть на процессоре ≈ 13 с на кадр (262 кадра ≈ 1 ч): запускать службой, чтобы не оборвалась с сессией:
#   sudo systemd-run --unit=sr-sportivnye --uid=mokeeva --working-directory=$PWD /bin/sh -c '... sr.py fr sr 1920'
set -e
V=${1:?путь к исходнику}
mkdir -p fr && ffmpeg -v error -y -i "$V" -vf crop=720:405:0:497 fr/%04d.png
/home/mokeeva/main/exchange/aivid/bin/python /home/mokeeva/main/exchange/esrgan/sr.py fr sr 1920
ffmpeg -v error -y -framerate 30000/1001 -i sr/%04d.png -an -vf "scale=1920:1080:flags=lanczos,format=yuv420p" \
  -c:v libx264 -preset slow -profile:v high -crf 24 -maxrate 4M -bufsize 8M -g 60 -movflags +faststart sportivnye-1080.mp4
ffmpeg -v error -y -i sportivnye-1080.mp4 -frames:v 1 -q:v 4 sportivnye-1080.jpg
