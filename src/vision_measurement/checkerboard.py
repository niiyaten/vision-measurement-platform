"""Checkerboard cell measurements based on the previous offline HTML application.

Binary connected components identify candidate tiles. Tile sizes are measured
from grayscale intensity transitions: sample points, fit four lines, intersect
neighboring lines. Erosion is never used as a measurement contour.
"""
from __future__ import annotations
from dataclasses import dataclass
import cv2
import numpy as np


@dataclass
class Cell:
    id: int
    color: str
    corners: np.ndarray  # clockwise TL,TR,BR,BL, original image pixels
    center: tuple[float,float]


def _corners_from_extrema(pts: np.ndarray) -> np.ndarray | None:
    pts = np.asarray(pts, np.float64).reshape(-1,2)
    sums = pts[:,0] + pts[:,1]
    diffs = pts[:,0] - pts[:,1]
    quad = np.asarray([pts[np.argmin(sums)], pts[np.argmax(diffs)],
                       pts[np.argmax(sums)], pts[np.argmin(diffs)]], np.float64)
    if len(np.unique(np.round(quad,2),axis=0)) != 4:
        return None
    if abs(cv2.contourArea(quad.astype(np.float32))) < 30:
        return None
    return quad


def _refine_square(gray: np.ndarray, rough: np.ndarray, polarity: int,
                   search_px: float = 5.0) -> np.ndarray | None:
    """Line-fit at each side's grayscale transition, returning four intersections."""
    h,w = gray.shape
    lines=[]
    offsets = np.arange(-search_px,search_px+.001,.25, dtype=np.float32)
    ts = np.linspace(.22,.78,13, dtype=np.float32)
    for i in range(4):
        a,b = rough[i],rough[(i+1)%4]
        d=b-a
        length=np.linalg.norm(d)
        if length<10:return None
        nx,ny = d[1]/length,-d[0]/length
        centers=a[None,:]+ts[:,None]*d[None,:]
        xx=centers[:,0,None] + offsets[None,:]*nx
        yy=centers[:,1,None] + offsets[None,:]*ny
        if (xx.min()<2 or yy.min()<2 or xx.max()>w-3 or yy.max()>h-3):return None
        def sample(shift):
            return cv2.remap(gray, (xx+shift*nx).astype(np.float32),
                             (yy+shift*ny).astype(np.float32), cv2.INTER_LINEAR).astype(np.float64)
        contrast = polarity*(sample(.8)-sample(-.8))
        idx=np.argmax(contrast,axis=1)
        strength=contrast[np.arange(len(ts)),idx]
        chosen=strength>=13
        if chosen.sum()<7:return None
        chosen_offsets=offsets[idx[chosen]]
        if np.std(chosen_offsets)>1.5:return None
        xy=centers[chosen]+chosen_offsets[:,None]*np.array([nx,ny])
        weights=strength[chosen]
        mean=np.average(xy,axis=0,weights=weights)
        normalized=(xy-mean)*np.sqrt(weights[:,None])
        _,_,vt=np.linalg.svd(normalized,full_matrices=False)
        tangent=vt[0]
        normal=np.array([-tangent[1],tangent[0]])
        if normal.dot([nx,ny])<0:normal=-normal
        lines.append((normal,float(normal.dot(mean))))
    corners=[]
    for i in range(4):
        n1,c1=lines[(i+3)%4];n2,c2=lines[i]
        mat=np.stack([n1,n2])
        if abs(np.linalg.det(mat))<.16:return None
        corners.append(np.linalg.solve(mat,[c1,c2]))
    corners=np.asarray(corners)
    a0=abs(cv2.contourArea(rough.astype(np.float32)))
    a1=abs(cv2.contourArea(corners.astype(np.float32)))
    if not (.65*a0<a1<1.9*a0):return None
    lengths=np.linalg.norm(np.roll(corners,-1,axis=0)-corners,axis=1)
    if min(lengths)<8 or max(lengths)/min(lengths)>3.3:return None
    return corners


