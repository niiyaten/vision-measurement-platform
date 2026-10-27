"""補正・計測の単一エンジン。GUI、CLI、APIで処理を共有。"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import csv
from pathlib import Path
import cv2
import numpy as np
from .analysis import Analyzer
from .calibration import lens_matrices
from .io import dump_json, load_image, save_image, sha256
from . import __version__

@dataclass
class ProcessOptions:
    save_corrected: bool = True
    save_overlay: bool = True
    video_format: str = 'mp4'  # mp4:軽量、avi:MJPG
    frame_step: int = 1
    scale_mm_per_pixel: float | None = None

class MeasurementEngine:
    def __init__(self, lens: dict | None = None, plane: dict | None = None,
                 analyzer: Analyzer | None = None, options: ProcessOptions | None = None):
        self.lens=lens;self.plane=plane;self.analyzer=analyzer
        self.options=options or ProcessOptions()
        self._map_cache={}
        if self.plane:
            needs=bool(self.plane.get('requires_lens_correction', 'camera_matrix' in self.plane))
            if needs and self.lens is None:
                raise ValueError('この射影校正はレンズ補正が必要です')
            if needs and self.lens is not None:
                a,b=lens_matrices(self.lens)
                p,q=lens_matrices(self.plane)
                if not (np.allclose(a,p,atol=1e-5) and np.allclose(b,q,atol=1e-7)):
                    raise ValueError('レンズと射影校正のパラメータが一致しません')
            if not self.plane.get('output_size_px'):
                raise ValueError('射影校正に出力解像度がありません')

    def mm_per_pixel(self):
        if self.plane is not None:
            return 1. / float(self.plane['pixels_per_mm'])
        return self.options.scale_mm_per_pixel

    def correct(self, frame: np.ndarray) -> np.ndarray:
        h,w=frame.shape[:2]
        if self.lens is not None:
            size=self.lens.get('source_size_px') or self.lens.get('image_size_px')
            if size is not None and list(size)!=[w,h]:
                raise ValueError(f'レンズ校正解像度{size}と入力動画{[w,h]}が一致しません')
            if (w,h) not in self._map_cache:
                k,d=lens_matrices(self.lens)
                self._map_cache[(w,h)]=cv2.initUndistortRectifyMap(k,d,None,k,(w,h),cv2.CV_32FC1)
            frame=cv2.remap(frame,*self._map_cache[(w,h)],cv2.INTER_LINEAR)
        if self.plane is not None:
            src_size=self.plane.get('source_size_px')
            if src_size is not None and list(src_size)!=[w,h]:
                raise ValueError(f'射影校正解像度{src_size}と入力動画{[w,h]}が一致しません')
            H=np.asarray(self.plane['homography_undistorted_to_plane'],np.float64)
            output=tuple(map(int,self.plane['output_size_px']))
            frame=cv2.warpPerspective(frame,H,output,flags=cv2.INTER_LINEAR)
        return frame

    def process_frame(self,frame:np.ndarray,index:int=0):
        corrected=self.correct(frame)
        result=self.analyzer.analyze(corrected,self.mm_per_pixel(),index) if self.analyzer else None
        return corrected,result

    def process_image(self,source:str|Path,output_dir:str|Path) -> dict:
        source=Path(source);target=Path(output_dir);target.mkdir(parents=True,exist_ok=True)
        frame=load_image(source)
        corrected,result=self.process_frame(frame)
        outputs=[]
        if self.options.save_corrected:
            save_image(target/'corrected.png',corrected);outputs.append('corrected.png')
        if result and self.options.save_overlay:
            save_image(target/'overlay.png',result.overlay);outputs.append('overlay.png')
        rows=[result.values] if result else []
        return self._finish(source,target,rows,outputs,{'input_kind':'image','frames_processed':1})

    def process_video(self,source:str|Path,output_dir:str|Path) -> dict:
        source=Path(source);target=Path(output_dir);target.mkdir(parents=True,exist_ok=True)
        cap=cv2.VideoCapture(str(source))
        if not cap.isOpened(): raise ValueError(f'動画を開けません: {source}')
        fps=float(cap.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(fps) or fps<=0:cap.release();raise ValueError('動画のfpsを取得できません')
        step=self.options.frame_step
        if step<1:cap.release();raise ValueError('frame_stepは1以上')
        fourcc=cv2.VideoWriter_fourcc(*('mp4v' if self.options.video_format=='mp4' else 'MJPG'))
        extension='.mp4' if self.options.video_format=='mp4' else '.avi'
        corrected_writer=overlay_writer=None
        rows=[];outputs=[];original_index=0;processed=0
        try:
            while True:
                ok,frame=cap.read()
                if not ok:break
                if original_index % step:
                    original_index+=1;continue
                corrected, result=self.process_frame(frame,original_index)
                wh=(corrected.shape[1],corrected.shape[0])
                if processed==0:
                    # 映像コーデックの偶数画素制約を事前に明示して記録。
                    wh=(wh[0]-wh[0]%2,wh[1]-wh[1]%2)
                    if min(wh)<2:raise ValueError('動画出力サイズが小さすぎます')
                    if self.options.save_corrected:
                        fn='corrected'+extension
                        corrected_writer=cv2.VideoWriter(str(target/fn),fourcc,fps/step,wh)
                        if not corrected_writer.isOpened():raise ValueError('補正動画を保存できません')
                        outputs.append(fn)
                    if self.options.save_overlay:
                        fn='overlay'+extension
                        overlay_writer=cv2.VideoWriter(str(target/fn),fourcc,fps/step,wh)
                        if not overlay_writer.isOpened():raise ValueError('確認動画を保存できません')
                        outputs.append(fn)
                if corrected_writer is not None:corrected_writer.write(corrected[:wh[1],:wh[0]])
                if overlay_writer is not None:overlay_writer.write((result.overlay if result else corrected)[:wh[1],:wh[0]])
                if result:rows.append(result.values)
                processed+=1;original_index+=1
        finally:
            cap.release()
            if corrected_writer:corrected_writer.release()
            if overlay_writer:overlay_writer.release()
        if processed==0:raise ValueError('入力動画にフレームがありません')
        return self._finish(source,target,rows,outputs,{'input_kind':'video','input_fps':fps,
                             'output_fps':fps/step,'frames_read':original_index,
                             'frames_processed':processed,'output_size_px':list(wh),
                             'frame_step':step,'audio_preserved':False})

    def _finish(self,source:Path,target:Path,rows:list,outputs:list,metadata:dict):
        if rows:
            with (target/'measurements.csv').open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0].keys()),extrasaction='ignore')
                writer.writeheader();writer.writerows(rows)
            outputs.append('measurements.csv')
        manifest={'schema_version':1,'program_version':__version__,
                  'created_utc':datetime.now(timezone.utc).isoformat(),
                  'input':str(source.resolve()),'input_sha256':sha256(source),
                  'lens':self.lens,'plane':self.plane,
                  'scale_mm_per_pixel':self.options.scale_mm_per_pixel,
                  'analyzer':self.analyzer.name if self.analyzer else 'none',
                  'outputs':outputs,'metadata':metadata}
        dump_json(target/'manifest.json',manifest)
        return manifest
