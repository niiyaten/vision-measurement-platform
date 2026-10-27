from pathlib import Path
import numpy as np
import cv2
import pytest
from vision_measurement.io import load_profile,dump_json
from vision_measurement.calibration import calibrate_lens,calibrate_plane_grid,calibrate_plane_points,detect_grid
from vision_measurement.processing import MeasurementEngine,ProcessOptions
from vision_measurement.analysis import FoilShiftAnalyzer

FIX=Path(__file__).parent/'fixtures'

def test_grid_detection():
    cap=cv2.VideoCapture(str(FIX/'plane_grid.mp4'))
    ok,img=cap.read();cap.release()
    assert ok and detect_grid(img,(14,10)) is not None

def test_lens_calibration():
    result=calibrate_lens(FIX/'lens_grid.mp4',(14,10),14.,step=1,max_checked=30,min_change=0.001)
    assert result['rms_reprojection_px']<1.3
    assert len(result['frames_used'])>=5
    assert result['source_size_px']==[640,480]

def test_plane_and_output(tmp_path):
    plane=calibrate_plane_grid(FIX/'plane_grid.mp4',(14,10),14.,step=2)
    assert plane['fit_rms_px']<2
    assert plane['frames_assumed_stationary']>2
    assert plane['holdout_rms_px'] is not None
    dump_json(tmp_path/'plane.json',plane)
    assert 'pixels_per_mm' in load_profile(tmp_path/'plane.json','plane')
    engine=MeasurementEngine(plane=plane,options=ProcessOptions(True,False,'avi'))
    output=engine.process_video(FIX/'plane_grid.mp4',tmp_path/'processed')
    assert (tmp_path/'processed'/'corrected.avi').exists()
    assert output['metadata']['frames_processed']==30

def test_foil_shift_and_trace(tmp_path):
    analyzer=FoilShiftAnalyzer(min_separation_px=50)
    engine=MeasurementEngine(analyzer=analyzer,options=ProcessOptions(True,True,'avi',1,.25))
    output=engine.process_video(FIX/'foil_shift.mp4',tmp_path/'foil')
    assert (tmp_path/'foil'/'measurements.csv').exists()
    assert (tmp_path/'foil'/'overlay.avi').exists()
    assert (tmp_path/'foil'/'manifest.json').exists()
    import csv
    with (tmp_path/'foil'/'measurements.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
    assert len(rows)==60 and all(r['valid']=='True' for r in rows)
    shifts=[float(r['shift_mm']) for r in rows]
    assert max(shifts)>4 and min(shifts)<-4
    assert output['input_sha256']

def test_manual_points_exact():
    src=np.array([[10,10],[110,10],[110,60],[10,60]],np.float64)
    dst=np.array([[0,0],[100,0],[100,50],[0,50]],np.float64)
    result=calibrate_plane_points(src,dst,(200,100),pixels_per_mm=2.)
    assert result['fit_rms_px']<1e-6
    assert result['output_size_px']==[240,140]


def test_incompatible_plane_rejected():
    lens={'camera_matrix':np.eye(3).tolist(),'distortion_coefficients':[0]*5}
    plane={'requires_lens_correction':True,'camera_matrix':(np.eye(3)*2).tolist(),
           'distortion_coefficients':[0]*5,'output_size_px':[100,100]}
    with pytest.raises(ValueError,match='一致しません'):
        MeasurementEngine(lens=lens,plane=plane)