def detect_cells(frame: np.ndarray, roi: tuple[int,int,int,int] | None = None,
                 polarity: str = 'both', threshold: str = 'otsu',
                 min_area: int = 120, full_cells_only: bool = True) -> list[Cell]:
    """Detect black/white square cells, label in reading order, refine four sides.

    Uses source-resolution gray values for all edge measurements.
    """
    if polarity not in {'both','dark','light'}:raise ValueError('polarity must be both/dark/light')
    if threshold not in {'otsu','adaptive'}:raise ValueError('threshold must be otsu/adaptive')
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY) if frame.ndim==3 else frame
    h,w=gray.shape
    x0,y0,x1,y1=roi or (0,0,w,h)
    if not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError('ROIが画像外です')
    window=gray[y0:y1,x0:x1]
    if threshold=='otsu':
        _,black=cv2.threshold(window,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
    else:
        block=max(15,min(121,min(window.shape)//2*2-1))
        if block%2==0:block-=1
        black=cv2.adaptiveThreshold(window,255,cv2.ADAPTIVE_THRESH_MEAN_C,
                                    cv2.THRESH_BINARY_INV,block,5)
    # A third (gray) background may be present. A plain inverse-Otsu mask
    # would join the white squares to that background. Separate the upper
    # intensity mode instead; binary black/white inputs still work.
    mid=float(np.median(window))
    high=float(np.quantile(window,.99))
    white_threshold=min(254., max(0.,(mid+high)/2.-.25))
    white=(window>white_threshold).astype(np.uint8)*255
    masks={'dark':black, 'light':white}
    ker=cv2.getStructuringElement(cv2.MORPH_CROSS,(3,3))
    raw=[]
    for tag in (['dark','light'] if polarity=='both' else [polarity]):
        mask=cv2.erode(masks[tag],ker,iterations=1)
        n,labels,stats,centroids=cv2.connectedComponentsWithStats(mask,connectivity=4)
        candidates=[]
        for j in range(1,n):
            left,top,bw,bh,area=map(int,stats[j])
            if area<min_area or area>window.size*.14 or min(bw,bh)<10:continue
            if (left<=1 or top<=1 or left+bw>=window.shape[1]-2
                    or top+bh>=window.shape[0]-2):continue
            ratio=max(bw/bh,bh/bw)
            if ratio>3.4 or area/(bw*bh)<.24:continue
            yy,xx=np.where(labels[top:top+bh,left:left+bw]==j)
            points=np.column_stack([xx+left+x0,yy+top+y0]).astype(np.float64)
            rough=_corners_from_extrema(points)
            if rough is not None:
                candidates.append((area,tuple(centroids[j]+[x0,y0]),rough))
        if full_cells_only and candidates:
            # Densest cluster of similarly sized tiles, matching the HTML tool.
            sizes=np.asarray([c[0] for c in candidates]);density=((sizes[:,None]>=sizes[None,:]/1.18)&
                                                (sizes[:,None]<=sizes[None,:]*1.18)).sum(axis=1)
            anchor=sizes[np.argmax(density)]
            candidates=[c for c in candidates if .70*anchor<=c[0]<=1.43*anchor]
        for _,center,rough in candidates:
            refined=_refine_square(gray,rough,1 if tag=='dark' else -1)
            if refined is not None:raw.append((center,tag,refined))
    # Sort by scan rows (a slight tilt should not change the ID order).
    if not raw:return []
    sizes=np.asarray([np.linalg.norm(x[2][1]-x[2][0]) for x in raw])
    row_tol=max(6,float(np.median(sizes))*.40)
    raw.sort(key=lambda item:item[0][1])
    grouped=[]
    for item in raw:
        if not grouped or abs(item[0][1] - np.mean([it[0][1] for it in grouped[-1]]))>row_tol:
            grouped.append([])
        grouped[-1].append(item)
    ordered=[item for row in grouped for item in sorted(row,key=lambda a:a[0][0])]
    return [Cell(i+1,tag,corners,(float(center[0]),float(center[1])))
            for i,(center,tag,corners) in enumerate(ordered)]


def measure_cell(cell: Cell, mm_per_pixel: float | None, frame_index: int) -> dict:
    distances=np.linalg.norm(np.roll(cell.corners,-1,axis=0)-cell.corners,axis=1)
    mm=distances*mm_per_pixel if mm_per_pixel is not None else [None]*4
    keys=['top','right','bottom','left']
    row={'frame':frame_index,'id':cell.id,'color':cell.color,'valid':True,
         'center_x_px':cell.center[0],'center_y_px':cell.center[1]}
    row.update({f'{name}_px':float(d) for name,d in zip(keys,distances)})
    row.update({f'{name}_mm':float(d) if d is not None else None for name,d in zip(keys,mm)})
    row.update(mean_px=float(np.mean(distances)),std_px=float(np.std(distances,ddof=0)),
               mean_mm=float(np.mean(mm)) if mm_per_pixel is not None else None,
               std_mm=float(np.std(mm,ddof=0)) if mm_per_pixel is not None else None)
    return row
