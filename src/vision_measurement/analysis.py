"""追加可能な計測モジュール。各フレームをBGRで受け取る。"""
from __future__ import annotations
from dataclasses import dataclass
import cv2
import numpy as np

@dataclass
class FrameResult:
    values: dict
    overlay: np.ndarray

class Analyzer:
    name = 'base'
    def analyze(self, frame: np.ndarray, mm_per_pixel: float | None, frame_index: int) -> FrameResult:
        raise NotImplementedError

class FoilShiftAnalyzer(Analyzer):
    """明暗差の強い左右エッジを検出し、基準中心からの変位を計算。"""
    name = 'foil_shift'
    def __init__(self, roi: tuple[int,int,int,int] | None = None,
                 baseline_x: float | None = None, min_separation_px: int = 15):
        self.roi = roi; self.baseline = baseline_x; self.min_separation_px = min_separation_px

    def analyze(self, frame, mm_per_pixel, frame_index):
        height, width = frame.shape[:2]
        x0, y0, x1, y1 = self.roi if self.roi else (0,0,width,height)
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError('ROIが画像範囲外です')
        gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        smooth = cv2.GaussianBlur(gray, (5,5), 0)
        signal = np.mean(cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3), axis=0)
        half = max(1, int(self.min_separation_px))
        # 強い立上がり・立下がりを選ぶ。幅方向に流れる箔を想定。
        rising = int(np.argmax(signal))
        candidates = np.arange(len(signal))
        falling_score = np.where(np.abs(candidates-rising)>=half, -signal, -np.inf)
        falling = int(np.argmax(falling_score))
        peak = min(float(signal[rising]), float(-signal[falling]))
        valid = bool(peak > 4 and np.isfinite(peak))
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
    """チェッカーボード交点間の水平・垂直距離（角点数を指定）。"""
    name='checkerboard'
    def __init__(self, inner_corners: tuple[int,int] = (7,7)):
        self.inner_corners=inner_corners

    def analyze(self, frame, mm_per_pixel, frame_index):
        gray=cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ok, corners = cv2.findChessboardCornersSB(gray,self.inner_corners)
        overlay=frame.copy()
        if not ok:
            return FrameResult({'frame':frame_index,'valid':False,'mean_edge_mm':None,'std_edge_mm':None},overlay)
        cv2.drawChessboardCorners(overlay,self.inner_corners,corners,ok)
        p=corners.reshape(self.inner_corners[1],self.inner_corners[0],2)
        distances=np.r_[np.linalg.norm(np.diff(p,axis=0),axis=2).ravel(),
                        np.linalg.norm(np.diff(p,axis=1),axis=2).ravel()]
        factor=mm_per_pixel if mm_per_pixel is not None else 1.
        return FrameResult({'frame':frame_index,'valid':True,'mean_edge_mm':float(np.mean(distances)*factor) if mm_per_pixel else None,
                            'std_edge_mm':float(np.std(distances)*factor) if mm_per_pixel else None,
                            'mean_edge_px':float(np.mean(distances))}, overlay)

class EdgeAnalyzer(Analyzer):
    name='edge'
    def __init__(self, low=50, high=150): self.low=low;self.high=high
    def analyze(self,frame,mm_per_pixel,frame_index):
        edges=cv2.Canny(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),self.low,self.high)
        overlay=frame.copy();overlay[edges>0]=(0,0,255)
        return FrameResult({'frame':frame_index,'edge_pixels':int(np.count_nonzero(edges))},overlay)


def create_analyzer(name: str, **options) -> Analyzer | None:
    if name in ('none', '', None): return None
    cls={'foil_shift':FoilShiftAnalyzer,'checkerboard':CheckerboardAnalyzer,'edge':EdgeAnalyzer}.get(name)
    if cls is None: raise ValueError(f'未対応の計測モジュール: {name}')
    return cls(**options)
