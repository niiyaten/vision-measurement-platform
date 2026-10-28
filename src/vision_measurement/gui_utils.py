"""Small pure helpers for GUI input; usable without starting Streamlit."""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
import re


def normalize_user_path(text: str) -> str:
    """Accept a pasted Explorer 'Copy as path' string, with optional outer quotes."""
    value = str(text).strip()
    pairs = {'"': '"', "'": "'", '“': '”', '「': '」', '‘': '’'}
    while len(value) >= 2 and value[0] in pairs and value[-1] == pairs[value[0]]:
        value = value[1:-1].strip()
    return value


def default_calibration_name(source: str, lens: bool = True) -> str:
    """Build a safe filename from a Windows or POSIX input path."""
    source = normalize_user_path(source)
    if not source:
        return 'lens_calibParm' if lens else 'plane_calibParm'
    # PureWindowsPath handles both backslashes and forward slashes on any host OS.
    stem = PureWindowsPath(source).stem or Path(source).stem
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', stem).strip(' .')
    return f'{stem or "calibration"}_calibParm' if lens else f'{stem or "calibration"}_planeParm'
