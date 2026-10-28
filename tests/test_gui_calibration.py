"""Regression tests for clipboard paths, filenames, and real calibration progress."""
from pathlib import Path

import pytest

from vision_measurement.gui_utils import normalize_user_path, default_calibration_name
from vision_measurement.calibration import calibrate_lens


@pytest.mark.parametrize(('raw', 'expected'), [
    (r'"D:\Users\data\lens shot.avi"', r'D:\Users\data\lens shot.avi'),
    (r' D:\撮影\lens.avi ', r'D:\撮影\lens.avi'),
    ('“D:\\Data\\sample.avi”', 'D:\\Data\\sample.avi'),
    ("'/tmp/camera data.avi'", '/tmp/camera data.avi'),
    ('', ''),
])
def test_clipboard_path_quotes(raw, expected):
    assert normalize_user_path(raw) == expected


def test_calibration_name_uses_video_stem():
    assert default_calibration_name(r'"D:\Data\レンズ.avi"') == 'レンズ_calibParm'
    assert default_calibration_name('/data/shot.v1.avi') == 'shot.v1_calibParm'
    assert default_calibration_name('"D:\\Data\\plane.avi"', lens=False) == 'plane_planeParm'
    assert default_calibration_name('') == 'lens_calibParm'


def test_real_calibration_progress_follows_inspected_frames():
    video = Path(__file__).parent / 'fixtures' / 'lens_grid.mp4'
    events = []
    profile = calibrate_lens(video, step=1, max_checked=30, min_change=.001,
                             progress=events.append)
    assert profile['frames_checked'] == 30
    assert events[0]['stage'] == 'inspection' and events[0]['inspected'] == 0
    assert [e['inspected'] for e in events if e['stage'] == 'inspection'] == list(range(31))
    assert events[-2]['stage'] == 'fitting'
    assert events[-1]['stage'] == 'done'
    assert events[-1]['used'] == len(profile['frames_used'])
    assert events[-1]['total'] == 30
    assert profile['rms_reprojection_px'] < 1.3


def test_progress_works_when_insufficient_frames():
    video = Path(__file__).parent / 'fixtures' / 'lens_grid.mp4'
    events = []
    with pytest.raises(ValueError, match='画像が不足'):
        calibrate_lens(video, max_checked=3, progress=events.append)
    assert events[-1]['stage'] == 'inspection'
    assert events[-1]['inspected'] == 3
