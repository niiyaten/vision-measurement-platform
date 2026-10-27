"""下端輪郭計測。校正済みBGRフレームに対する独立した計測モジュール。

座標系は画像座標（x右向き、y下向き）。正の位置ずれは下方向。
エッジ検出は ROI 内で縦方向の符号付き輝度勾配を使用する。
"""
from __future__ import annotations

import math
from typing import Literal

import cv2
import numpy as np

from .analysis import Analyzer, FrameResult


class FoilBottomAnalyzer(Analyzer):
    """電極箔の下端を各列で検出し、直線近似と時系列変位を求める。

    現状は明暗境界が単一で、ROI 内に追跡対象の下端が見える映像向け。
    同じ物理的な箔端を追跡できているかは確認動画で検証する。
    """

    name = 'foil_bottom'

    def __init__(
        self,
        roi: tuple[int, int, int, int] | None = None,
        polarity: Literal['bright', 'dark'] = 'bright',
        gaussian_kernel: int = 5,
        sobel_kernel: int = 3,
        min_gradient: float = 40.,
        column_step: int = 4,
        tracking_window_px: float = 40.,
        min_coverage: float = .60,
        fit_tolerance_px: float = 6.,
        reference_x_px: float | None = None,
        baseline_mode: Literal['first_valid', 'fixed', 'mean_n'] = 'first_valid',
        baseline_y_px: float | None = None,
        baseline_frames: int = 10,
        save_contour_points: bool = False,
    ):
        if polarity not in ('bright', 'dark'):
            raise ValueError('polarity は bright または dark')
        if gaussian_kernel < 1 or gaussian_kernel % 2 != 1 or gaussian_kernel > 31:
            raise ValueError('gaussian_kernel は 1～31 の奇数')
        if sobel_kernel not in (1, 3, 5, 7):
            raise ValueError('sobel_kernel は 1, 3, 5, 7')
        if min_gradient <= 0 or column_step < 1 or tracking_window_px < 0:
            raise ValueError('勾配・列間隔・追跡範囲の設定が不正です')
        if not 0 < min_coverage <= 1 or fit_tolerance_px < .1:
            raise ValueError('有効列率または直線フィット許容値が不正です')
        if baseline_mode not in ('first_valid', 'fixed', 'mean_n'):
            raise ValueError('baseline_mode が不正です')
        if baseline_mode == 'fixed' and baseline_y_px is None:
            raise ValueError('固定基準では baseline_y_px が必要です')
        if baseline_frames < 1:
            raise ValueError('baseline_frames は1以上')
        self.roi = roi
        self.polarity = polarity
        self.gaussian_kernel = int(gaussian_kernel)
        self.sobel_kernel = int(sobel_kernel)
        self.min_gradient = float(min_gradient)
        self.column_step = int(column_step)
        self.tracking_window_px = float(tracking_window_px)
        self.min_coverage = float(min_coverage)
        self.fit_tolerance_px = float(fit_tolerance_px)
        self.reference_x_px = reference_x_px
        self.baseline_mode = baseline_mode
        self.baseline_y_px = baseline_y_px
        self.baseline_frames = int(baseline_frames)
        self.save_contour_points = bool(save_contour_points)
        self.reset()

    def reset(self) -> None:
        """新しい動画を処理する前に時間方向の状態を初期化する。"""
        self._previous_line: tuple[float, float] | None = None
        self._reference_y = float(self.baseline_y_px) if self.baseline_mode == 'fixed' else None
        self._warmup: list[float] = []

    def parameters(self) -> dict:
        """追跡で変化する内部状態を除いた再現用の設定。"""
        return {k: v for k, v in vars(self).items() if not k.startswith('_')}

    def analyze(self, frame: np.ndarray, mm_per_pixel: float | None, frame_index: int) -> FrameResult:
        height, width = frame.shape[:2]
        x0, y0, x1, y1 = self.roi or (0, 0, width, height)
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError('ROI が画像外です')
        if x1-x0 < 15 or y1-y0 < 8:
            raise ValueError('ROI が小さすぎます（幅15px、高さ8px以上）')
        xref = float(self.reference_x_px) if self.reference_x_px is not None else (x0+x1-1)/2
        if not x0 <= xref < x1:
            raise ValueError('reference_x_px は ROI 内を指定してください')

        gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        if self.gaussian_kernel > 1:
            gray = cv2.GaussianBlur(gray, (self.gaussian_kernel, self.gaussian_kernel), 0)
        # bright: 明→暗なので下端勾配は負。dark: 暗→明なので正。
        gradient = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=self.sobel_kernel)
        signed = (-gradient if self.polarity == 'bright' else gradient)
        xs = np.arange(x0+2, x1-2, self.column_step, dtype=np.int32)
        observed_x: list[float] = []
        observed_y: list[float] = []
        strengths: list[float] = []
        for x in xs:
            profile = signed[2:-2, x-x0]
            if len(profile) == 0:
                continue
            indices = np.flatnonzero(profile >= self.min_gradient)
            if not len(indices):
                continue
            if self._previous_line is not None and self.tracking_window_px > 0:
                a, b = self._previous_line
                predicted = a*float(x) + b
                local = indices[np.abs((indices+2+y0)-predicted) <= self.tracking_window_px]
                # 追跡中は近傍に見つからなければ、その列を欠測として扱う。
                if not len(local):
                    continue
                indices = local
                # 最も近い候補を使い、同程度なら勾配の強い方を選ぶ。
                cost = abs((indices+2+y0)-predicted) - .03*profile[indices]
                idx = int(indices[int(np.argmin(cost))])
            else:
                idx = int(indices[np.argmax(profile[indices])])
            if idx <= 0 or idx >= len(profile)-1:
                offset = 0.
            else:
                before, peak, after = map(float, profile[idx-1:idx+2])
                denom = before - 2*peak + after
                offset = float(np.clip(.5*(before-after)/denom, -1, 1)) if abs(denom)>1e-8 else 0.
            observed_x.append(float(x))
            observed_y.append(float(idx+2+y0+offset))
            strengths.append(float(profile[idx]))
        overlay = frame.copy()
        cv2.rectangle(overlay, (x0,y0), (x1-1,y1-1), (0, 210, 225), 1)
        cv2.line(overlay, (round(xref), y0), (round(xref), y1-1), (180,140,60), 1)

        ratio = len(observed_x) / max(1, len(xs))
        data: dict = {'frame':int(frame_index), 'valid':False,
                      'detected_columns':len(observed_x), 'total_columns':len(xs),
                      'coverage':round(ratio,4), 'reference_x_px':xref,
                      'baseline_mode':self.baseline_mode, 'baseline_ready':False}
        missing = ('edge_y_px', 'edge_y_mm', 'baseline_y_px', 'shift_px', 'shift_mm',
                   'angle_deg', 'straightness_rms_px', 'straightness_rms_mm',
                   'peak_to_peak_px', 'peak_to_peak_mm', 'fit_inliers', 'fit_inlier_fraction')
        data.update({key:None for key in missing})
        if len(observed_x) < 5 or ratio < self.min_coverage:
            cv2.putText(overlay, 'BOTTOM EDGE NOT FOUND', (max(x0,5),max(y0+24,24)),
                        cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,255),1)
            return FrameResult(data, overlay)

        xx = np.asarray(observed_x, dtype=np.float64)
        yy = np.asarray(observed_y, dtype=np.float64)
        # 最小二乗→残差に基づく外れ値除外。うねりは残差として保存する。
        inliers = np.ones(len(xx), dtype=bool)
        for _ in range(4):
            if inliers.sum() < 5:
                break
            a, b = np.polyfit(xx[inliers]-xref, yy[inliers], 1)
            deviation = yy - (a*(xx-xref)+b)
            med = np.median(deviation[inliers])
            mad = np.median(np.abs(deviation[inliers]-med))
            limit = max(self.fit_tolerance_px, 3.0*1.4826*mad)
            candidate = np.abs(deviation-med) <= limit
            if np.array_equal(candidate,inliers):
                break
            inliers = candidate
        if inliers.sum() < 5 or inliers.sum()/max(1,len(xs)) < self.min_coverage:
            return FrameResult(data, overlay)
        a, b = np.polyfit(xx[inliers]-xref, yy[inliers], 1)
        fit = a*(xx-xref)+b
        residuals = yy-fit
        rms = float(np.sqrt(np.mean(np.square(residuals[inliers]))))
        p2p = float(np.ptp(residuals[inliers]))
        yref = float(b)
        self._previous_line = (float(a), float(b-a*xref))

        if self._reference_y is None:
            if self.baseline_mode == 'first_valid':
                self._reference_y = yref
            elif self.baseline_mode == 'mean_n':
                self._warmup.append(yref)
                if len(self._warmup) >= self.baseline_frames:
                    self._reference_y = float(np.mean(self._warmup))
        baseline = self._reference_y
        shift = yref-baseline if baseline is not None else None
        angle = math.degrees(math.atan(float(a)))
        factor = mm_per_pixel
        data.update(valid=True, baseline_ready=baseline is not None,
                    edge_y_px=yref, edge_y_mm=yref*factor if factor is not None else None,
                    baseline_y_px=baseline, shift_px=shift,
                    shift_mm=shift*factor if shift is not None and factor is not None else None,
                    angle_deg=angle, straightness_rms_px=rms,
                    straightness_rms_mm=rms*factor if factor is not None else None,
                    peak_to_peak_px=p2p,
                    peak_to_peak_mm=p2p*factor if factor is not None else None,
                    fit_inliers=int(inliers.sum()), fit_inlier_fraction=float(inliers.mean()))

        points = np.rint(np.column_stack([xx[inliers],yy[inliers]])).astype(np.int32)
        for x, y in points:
            cv2.circle(overlay, (int(x),int(y)), 1, (255,120,0), -1)
        yl = int(round(a*(x0-xref)+b))
        yr = int(round(a*(x1-1-xref)+b))
        cv2.line(overlay,(x0,yl),(x1-1,yr),(0,185,255),2,cv2.LINE_AA)
        cv2.circle(overlay,(round(xref),round(yref)),5,(0,255,0),-1)
        if baseline is not None:
            cv2.line(overlay,(x0,round(baseline)),(x1-1,round(baseline)),(0,255,255),1)
        label = (f'dY={shift*factor:+.3f} mm' if shift is not None and factor is not None else
                 f'dY={shift:+.2f} px' if shift is not None else 'baseline initializing')
        cv2.putText(overlay,label,(max(5,x0+5),max(24,y0+22)),
                    cv2.FONT_HERSHEY_SIMPLEX,.55,(0,220,0),2)

        details = None
        if self.save_contour_points:
            details = [{'frame':int(frame_index),'x_px':float(x), 'y_px':float(y),
                        'fit_y_px':float(f), 'residual_px':float(res),
                        'gradient':float(grad), 'inlier':bool(ok)}
                       for x,y,f,res,grad,ok in zip(xx,yy,fit,residuals,strengths,inliers)]
        return FrameResult(data,overlay,details=details)
