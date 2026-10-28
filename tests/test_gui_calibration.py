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


def test_busy_blob_scene_skips_expensive_search(monkeypatch):
    """High-candidate scenes should not call costly grid clustering."""
    from unittest.mock import Mock
    import numpy as np
    import vision_measurement.calibration as calibration
    monkeypatch.setattr(calibration, '_detector', lambda *args: Mock(detect=lambda image: [None] * 999))
    called = Mock(side_effect=AssertionError('Expensive grid matching should be skipped'))
    monkeypatch.setattr(calibration.cv2, 'findCirclesGrid', called)
    image = np.zeros((320, 420, 3), dtype=np.uint8)
    assert calibration.detect_grid(image, (14, 10), skip_busy_trials=True) is None
    called.assert_not_called()


def test_calibration_progress_has_before_and_after_notifications():
    video = Path(__file__).parent / 'fixtures' / 'lens_grid.mp4'
    events = []
    calibrate_lens(video, step=1, max_checked=30, min_change=.001, progress=events.append)
    scanned = [event for event in events if event['stage'] == 'scanning']
    inspected = [event for event in events if event['stage'] == 'inspection' and event['inspected'] > 0]
    assert len(scanned) == len(inspected) == 30
    assert all(event['last_detection_s'] is not None and event['last_detection_s'] >= 0 for event in inspected)
