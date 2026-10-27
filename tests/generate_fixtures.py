"""検証用の合成AVIを決定的に生成。会社の実データを含まない。"""
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).parent/'fixtures';ROOT.mkdir(parents=True,exist_ok=True)
W,H=640,480

def writer(name,fps=30):
    out=cv2.VideoWriter(str(ROOT/name),cv2.VideoWriter_fourcc(*'mp4v'),fps,(W,H))
    if not out.isOpened():raise RuntimeError(f'VideoWriter unavailable: {name}')
    return out


def grid_video(name,move=False):
    out=writer(name)
    pts=(np.mgrid[0:14,0:10].T.reshape(-1,2)*14.).astype(np.float32)
    obj=np.column_stack([pts,np.zeros(len(pts))])
    K=np.array([[900.,0,W/2],[0,900.,H/2],[0,0,1.]])
    for i in range(30):
        img=np.full((H,W,3),244,np.uint8)
        if move:
            rvec=np.array([0.12*np.sin(i*0.27),0.18*np.cos(i*.29),0.1*np.sin(i*.2)])
            tvec=np.array([-90+12*np.sin(i*.13),-65+13*np.cos(i*.19),680.+18*np.sin(i*.2)])
        else:
            rvec=np.array([.12,-.18,.035]);tvec=np.array([-90.,-65.,700.])
        centers,_=cv2.projectPoints(obj,rvec,tvec,K,np.zeros(5))
        for p in centers.reshape(-1,2):
            cv2.circle(img,tuple(np.rint(p).astype(int)),5,(15,15,15),-1,cv2.LINE_AA)
        cv2.putText(img,'SYNTHETIC TEST', (12,24),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,170),2)
        out.write(img)
    out.release()


def foil_video():
    out=writer('foil_shift.mp4')
    for i in range(60):
        img=np.full((H,W,3),35,np.uint8)
        offset=round(20*np.sin(i/9))
        left=220+offset;right=420+offset
        cv2.rectangle(img,(left,30),(right,H-30),(210,210,210),-1)
        cv2.putText(img,'SYNTHETIC | 0.25 mm/px', (12,23),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,0,200),2)
        out.write(img)
    out.release()

if __name__=='__main__':
    grid_video('lens_grid.mp4',True)
    grid_video('plane_grid.mp4')
    foil_video()
    print(*(f'{p.name}: {p.stat().st_size} bytes' for p in ROOT.glob('*.mp4')),sep='\n')
