set -e
# Исходник — ролик шапки, увеличенный Real-ESRGAN в 4 раза (2880×5120); прежний исходник 720×1280 —
# 26e64b06…_video-2026-10-12-00-11-11-1.mp4, ключевые точки ниже даны в его пикселях, S — множитель
V=/home/mokeeva/main/webui/uploads/b4ff17cc36444cdeb7687765bb31822c_video-2026-10-12-00-11-11-1-realesrgan.mkv
S=4
O=/var/www/glavpryg/public/video
T=${TMPDIR:-/tmp}/video-glavnaya; mkdir -p $T
# Центр полосы 16:9 по времени (пиксели исходника 720×1280). До 7 с — по лицу и корпусу (YOLO11-pose):
# голова и бёдра в видимой части шапки при 1920×883; дальше — по действию; между точками — плавно
K="0:671 0.3:687 0.6:734 0.9:784 1.2:820 1.5:844 1.8:857 2.1:858 2.4:843 2.7:817 3.0:798 3.3:768 3.6:728 3.9:705 4.2:700 4.5:680 4.8:648 5.11:623 5.41:608 5.71:592 6.01:569 6.31:538 6.61:510 7.6:500 8.6:540 9.6:800 11.6:800 12.4:640 15.2:640 16.2:500 20:500"
Y=$(python3 - "$K" "$S" <<'P'
import sys
S=float(sys.argv[2])
k=[tuple(map(float,p.split(':'))) for p in sys.argv[1].split()]
e=str((k[-1][1]-202.5)*S)
for (t0,c0),(t1,c1) in reversed(list(zip(k,k[1:]))):
    s=f"(t-{t0})/{t1-t0}"
    e=f"if(lt(t\\,{t1})\\,{(c0-202.5)*S}+({(c1-c0)*S})*({s})*({s})*(3-2*({s}))\\,{e})"
print(e)
P
)
G="vibrance=intensity=0.4,eq=contrast=1.12:saturation=1.32:gamma=0.94,curves=all='0/0 0.25/0.21 0.75/0.8 1/1'"
# Промежуточные почти без потерь: кадрирование и цвет — один раз
M="-an -c:v libx264 -preset medium -crf 14 -pix_fmt yuv420p"
ffmpeg -v error -y -i $V -vf "crop=$((720*S)):$((405*S)):0:'$Y',scale=1920:1080:flags=lanczos,$G" $M $T/d.mp4
ffmpeg -v error -y -i $V -vf "crop=$((720*S)):$((1080*S)):0:$((100*S)),scale=720:1080:flags=lanczos,$G" $M $T/m.mp4
# Выдача: AV1 — основная (SSIM к промежуточной ≈ 0,99 при вдвое меньшем размере), H.264 — для браузеров без AV1
A="-an -c:v libsvtav1 -preset 5 -crf 38 -g 60 -pix_fmt yuv420p -movflags +faststart"
X="-an -c:v libx264 -preset slow -profile:v high -pix_fmt yuv420p -g 60 -movflags +faststart -crf 27"
ffmpeg -v error -y -i $T/d.mp4 $A $O/main-hero-1920x1080-av1.mp4
ffmpeg -v error -y -i $T/d.mp4 $X $O/main-hero-1920x1080.mp4
# телефон: 720×1080 — по размеру как прежний ролик (≈ 3,6 МБ), 1080×1620 вышел бы 5 МБ
ffmpeg -v error -y -i $T/m.mp4 ${A/-crf 38/-crf 36} $O/main-hero-720x1080-av1.mp4
ffmpeg -v error -y -i $T/m.mp4 ${X/-crf 27/-crf 26} $O/main-hero-720x1080.mp4
ffmpeg -v error -y -ss 1 -i $T/d.mp4 -frames:v 1 -q:v 7 $O/main-hero-poster-1080.jpg
ffmpeg -v error -y -ss 1 -i $T/m.mp4 -frames:v 1 -q:v 4 $O/main-hero-poster.jpg
sudo -n chgrp www-data $O/main-hero*; chmod 640 $O/main-hero*
ls -la $O/main-hero*
