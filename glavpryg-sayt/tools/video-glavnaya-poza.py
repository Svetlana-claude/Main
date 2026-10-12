import cv2, json
from ultralytics import YOLO
m=YOLO('yolo11m-pose.pt')
cap=cv2.VideoCapture('/home/mokeeva/main/webui/uploads/26e64b06db9a489a879121f61b7e96ec_video-2026-10-12-00-11-11-1.mp4')
fps=cap.get(5); out=[]; i=0
while True:
    ok,f=cap.read()
    if not ok: break
    if i%3==0:
        r=m(f,verbose=False,conf=0.3)[0]
        for b,k in zip(r.boxes,r.keypoints):
            kp=k.xy[0].tolist(); kc=k.conf[0].tolist()
            out.append(dict(t=round(i/fps,2),box=[round(x) for x in b.xyxy[0].tolist()],conf=round(float(b.conf),2),kp=[[round(x),round(y),round(c,2)] for (x,y),c in zip(kp,kc)]))
    i+=1
json.dump(out,open('pose.json','w')); print(i,len(out))
