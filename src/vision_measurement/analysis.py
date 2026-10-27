"""追加可能な計測モジュール。各フレームをBGRで受け取る。"""
from __future__ import annotations
from dataclasses import dataclass
import cv2
import numpy as np

@dataclass
class FrameResult:
    values: dict
    overlay: np.ndarray
    rows: list[dict] | None = None
    details: list[dict] | None = None

class Analyzer:
    name = 'base'
    def analyze(self, frame: np.ndarray, mm_per_pixel: float | None, frame_index: int) -> FrameResult:
        raise NotImplementedError

class FoilShiftAnalyzer(Analyzer):
    """明暗差の強い左右エッジを検出し、基準中心からの変位を計算。"""
    name = 'foil_shift'
    def __init__(self, roi: tuple[int,int,int,int] | None = None,
                 baseline_x: float | None = None, min_separation_px: int = 15,
                 gaussian_kernel: int = 5, sobel_kernel: int = 3, min_gradient: float = 4.):
        if gaussian_kernel < 1 or gaussian_kernel > 31 or gaussian_kernel % 2 != 1:
            raise ValueError('gaussian_kernel は 1～31 の奇数')
        if sobel_kernel not in (1,3,5,7) or min_gradient <= 0 or min_separation_px < 1:
            raise ValueError('Sobel・エッジ検出のパラメータが不正です')
        self.roi = roi; self.baseline = baseline_x; self.min_separation_px = min_separation_px
        self.gaussian_kernel = gaussian_kernel; self.sobel_kernel = sobel_kernel
        self.min_gradient = float(min_gradient)

    def analyze(self, frame, mm_per_pixel, frame_index):
        height, width = frame.shape[:2]
        x0, y0, x1, y1 = self.roi if self.roi else (0,0,width,height)
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError('ROIが画像範囲外です')
        gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        smooth = cv2.GaussianBlur(gray, (self.gaussian_kernel,self.gaussian_kernel), 0) if self.gaussian_kernel>1 else gray
        signal = np.mean(cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=self.sobel_kernel), axis=0)
        half = max(1, int(self.min_separation_px))
        # 強い立上がり・立下がりを選ぶ。幅方向に流れる箔を想定。
        rising = int(np.argmax(signal))
        candidates = np.arange(len(signal))
        falling_score = np.where(np.abs(candidates-rising)>=half, -signal, -np.inf)
        falling = int(np.argmax(falling_score))
        peak = min(float(signal[rising]), float(-signal[falling]))
        valid = bool(peak > self.min_gradient and np.isfinite(peak))
        overlay = frame.copy()
        cv2.rectangle(overlay, (x0,y0),(x1-1,y1-1),(120,200,200),1)
        data={'frame': frame_index, 'valid': valid}
        if not valid:
            data.update(left_px=None,right_px=None,width_px=None,center_px=None,shift_px=None,
                        left_mm=None,right_mm=None,width_mm=None,center_mm=None,shift_mm=None)
            return FrameResult(data, overlay)
        left, right = sorted([x0+rising, x0+falling])
        center = 0.5*(left+right)
        if self.baseline is None:
            self.baseline = center
        shift = center-self.baseline
        data.update(left_px=left,right_px=right,width_px=right-left,center_px=center,
                    shift_px=shift, left_mm=left*mm_per_pixel if mm_per_pixel else None,
                    right_mm=right*mm_per_pixel if mm_per_pixel else None,
                    width_mm=(right-left)*mm_per_pixel if mm_per_pixel else None,
                    center_mm=center*mm_per_pixel if mm_per_pixel else None,
                    shift_mm=shift*mm_per_pixel if mm_per_pixel else None)
        cv2.line(overlay,(left,y0),(left,y1-1),(255,100,30),2)
        cv2.line(overlay,(right,y0),(right,y1-1),(255,100,30),2)
        cv2.line(overlay,(round(self.baseline),y0),(round(self.baseline),y1-1),(0,255,255),1)
        label = f'shift {data["shift_mm"]:.3f} mm' if mm_per_pixel else f'shift {shift:.2f} px'
        cv2.putText(overlay,label,(max(3,x0+5),max(18,y0+22)),cv2.FONT_HERSHEY_SIMPLEX,0.55,(0,200,0),2)
        return FrameResult(data, overlay)

class CheckerboardAnalyzer(Analyzer):
    """Detect both black and white squares; export each ID's four sides."""
    name='checkerboard'
    def __init__(self, roi=None, polarity='both', threshold='otsu',
                 min_area=120, full_cells_only=True):
        self.roi=roi
        self.polarity=polarity
        self.threshold=threshold
        self.min_area=int(min_area)
        self.full_cells_only=full_cells_only

    def analyze(self,frame,mm_per_pixel,frame_index):
        from .checkerboard import detect_cells, measure_cell
        cells=detect_cells(frame,roi=self.roi,polarity=self.polarity,threshold=self.threshold,
                           min_area=self.min_area,full_cells_only=self.full_cells_only)
        overlay=frame.copy()
        rows=[measure_cell(cell,mm_per_pixel,frame_index) for cell in cells]
        for cell in cells:
            pts=np.round(cell.corners).astype(np.int32)
            cv2.polylines(overlay,[pts],True,(40,210,50) if cell.color=='dark' else (255,80,50),2)
            pos=(int(cell.center[0]-8),int(cell.center[1]+5))
            cv2.putText(overlay,str(cell.id),pos,cv2.FONT_HERSHEY_SIMPLEX,.48,(0,0,255),2)
        if self.roi is not None:
            x0,y0,x1,y1=self.roi
            cv2.rectangle(overlay,(x0,y0),(x1-1,y1-1),(0,170,240),1)
        summary={'frame':frame_index,'valid':bool(cells),'cell_count':len(cells),
                 'edge_count':len(cells)*4,
                 'mean_edge_mm':float(np.mean([r['mean_mm'] for r in rows])) if rows and mm_per_pixel is not None else None,
                 'std_edge_mm':float(np.std([r[f'{side}_mm'] for r in rows
                                          for side in ('top','right','bottom','left')]))
                               if rows and mm_per_pixel is not None else None}
        return FrameResult(summary,overlay,rows)

class EdgeAnalyzer(Analyzer):
    name='edge'
    def __init__(self, low=50, high=150, roi=None): self.low=low;self.high=high;self.roi=roi
    def analyze(self,frame,mm_per_pixel,frame_index):
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        edges=np.zeros_like(gray)
        if self.roi is None:
            edges=cv2.Canny(gray,self.low,self.high)
        else:
            x0,y0,x1,y1=self.roi
            if not (0<=x0<x1<=frame.shape[1] and 0<=y0<y1<=frame.shape[0]):raise ValueError('ROIが画像外です')
            edges[y0:y1,x0:x1]=cv2.Canny(gray[y0:y1,x0:x1],self.low,self.high)
        overlay=frame.copy();overlay[edges>0]=(0,0,255)
        return FrameResult({'frame':frame_index,'edge_pixels':int(np.count_nonzero(edges))},overlay)


def create_analyzer(name: str, **options) -> Analyzer | None:
    if name in ('none', '', None): return None
    if name == 'foil_bottom':
        from .foil_bottom import FoilBottomAnalyzer
        return FoilBottomAnalyzer(**options)
    cls={'foil_shift':FoilShiftAnalyzer,'checkerboard':CheckerboardAnalyzer,'edge':EdgeAnalyzer}.get(name)
    if cls is None: raise ValueError(f'未対応の計測モジュール: {name}')
    return cls(**options)
