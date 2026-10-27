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


def rectangle_image():
    """Create 100 mm x 60 mm sample quadrilateral for interactive clicks."""
    base=np.full((121,201,3),245,np.uint8)
    for x in range(0,201,20):cv2.line(base,(x,0),(x,120),(225,220,208),1)
    for y in range(0,121,20):cv2.line(base,(0,y),(200,y),(225,220,208),1)
    cv2.rectangle(base,(0,0),(200,120),(18,83,160),3)
    cv2.putText(base,'100 x 60 mm',(22,65),cv2.FONT_HERSHEY_SIMPLEX,.48,(40,60,60),1,cv2.LINE_AA)
    pts=np.asarray([[175,125],[480,100],[510,348],[155,377]],np.float32)
    H=cv2.getPerspectiveTransform(np.float32([[0,0],[200,0],[200,120],[0,120]]),pts)
    warped=cv2.warpPerspective(base,H,(640,480))
    mask=cv2.warpPerspective(np.full(base.shape[:2],255,np.uint8),H,(640,480))
    bg=np.full((480,640,3),175,np.uint8)
    bg[mask>0]=warped[mask>0]
    cv2.imwrite(str(ROOT/'rectangle_tilted.png'),bg)


def checkerboard_image():
    """7 by 5 separated black/white tiles for per-side measurements."""
    bd=np.full((500,650,3),170,np.uint8)
    for row in range(5):
        for col in range(7):
            value=40 if (row+col)%2==0 else 235
            x,y=65+col*70,50+row*70
            cv2.rectangle(bd,(x+3,y+3),(x+67,y+67),(value,)*3,-1)
    cv2.imwrite(str(ROOT/'checkerboard_tiles.png'),bd)


if __name__=='__main__':
    grid_video('lens_grid.mp4',True)
    grid_video('plane_grid.mp4')
    foil_video()
    rectangle_image()
    checkerboard_image()
    print(*(f'{p.name}: {p.stat().st_size} bytes' for p in ROOT.glob('*.mp4')),sep='\n')
