import cv2, numpy as np, json
W=cv2.imread('img-002.png'); D=cv2.imread('img-003.png'); M=np.load('M.npy')
PXM=1.78                      # пикселей детального снимка на метр
# центр круга на детальном снимке — ищем оранжевую точку возле (601,822)
roi=D[760:890,540:670].astype(int); b,g,r=roi[...,0],roi[...,1],roi[...,2]
sel=(r>170)&(r-b>60)&(g<190); ys,xs=np.nonzero(sel)
cx,cy=(540+xs.mean(),760+ys.mean()) if len(xs) else (601,822); print('цель',cx,cy,len(xs))
# снимаем подписи-разметку с детального снимка
m=np.zeros(D.shape[:2],np.uint8)
white=(D.min(axis=2)>205).astype(np.uint8)*255
reg=np.zeros_like(m); cv2.rectangle(reg,(100,200),(950,1260),255,-1); cv2.rectangle(reg,(1000,30),(1500,480),255,-1)
m=cv2.dilate(cv2.bitwise_and(white,reg),np.ones((5,5),np.uint8),iterations=2)
Dc=cv2.inpaint(D,m,7,cv2.INPAINT_TELEA); cv2.imwrite('detal-chisto.png',Dc)
# мир: метры, ноль — цель, x на восток, y на юг; обзорный снимок переводим в кадр детального
Mi=cv2.invertAffineTransform(M)      # обзорный -> детальный
h,w=W.shape[:2]; c=np.array([[0,0],[w,0],[0,h],[w,h]],float)
cd=(np.c_[c,np.ones(4)]@Mi.T); cm=(cd-[cx,cy])/PXM
x0,y0=cm.min(0); x1,y1=cm.max(0); print('мир, м',x0,y0,x1,y1)
# вписанный прямоугольник без пустых углов: берём с запасом внутрь
FAR=0.5                               # пикселей дальнего слоя на метр
X0,Y0,X1,Y1=[int(v) for v in (x0+150,y0+150,x1-150,y1-150)]
fw,fh=int((X1-X0)*FAR),int((Y1-Y0)*FAR)
# мир(м) -> детальный px -> обзорный px
A=np.array([[1/FAR/1,0,X0],[0,1/FAR,Y0]])  # far px -> м
def compose(Aff,B):  # Aff∘B, 2x3
    return (np.vstack([Aff,[0,0,1]])@np.vstack([B,[0,0,1]]))[:2]
m2d=np.array([[PXM,0,cx],[0,PXM,cy]])
T=compose(M,compose(m2d,A))
far=cv2.warpAffine(W,T,(fw,fh),flags=cv2.WARP_INVERSE_MAP|cv2.INTER_AREA,borderMode=cv2.BORDER_REFLECT)

cv2.imwrite('far.png',far)
# ближний слой — детальный снимок, 1,2 px/м, в своих границах
NEAR=1.2
dh,dw=D.shape[:2]
NX0,NY0=int(-cx/PXM)+15,int(-cy/PXM)+15; NX1,NY1=int((dw-cx)/PXM)-15,int((dh-cy)/PXM)-15
nw,nh=int((NX1-NX0)*NEAR),int((NY1-NY0)*NEAR)
Tn=compose(m2d,np.array([[1/NEAR,0,NX0],[0,1/NEAR,NY0]]))
near=cv2.warpAffine(Dc,Tn,(nw,nh),flags=cv2.WARP_INVERSE_MAP|cv2.INTER_AREA)
cv2.imwrite('near.png',near)
# маска 5 м/px: 0 поле, 1 лес, 2 вода
MS=0.2
mw,mh=int((X1-X0)*MS),int((Y1-Y0)*MS)
small=cv2.resize(far,(mw,mh),interpolation=cv2.INTER_AREA)
hsv=cv2.cvtColor(small,cv2.COLOR_BGR2HSV)
v=hsv[...,2].astype(int)
hh=hsv[...,0].astype(int); ss=hsv[...,1].astype(int)
forest=(((hh>=42)&(v<165))|(v<85)).astype(np.uint8)
forest=cv2.morphologyEx(forest,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
mask=forest.copy()
# вода — пруды на севере, обведены по снимку (метры мира = −1608 + x/0,24, −1762 + y/0,24)
water=np.zeros_like(mask)
for poly in ([(588,66),(612,62),(645,78),(690,112),(712,140),(690,152),(650,128),(615,104),(592,92)],
             [(196,146),(236,146),(240,166),(198,168)]):
    mir=np.array(poly)/0.24+[-1608,-1762]
    cv2.fillPoly(water,[np.int32((mir-[X0,Y0])*MS)],1)
mask[water==1]=2
pass
vis=small.copy(); vis[mask==1]=(0,0,255); vis[mask==2]=(255,120,0); cv2.imwrite('mask-vis.jpg',cv2.resize(vis,None,fx=1.2,fy=1.2))
cv2.imwrite('mask.png',mask)
json.dump(dict(far=[X0,Y0,X1,Y1,FAR],near=[NX0,NY0,NX1,NY1,NEAR],mask=[X0,Y0,MS]),open('world.json','w'))
print('far',fw,fh,'near',nw,nh,'mask',mw,mh)

# подгонка цвета ближнего слоя под дальний (LAB, среднее и разброс по общей площади)
fx0=int((NX0-X0)*FAR); fy0=int((NY0-Y0)*FAR); fx1=int((NX1-X0)*FAR); fy1=int((NY1-Y0)*FAR)
uchastok=far[fy0:fy1,fx0:fx1]
nm=cv2.resize(near,(uchastok.shape[1],uchastok.shape[0]),interpolation=cv2.INTER_AREA)
a=cv2.cvtColor(uchastok,cv2.COLOR_BGR2LAB).reshape(-1,3).astype(float); b_=cv2.cvtColor(nm,cv2.COLOR_BGR2LAB).reshape(-1,3).astype(float)
nl=cv2.cvtColor(near,cv2.COLOR_BGR2LAB).astype(float)
for k in range(3): nl[...,k]=(nl[...,k]-b_[:,k].mean())/b_[:,k].std()*a[:,k].std()+a[:,k].mean()
near=cv2.cvtColor(np.clip(nl,0,255).astype(np.uint8),cv2.COLOR_LAB2BGR); cv2.imwrite('near.png',near)
print('цвет подогнан')
