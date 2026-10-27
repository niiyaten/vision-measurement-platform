"""Synthetic foil edge tests: known shifts, line slope, missing detections, video outputs."""
from __future__ import annotations
import csv
from pathlib import Path

import cv2
import numpy as np
import pytest
from typer.testing import CliRunner

from vision_measurement.analysis import create_analyzer
from vision_measurement.processing import MeasurementEngine, ProcessOptions
from vision_measurement.cli import app


def make_foil(dy=0, slope=0.04, dark=False, missing=False, highlight=False):
    h,w=240,320
    background=205 if dark else 35
    foreground=36 if dark else 210
    image=np.full((h,w,3),background,np.uint8)
    if not missing:
        xs=np.arange(40,281)
        bottom=np.rint(135+dy+slope*(xs-160)+1.3*np.sin((xs-40)/15)).astype(int)
        points=np.vstack([[[40,15],[280,15]], np.column_stack((xs[::-1],bottom[::-1]))]).astype(np.int32)
        cv2.fillPoly(image,[points],(foreground,)*3)
    if highlight:
        # 局所的なノイズと左の無関係な強い線
        cv2.rectangle(image,(6,20),(21,205),(250,250,250),-1)
        cv2.rectangle(image,(115,79),(155,83),(235,235,235),-1)
    return image


def analyzer(**opts):
    return create_analyzer('foil_bottom',roi=(35,90,285,195), min_coverage=.6, **opts)


def test_bottom_shift_and_shape_with_inlier_points():
    a=analyzer(save_contour_points=True)
    rows=[a.analyze(make_foil(dy=d),.25,i) for i,d in enumerate((0,6,12,-4))]
    assert all(r.values['valid'] for r in rows)
    assert abs(rows[0].values['edge_y_px']-135)<2.0
    assert [r.values['shift_mm'] for r in rows[1:]]==pytest.approx([1.5,3,-1],abs=.30)
    assert rows[1].values['angle_deg']==pytest.approx(np.degrees(np.arctan(.04)),abs=.5)
    assert rows[1].values['straightness_rms_px']>0.3
    assert rows[1].values['peak_to_peak_px']>1
    assert len(rows[1].details)>30
    assert {'x_px','y_px','residual_px','inlier'} <= rows[1].details[0].keys()


def test_dark_foil_and_no_scale():
    output=analyzer(polarity='dark').analyze(make_foil(dark=True),None,0).values
    assert output['valid'] is True
    assert output['shift_px']==0
    assert output['shift_mm'] is None
    assert output['edge_y_mm'] is None


def test_empty_and_roi_error():
    r=analyzer().analyze(make_foil(missing=True),.25,0)
    assert not r.values['valid']
    assert r.values['shift_mm'] is None
    with pytest.raises(ValueError,match='ROI'):
        create_analyzer('foil_bottom',roi=(0,0,350,200)).analyze(make_foil(),.25,0)


def test_manual_baseline_and_mean_n():
    manual=analyzer(baseline_mode='fixed',baseline_y_px=130)
    v=manual.analyze(make_foil(dy=5),.25,0).values
    assert v['shift_mm']==pytest.approx((v['edge_y_px']-130)*.25)
    mean=analyzer(baseline_mode='mean_n',baseline_frames=3)
    values=[mean.analyze(make_foil(dy=d),.25,i).values for i,d in enumerate((0,4,8,12))]
    assert values[0]['shift_mm'] is None
    assert values[1]['shift_mm'] is None
    assert values[2]['baseline_ready']
    assert values[3]['shift_mm']==pytest.approx(2.,abs=.3)


def test_bad_parameters_and_tracking():
    with pytest.raises(ValueError):analyzer(gaussian_kernel=4)
    with pytest.raises(ValueError):analyzer(baseline_mode='fixed')
    a=analyzer(tracking_window_px=25, save_contour_points=True)
    initial=a.analyze(make_foil(highlight=True),.25,0)
    second=a.analyze(make_foil(dy=8,highlight=True),.25,1)
    assert initial.values['valid'] and second.values['valid']
    assert second.values['shift_mm']==pytest.approx(2,abs=.5)


def test_video_csv_manifest_and_preview(tmp_path):
    video=tmp_path/'bottom.mp4'
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),25,(320,240))
    assert writer.isOpened()
    for dy in (0,2,4,6,8,6,4,2):writer.write(make_foil(dy=dy))
    writer.release()
    instance=analyzer(save_contour_points=True)
    engine=MeasurementEngine(analyzer=instance,options=ProcessOptions(True,True,'mp4',1,.25))
    result=engine.process_video(video,tmp_path/'result')
    target=tmp_path/'result'
    for filename in ('measurements.csv','contour_points.csv','corrected.mp4','overlay.mp4','manifest.json'):
        assert (target/filename).exists(),filename
    with (target/'measurements.csv').open(encoding='utf-8-sig') as f:
        rows=list(csv.DictReader(f))
    assert len(rows)==8
    assert float(rows[4]['shift_mm'])==pytest.approx(2,abs=.6)
    assert result['analyzer']=='foil_bottom'
    assert 'save_contour_points' in result['analyzer_parameters']
    assert not any(key.startswith('_') for key in result['analyzer_parameters'])
    # Reprocessing with the same engine must not reuse a stale first-frame baseline.
    repeat=engine.process_video(video,tmp_path/'repeat')
    assert repeat['metadata']['frames_processed']==8
    with (tmp_path/'repeat'/'measurements.csv').open(encoding='utf-8-sig') as f:
        assert float(list(csv.DictReader(f))[0]['shift_mm'])==0


def test_cli_bottom_mode(tmp_path):
    image=tmp_path/'foil.png'
    cv2.imwrite(str(image),make_foil())
    runner=CliRunner()
    result=runner.invoke(app,['process',str(image),'--analysis','foil_bottom',
                              '--scale-mm-per-pixel','0.25','--roi','35,90,285,195',
                              '--bottom-min-gradient','25','--output-dir',str(tmp_path/'cli')])
    assert result.exit_code == 0, result.output
    assert (tmp_path/'cli'/'measurements.csv').is_file()
