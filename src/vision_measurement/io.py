"""画像、校正ファイル、実行履歴の読み書き。"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import zipfile
import cv2
import numpy as np


def load_image(path: str | Path) -> np.ndarray:
    """日本語ファイル名を含む画像をBGRで読む。"""
    raw = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"画像を開けません: {path}")
    return image


def save_image(path: str | Path, frame: np.ndarray) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower()
    ok, buffer = cv2.imencode(ext, frame)
    if not ok:
        raise ValueError(f"画像保存形式を確認してください: {ext}")
    buffer.tofile(str(path))


def load_profile(path: str | Path, kind: str | None = None) -> dict:
    """JSONまたは旧校正ZIPを読む。新旧の主要フィールドを維持。"""
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as z:
            candidates = [n for n in z.namelist() if Path(n).name in
                          ('calibration.json', 'plane_transform.json', 'profile.json')]
            if kind == 'lens':
                candidates.sort(key=lambda x: Path(x).name != 'calibration.json')
            if kind == 'plane':
                candidates.sort(key=lambda x: Path(x).name != 'plane_transform.json')
            if not candidates:
                raise ValueError('ZIPに校正JSONが見つかりません')
            data = json.loads(z.read(candidates[0]).decode('utf-8-sig'))
    elif path.suffix.lower() == '.json':
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    elif path.suffix.lower() == '.csv':
        import csv
        with path.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        vals = {str(r.get('parameter', '')).strip(): float(r['value']) for r in rows}
        needed = ('fx_px', 'fy_px', 'cx_px', 'cy_px', 'k1', 'k2', 'p1', 'p2', 'k3')
        if not all(k in vals for k in needed):
            raise ValueError('CSVにカメラパラメータがありません')
        # 旧CSVには画像解像度がないため、利用前に size を指定する。
        data = {'camera_matrix': [[vals['fx_px'], 0, vals['cx_px']],
                                  [0, vals['fy_px'], vals['cy_px']], [0, 0, 1]],
                'distortion_coefficients': [vals[k] for k in ('k1', 'k2', 'p1', 'p2', 'k3')]}
    else:
        raise ValueError('校正ファイルは JSON / CSV / ZIP を指定してください')
    return data


def dump_json(path: str | Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def sha256(path: str | Path) -> str:
    sha = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def read_frames(path: str | Path, step: int = 1, max_checked: int = 300):
    if step < 1 or max_checked < 1:
        raise ValueError('step/max_checkedは1以上にしてください')
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f'動画を開けません: {path}')
    try:
        index, checked = 0, 0
        while checked < max_checked:
            ok, frame = cap.read()
            if not ok:
                break
            if index % step == 0:
                yield index, frame
                checked += 1
            index += 1
    finally:
        cap.release()
