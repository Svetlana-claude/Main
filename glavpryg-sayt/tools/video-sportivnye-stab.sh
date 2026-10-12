# Шапка «Спортивных» (компьютер): стабилизация ролика Wikimedia Commons
# File:Skydive-video-formationpractice-2013.ogv (Pigheart, CC BY-SA 4.0), отрезок 2,5–19,02 с.
set -e
curl -sL -A "Mozilla/5.0 glavpryg" -o src.ogv "https://commons.wikimedia.org/wiki/Special:FilePath/Skydive-video-formationpractice-2013.ogv"
ffmpeg -v error -y -ss 2.5 -t 16.52 -i src.ogv -an -vf vidstabdetect=shakiness=10:accuracy=15:stepsize=6:result=s.trf -f null -
ffmpeg -v error -y -ss 2.5 -t 16.52 -i src.ogv -an -vf "vidstabtransform=input=s.trf:smoothing=30:optzoom=1:interpol=bicubic,unsharp=5:5:0.4,format=yuv420p" \
  -c:v libx264 -preset slow -profile:v high -crf 31 -maxrate 2.5M -bufsize 5M -g 50 -movflags +faststart sportivnye-gruppa-1080.mp4
ffmpeg -v error -y -i sportivnye-gruppa-1080.mp4 -frames:v 1 -q:v 4 sportivnye-gruppa-1080.jpg
