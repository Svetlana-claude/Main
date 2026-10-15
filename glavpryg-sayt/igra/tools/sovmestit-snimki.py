import cv2, numpy as np
W=cv2.imread('img-002.png'); D=cv2.imread('img-003.png')
g1=cv2.cvtColor(W,cv2.COLOR_BGR2GRAY); g2=cv2.cvtColor(D,cv2.COLOR_BGR2GRAY)
# деталь уменьшаем примерно к масштабу обзорного
s=0.25; g2s=cv2.resize(g2,None,fx=s,fy=s,interpolation=cv2.INTER_AREA)
sift=cv2.SIFT_create(8000)
k1,d1=sift.detectAndCompute(g1,None); k2,d2=sift.detectAndCompute(g2s,None)
m=cv2.BFMatcher().knnMatch(d2,d1,k=2)
good=[a for a,b in m if a.distance<0.75*b.distance]
src=np.float32([k2[a.queryIdx].pt for a in good])/s; dst=np.float32([k1[a.trainIdx].pt for a in good])
M,inl=cv2.estimateAffinePartial2D(src,dst,method=cv2.RANSAC,ransacReprojThreshold=4)
print(len(good), int(inl.sum())); print(M)
sc=np.hypot(M[0,0],M[1,0]); ang=np.degrees(np.arctan2(M[1,0],M[0,0])); print('scale',sc,'angle',ang)
np.save('M.npy',M)
warp=cv2.warpAffine(D,M,(W.shape[1],W.shape[0]))
mask=cv2.warpAffine(np.full(D.shape[:2],255,np.uint8),M,(W.shape[1],W.shape[0]))
out=W.copy(); out[mask>0]=(0.5*out[mask>0]+0.5*warp[mask>0]).astype(np.uint8)
x,y,w,h=cv2.boundingRect(mask); print('bbox',x,y,w,h)
cv2.imwrite('check-align.jpg',cv2.resize(out[max(0,y-100):y+h+100,max(0,x-100):x+w+100],None,fx=0.8,fy=0.8))
