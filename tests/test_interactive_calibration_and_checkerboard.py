"""GUI-independent tests for the same functions used by point clicks and ROI."""
from pathlib import Path
import csv
import cv2
import numpy as np
import pytest
from vision_measurement.calibration import calibrate_plane_rectangle
from vision_measurement.checkerboard import detect_cells, measure_cell
from vision_measurement.analysis import CheckerboardAnalyzer
from vision_measurement.processing import MeasurementEngine, ProcessOptions
from vision_measurement.io import save_image


def make_board():
    frame=np.full((500,650,3),170,np.uint8)
    for row in range(5):
        for col in range(7):
            v=40 if (row+col)%2==0 else 235
            x=65+col*70
            y=50+row*70
            cv2.rectangle(frame,(x+3,y+3),(x+67,y+67),(v,v,v),-1)
    return frame


def test_rectangle_geometry_is_in_mm_and_rejects_crossed_points():
    # Known trapezoid, top-left -> top-right -> bottom-right -> bottom-left.
    pts=np.array([[175.,125.],[480.,100.],[510.,348.],[155.,377.]])
    profile=calibrate_plane_rectangle(pts,100.,60.,(640,480))
    assert profile['mode']=='clicked_rectangle'
    assert profile['output_size_px'][0]%2==0
    assert profile['output_size_px'][1]%2==0
    assert profile['fit_rms_px']<1e-3
    h=np.asarray(profile['homography_undistorted_to_plane'])
    proj=cv2.perspectiveTransform(pts.reshape(-1,1,2),h).reshape(-1,2)
    expected=np.array([[0,0],[100,0],[100,60],[0,60]])*profile['pixels_per_mm']
    np.testing.assert_allclose(proj,expected,atol=1e-4)
    with pytest.raises(ValueError,match='凸四角形'):
        calibrate_plane_rectangle(pts[[0,2,1,3]],100.,60.,(640,480))


def test_square_ids_four_edges_mean_and_population_sd():
    frame=make_board()
    cells=detect_cells(frame,min_area=120)
    assert len(cells)==35
    assert sum(c.color=='dark' for c in cells)==18
    assert sum(c.color=='light' for c in cells)==17
    assert [c.id for c in cells]==list(range(1,36))
    for c in cells:
        row=measure_cell(c,15/64.5,0)
        assert all(abs(row[f'{side}_mm']-15)<.3 for side in ('top','right','bottom','left'))
        assert abs(row['mean_mm']-15)<.3
        assert row['std_mm']<.2


def test_checkerboard_roi_and_csv(tmp_path):
    image=tmp_path/'board.png'
    save_image(image,make_board())
    options=ProcessOptions(True,True,'mp4',1,15/64.5)
    analyzer=CheckerboardAnalyzer(roi=(57,42,275,195),min_area=120)
    result=MeasurementEngine(analyzer=analyzer,options=options).process_image(image,tmp_path/'result')
    with (tmp_path/'result'/'measurements.csv').open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    assert 0<len(rows)<35
    assert len({int(r['id']) for r in rows})==len(rows)
    assert all(r['top_mm'] and r['right_mm'] and r['bottom_mm'] and r['left_mm'] for r in rows)
    assert (tmp_path/'result'/'overlay.png').exists()
    assert (tmp_path/'result'/'summary.csv').exists()
    assert result['analyzer']=='checkerboard'
    assert result['analyzer_parameters']['roi']==(57,42,275,195)


def test_checkerboard_pixel_only_without_scale():
    out=CheckerboardAnalyzer().analyze(make_board(),None,0)
    assert out.values['cell_count']==35
    assert out.rows[0]['top_mm'] is None
    assert out.rows[0]['top_px']>0
