"""共通の円グリッド検出、レンズと平面の校正。"""
from __future__ import annotations
from pathlib import Path
from collections.abc import Callable
from time import perf_counter
import cv2
import numpy as np
from .io import load_image, read_frames


def grid_object_points(pattern: tuple[int, int], pitch_mm: float) -> np.ndarray:
    cols, rows = pattern
    if cols < 3 or rows < 3 or pitch_mm <= 0:
        raise ValueError('円グリッドの個数と中心間距離を確認してください')
    return (np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * pitch_mm).astype(np.float32)


def _detector(min_area: float = 15., max_area: float = 80000.) -> cv2.SimpleBlobDetector:
    p = cv2.SimpleBlobDetector_Params()
    p.filterByArea = True
    if not (0 < min_area < max_area):
        raise ValueError("ブロブ面積の最小値・最大値を確認してください")
    p.minArea = float(min_area)
    p.maxArea = float(max_area)
    p.filterByCircularity = False
    p.filterByConvexity = False
    p.filterByInertia = False
    p.filterByColor = True
    p.blobColor = 0
    return cv2.SimpleBlobDetector_create(p)


def detect_grid(frame: np.ndarray, pattern: tuple[int, int] = (14, 10),
                fill_holes: bool = True, fill_kernel: int = 9,
                blob_min_area: float = 15., blob_max_area: float = 80000.,
                skip_busy_trials: bool = True) -> np.ndarray | None:
    """Detect symmetric circles; skip images with excessive blob candidates.

    On cluttered CLAHE frames, OpenCV's grid search may take many seconds.
    Count blobs before grid matching to avoid expensive impossible trials.
    Disable this heuristic only for unusually cluttered calibration boards.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    clahe = cv2.createCLAHE(clipLimit=2., tileGridSize=(8, 8)).apply(gray)
    trials = [gray]
    if fill_holes:
        k = max(3, int(fill_kernel) | 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        trials.append(cv2.morphologyEx(clahe, cv2.MORPH_CLOSE, kernel))
    trials.append(clahe)
    detector = _detector(blob_min_area, blob_max_area)
    expected = int(pattern[0] * pattern[1])
    max_candidates = max(500, expected * 4)
    for image in trials:
        if skip_busy_trials:
            n = len(detector.detect(image))
            if n < expected or n > max_candidates:
                continue
        for flags in (cv2.CALIB_CB_SYMMETRIC_GRID,
                      cv2.CALIB_CB_SYMMETRIC_GRID | cv2.CALIB_CB_CLUSTERING):
            ok, points = cv2.findCirclesGrid(image, pattern, flags=flags, blobDetector=detector)
            if ok:
                return points.reshape(-1, 2).astype(np.float32)
    return None


def _diversity(points: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    w, h = size
    center = points.mean(axis=0) / (w, h)
    extent = (points.max(axis=0) - points.min(axis=0)) / (w, h)
    horizontal = points[-1] - points[0]
    return np.r_[center, extent, np.arctan2(horizontal[1], horizontal[0]) / np.pi]


def _estimated_video_samples(video: str | Path, step: int, limit: int) -> int | None:
    """Estimate selected frames for an honest progress percentage (None if unknown)."""
    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():
            return None
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        return min(limit, (n + step - 1) // step) if n > 0 else None
    finally:
        cap.release()


def calibrate_lens(video: str | Path, pattern=(14, 10), pitch_mm=14., step=10,
                   max_checked=300, max_used=35, min_change=0.025,
                   fill_holes=True, fill_kernel=9,
                   blob_min_area=15., blob_max_area=80000.,
                   skip_busy_trials=True, progress: Callable[[dict], None] | None = None) -> dict:
    """Calibrate intrinsic parameters, emitting per-inspected-frame progress events.

    Progress event: stage (inspection/fitting/done), inspected, detected, used,
    total (None if unavailable). Callback never mutates processing decisions.
    """
    if step < 1 or max_checked < 1 or max_used < 5 or min_change < 0:
        raise ValueError('検査間隔・枚数・姿勢差を確認してください（採用上限は5枚以上）')
    obj2d = grid_object_points(pattern, pitch_mm)
    obj3d = np.column_stack([obj2d, np.zeros(len(obj2d))]).astype(np.float32)
    objects, images, frames, size, last = [], [], [], None, None
    inspected = detected = 0
    duration = None
    total = _estimated_video_samples(video, step, max_checked) if progress else None

    def notify(stage: str, frame: int | None = None):
        if progress is not None:
            progress({'stage': stage, 'inspected': inspected, 'detected': detected,
                      'used': len(images), 'total': total, 'frame': frame,
                      'last_detection_s': duration})

    notify('inspection')
    for idx, frame in read_frames(video, step, max_checked):
        inspected += 1
        size = (frame.shape[1], frame.shape[0])
        notify('scanning', idx)
        detection_start = perf_counter()
        pts = detect_grid(frame, pattern, fill_holes, fill_kernel, blob_min_area, blob_max_area,
                          skip_busy_trials=skip_busy_trials)
        duration = perf_counter() - detection_start
        if pts is not None:
            detected += 1
            desc = _diversity(pts, size)
            if last is None or np.linalg.norm(desc - last) >= min_change:
                objects.append(obj3d.copy())
                images.append(pts.reshape(-1, 1, 2))
                frames.append(idx)
                last = desc
        notify('inspection', idx)
        if len(images) >= max_used:
            break
    if len(images) < 5:
        raise ValueError(f'校正に必要な画像が不足（検査{inspected}、検出{detected}、採用{len(images)}）。')
    notify('fitting')
    rms, k, d, rvecs, tvecs = cv2.calibrateCamera(objects, images, size, None, None)
    per_frame = []
    for idx, obj, img, r, t in zip(frames, objects, images, rvecs, tvecs):
        pred, _ = cv2.projectPoints(obj, r, t, k, d)
        err = float(np.sqrt(np.mean(np.sum((pred - img).reshape(-1, 2)**2, axis=1))))
        per_frame.append({'frame': idx, 'rms_px': err})
    notify('done')
    return {'schema_version': 3, 'type': 'lens', 'source_size_px': list(size),
            'camera_matrix': k.tolist(), 'distortion_coefficients': d.ravel().tolist(),
            'rms_reprojection_px': float(rms), 'frames_checked': inspected,
            'frames_detected': detected, 'frames_used': frames, 'frame_errors': per_frame,
            'pattern': list(pattern), 'pitch_mm': pitch_mm}


def _undistort_points(pts: np.ndarray, lens: dict | None) -> np.ndarray:
    if lens is None:
        return pts.reshape(-1, 2).astype(np.float64)
    k, d = lens_matrices(lens)
    return cv2.undistortPoints(np.asarray(pts, np.float64).reshape(-1, 1, 2), k, d, P=k).reshape(-1, 2)


def lens_matrices(profile: dict):
    return np.asarray(profile['camera_matrix'], np.float64), np.asarray(profile['distortion_coefficients'], np.float64)


def _homography(src: np.ndarray, world: np.ndarray, ppm: float, margin_mm: float):
    if len(src) < 4 or src.shape != world.shape:
        raise ValueError('既知座標が対応する4点以上を指定してください')
    lo = world.min(axis=0)
    hi = world.max(axis=0)
    targets = (world - lo + margin_mm) * ppm
    h, _ = cv2.findHomography(src, targets, method=0)
    if h is None:
        raise ValueError('射影行列を求められません')
    wh = np.ceil((hi - lo + 2*margin_mm) * ppm).astype(int)
    if np.any(wh < 2) or np.any(wh > 10000) or np.prod(wh) > 40_000_000:
        raise ValueError('出力画像サイズが不正です')
    fit = cv2.perspectiveTransform(src.reshape(-1, 1, 2).astype(np.float64), h).reshape(-1, 2)
    err = np.linalg.norm(fit - targets, axis=1)
    return h, (int(wh[0]), int(wh[1])), float(np.sqrt(np.mean(err**2))), float(np.max(err))


def calibrate_plane_points(image_points: np.ndarray, world_points_mm: np.ndarray,
                           image_size: tuple[int, int], lens: dict | None = None,
                           pixels_per_mm: float = 2., margin_mm: float = 10., mode='manual_points') -> dict:
    src = _undistort_points(np.asarray(image_points), lens)
    world = np.asarray(world_points_mm, dtype=np.float64).reshape(-1, 2)
    if pixels_per_mm <= 0:
        raise ValueError('pixels_per_mm は正の値が必要です')
    h, output, rms, mx = _homography(src, world, pixels_per_mm, margin_mm)
    result = {'schema_version': 3, 'type': 'plane', 'mode': mode,
              'source_size_px': list(image_size), 'output_size_px': list(output),
              'homography_undistorted_to_plane': h.tolist(),
              'pixels_per_mm': float(pixels_per_mm), 'margin_mm': margin_mm,
              'fit_rms_px': rms, 'fit_rms_mm': rms/pixels_per_mm,
              'fit_max_px': mx, 'fitted_points': len(src),
              'requires_lens_correction': lens is not None}
    if lens is not None:
        result['camera_matrix'] = lens['camera_matrix']
        result['distortion_coefficients'] = lens['distortion_coefficients']
    return result


def calibrate_plane_grid(path: str | Path, pattern=(14, 10), pitch_mm=14.,
                         lens: dict | None = None, step=15, max_checked=120,
                         max_stationary_motion_px=2.5, fill_holes=True, fill_kernel=9,
                         pixels_per_mm: float | None = None, margin_mm=14.) -> dict:
    path = Path(path)
    if path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff'}:
        samples = [(0, load_image(path))]
    else:
        samples = list(read_frames(path, step, max_checked))
    valid = []
    size = None
    for i, frame in samples:
        size = frame.shape[1], frame.shape[0]
        pts = detect_grid(frame, pattern, fill_holes, fill_kernel)
        if pts is not None:
            valid.append((i, _undistort_points(pts, lens)))
    if not valid:
        raise ValueError('全点の円グリッドを検出できませんでした')
    # 動画は同じ平面・同じ姿勢の点群だけ集約する。動体を平均するとHが壊れる。
    first = valid[0][1]
    retained = [(i, p) for i, p in valid if np.median(np.linalg.norm(p-first, axis=1)) <= max_stationary_motion_px]
    if len(retained) == 0:
        raise ValueError('静止したボードのフレームがありません')
    # 対称格子は向きが逆転して検出される場合があるため、対応順序が揃っているものだけ用いる。
    pts = np.median(np.stack([p for _, p in retained]), axis=0)
    world = grid_object_points(pattern, pitch_mm).astype(np.float64)
    if pixels_per_mm is None:
        grid = pts.reshape(pattern[1], pattern[0], 2)
        spacing = np.r_[np.linalg.norm(np.diff(grid, axis=0), axis=2).ravel(),
                        np.linalg.norm(np.diff(grid, axis=1), axis=2).ravel()]
        pixels_per_mm = float(np.median(spacing)/pitch_mm)
    # already undistorted points: avoid applying lens again
    result = calibrate_plane_points(pts, world, size, None, pixels_per_mm, margin_mm, 'grid_video' if len(samples)>1 else 'grid_image')
    result['requires_lens_correction'] = lens is not None
    if lens is not None:
        result['camera_matrix'] = lens['camera_matrix']
        result['distortion_coefficients'] = lens['distortion_coefficients']
    result['pattern'] = list(pattern); result['pitch_mm'] = pitch_mm
    result['frames_checked'] = len(samples); result['frames_detected'] = len(valid)
    result['frames_assumed_stationary'] = len(retained)
    result['max_motion_px'] = float(max(np.median(np.linalg.norm(p-first, axis=1)) for _,p in valid))
    holdout = retained[::2]; train = retained[1::2]
    if len(train) >= 1 and len(holdout) >= 1:
        train_pts = np.median(np.stack([p for _, p in train]), axis=0)
        hh, _, _, _ = _homography(train_pts, world, pixels_per_mm, margin_mm)
        goal = (world - world.min(axis=0) + margin_mm)*pixels_per_mm
        errors = [np.linalg.norm(cv2.perspectiveTransform(p.reshape(-1,1,2), hh).reshape(-1,2)-goal, axis=1) for _,p in holdout]
        result['holdout_rms_px'] = float(np.sqrt(np.mean(np.square(np.concatenate(errors)))))
        result['holdout_rms_mm'] = result['holdout_rms_px']/pixels_per_mm
    else:
        result['holdout_rms_px'] = None
        result['holdout_rms_mm'] = None
    return result


def calibrate_plane_rectangle(image_points: np.ndarray, width_mm: float, height_mm: float,
                              image_size: tuple[int, int], lens: dict | None = None,
                              pixels_per_mm: float | None = None) -> dict:
    """Four clicked corners (TL, TR, BR, BL) and measured dimensions -> plane H.

    Pixel scale is estimated from the clicked side lengths if not supplied.
    This makes a rectified *image*, not an independent accuracy guarantee.
    """
    corners = np.asarray(image_points, dtype=np.float64)
    if corners.shape != (4, 2) or not np.isfinite(corners).all():
        raise ValueError('4隅の画像座標を左上→右上→右下→左下の順で指定してください')
    if not (np.isfinite(width_mm) and np.isfinite(height_mm) and width_mm > 0 and height_mm > 0):
        raise ValueError('実寸幅・高さは正の値を指定してください')
    # For a convex quadrilateral, all signed turns must have the same sign.
    segments = np.roll(corners, -1, axis=0) - corners
    # NumPy 2.5 removed support for 2-D vectors in np.cross().
    # The scalar 2-D determinant gives the signed turn at each corner.
    next_segments = np.roll(segments, -1, axis=0)
    turns = segments[:, 0] * next_segments[:, 1] - segments[:, 1] * next_segments[:, 0]
    if not (np.all(turns > 1e-5) or np.all(turns < -1e-5)):
        raise ValueError('クリックした4点が凸四角形になっていません。順序を確認してください')
    src = _undistort_points(corners, lens)
    automatic_scale = pixels_per_mm is None
    if automatic_scale:
        edges = np.linalg.norm(src - np.roll(src, -1, axis=0), axis=1)
        pixels_per_mm = float(np.median(edges / [width_mm, height_mm, width_mm, height_mm]))
    if not np.isfinite(pixels_per_mm) or pixels_per_mm <= 0:
        raise ValueError('出力の画素密度を求められません')
    world = np.asarray([(0, 0), (width_mm, 0), (width_mm, height_mm), (0, height_mm)],
                       dtype=np.float64)
    result = calibrate_plane_points(corners, world, image_size, lens, pixels_per_mm,
                                    margin_mm=0, mode='clicked_rectangle')
    result['rectangle_size_mm'] = [float(width_mm), float(height_mm)]
    result['clicked_points_px'] = corners.tolist()
    result['pixels_per_mm_source'] = ('automatically_estimated' if automatic_scale else 'manual')
    # Keep the last transformed corner and ensure video-safe even dimensions.
    def even_ceil(value: float) -> int:
        import math
        last_pixel=int(math.ceil(value))+1
        return max(2,last_pixel+(last_pixel%2))
    result['output_size_px'] = [even_ceil(width_mm*pixels_per_mm),
                                even_ceil(height_mm*pixels_per_mm)]
    return result
