set -e
V=/home/mokeeva/main/webui/uploads/26e64b06db9a489a879121f61b7e96ec_video-2026-10-12-00-11-11-1.mp4
O=/var/www/glavpryg/public/video
# Центр полосы 16:9 по времени (пиксели исходника 720×1280). До 7 с — по лицу и корпусу (YOLO11-pose):
# голова и бёдра в видимой части шапки при 1920×883; дальше — по действию; между точками — плавно
K="0:671 0.3:687 0.6:734 0.9:784 1.2:820 1.5:844 1.8:857 2.1:858 2.4:843 2.7:817 3.0:798 3.3:768 3.6:728 3.9:705 4.2:700 4.5:680 4.8:648 5.11:623 5.41:608 5.71:592 6.01:569 6.31:538 6.61:510 7.6:500 8.6:540 9.6:800 11.6:800 12.4:640 15.2:640 16.2:500 20:500"
Y=$(python3 - "$K" <<'P'
import sys
k=[tuple(map(float,p.split(':'))) for p in sys.argv[1].split()]
e=str(k[-1][1]-202)
for (t0,c0),(t1,c1) in reversed(list(zip(k,k[1:]))):
    s=f"(t-{t0})/{t1-t0}"
    e=f"if(lt(t\\,{t1})\\,{c0-202}+({c1-c0})*({s})*({s})*(3-2*({s}))\\,{e})"
print(e)
P
)
G="vibrance=intensity=0.4,eq=contrast=1.12:saturation=1.32:gamma=0.94,curves=all='0/0 0.25/0.21 0.75/0.8 1/1'"
X="-an -c:v libx264 -preset slow -profile:v high -pix_fmt yuv420p -g 60 -movflags +faststart"
ffmpeg -v error -y -i $V -vf "crop=720:405:0:'$Y',scale=1280:720:flags=lanczos,$G,unsharp=5:5:0.7" $X -crf 26 $O/main-hero-1080.mp4
ffmpeg -v error -y -i $V -vf "crop=720:1080:0:100,$G,unsharp=5:5:0.5" $X -crf 28 $O/main-hero-720x1080.mp4
ffmpeg -v error -y -ss 1 -i $O/main-hero-1080.mp4 -frames:v 1 -q:v 4 $O/main-hero-poster-1080.jpg
ffmpeg -v error -y -ss 1 -i $O/main-hero-720x1080.mp4 -frames:v 1 -q:v 4 $O/main-hero-poster.jpg
ls -la $O/main-hero*
