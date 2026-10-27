"""Streamlit GUI。処理はAPI層へ委譲。"""
from pathlib import Path
import json
import tempfile
import cv2
import streamlit as st
from vision_measurement.calibration import calibrate_lens,calibrate_plane_grid,calibrate_plane_points,calibrate_plane_rectangle
from vision_measurement.io import dump_json,load_profile,load_image
from vision_measurement.processing import MeasurementEngine,ProcessOptions
from vision_measurement.analysis import create_analyzer
from vision_measurement.gui_interaction import preview_frame,frame_picker,four_clicks,drag_roi

st.set_page_config(page_title='画像・動画計測',layout='wide')
st.title('画像・動画計測プラットフォーム')
st.caption('校正データを再利用し、補正と計測を共通の処理で実行します。動画・画像はローカルPCで処理します。')
ROOT=Path.cwd();PROFILES=ROOT/'profiles';PROFILES.mkdir(exist_ok=True)

def choose_profile(label,kind,key):
    paths=[]
    for path in sorted(PROFILES.glob('*.json')):
        try:
            profile=load_profile(path)
            is_lens=('camera_matrix' in profile and 'homography_undistorted_to_plane' not in profile)
            is_plane='homography_undistorted_to_plane' in profile
            if (kind=='lens' and is_lens) or (kind=='plane' and is_plane):paths.append(path)
        except Exception:continue
    choices=['使用しない','ファイルから読み込む'] + [str(p) for p in paths]
    choice=st.selectbox(label,choices,key=key)
    if choice=='使用しない':return None
    if choice=='ファイルから読み込む':
        uploaded=st.file_uploader(label+' ファイル',type=['json','zip','csv'],key=key+'_upload')
        if uploaded is None:return None
        with tempfile.TemporaryDirectory() as td:
            tmp=Path(td)/uploaded.name;tmp.write_bytes(uploaded.getvalue())
            try:return load_profile(tmp,kind)
            except Exception as exc:st.error(str(exc));return None
    try:return load_profile(choice,kind)
    except Exception as exc:st.error(str(exc));return None

def save_profile(result,name):
    if not name or any(x in name for x in '/\\..'):
        st.error('保存名は英数字・日本語・ハイフン・アンダースコアを使用してください')
        return
    path=PROFILES/(name+'.json');dump_json(path,result)
    st.success(f'校正結果を登録しました: {path}')

screen=st.sidebar.radio('画面',['計測','校正管理','結果の確認'])
if screen=='校正管理':
    mode=st.radio('校正の種類',['レンズ校正（円グリッド動画）','平面校正（円グリッド画像・動画）','平面校正（長方形の四隅をクリック）','平面校正（対応点JSON・上級者向け）'])
    source=st.text_input('校正入力のファイルパス（ローカルPC）')
    name=st.text_input('保存する校正名','calibration_A')
    if mode.startswith('平面'):
        lens=choose_profile('平面校正に使用するレンズ校正','lens','plane_lens')
    cols=st.columns(2)
    with cols[0]:
        x=st.number_input('グリッド列数',value=14,min_value=3)
        y=st.number_input('グリッド行数',value=10,min_value=3)
    with cols[1]:
        pitch=st.number_input('円中心間隔 (mm)',value=14.,min_value=0.001)
        fill=st.checkbox('白抜きドットを黒塗り補正して検出',value=True)
    rectangle_points=None
    if '四隅をクリック' in mode:
        st.subheader('既知寸法の長方形を4点クリック')
        st.caption('長方形は計測する平面上に置きます。入力する寸法は撮影画像のpxではなく実寸(mm)です。')
        col_a,col_b=st.columns(2)
        with col_a:rectangle_width=st.number_input('長方形の実寸幅 (mm)',min_value=.001,value=100.,step=1.)
        with col_b:rectangle_height=st.number_input('長方形の実寸高さ (mm)',min_value=.001,value=60.,step=1.)
        idx=frame_picker(source,'plane_rectangle_frame')
        if source and Path(source).is_file():
            try:
                frame=preview_frame(source,idx)
                rectangle_points=four_clicks(frame,f'{Path(source).resolve()}::{idx}',key='plane_corners')
                if len(rectangle_points)==4:
                    import numpy as np
                    preview=calibrate_plane_rectangle(np.asarray(rectangle_points),rectangle_width,
                                                       rectangle_height,(frame.shape[1],frame.shape[0]),lens)
                    st.caption(f'出力解像度：{preview["output_size_px"]} px、'
                               f'分解能：{1/preview["pixels_per_mm"]:.6f} mm/px（推定）')
                    if st.checkbox('変換後の画像を確認',value=True):
                        from vision_measurement.processing import MeasurementEngine
                        st.image(cv2.cvtColor(MeasurementEngine(lens,preview).correct(frame),
                                                  cv2.COLOR_BGR2RGB),caption='射影補正プレビュー')
            except Exception as exc:st.error(str(exc))
    elif '対応点JSON' in mode:
        st.info('こちらは上級者向けです。通常は「長方形の四隅をクリック」を使用してください。')
        st.code('{"image_points_px": [[100,100],[400,100],[400,300],[100,300]],\n "world_points_mm": [[0,0],[100,0],[100,60],[0,60]]}',language='json')
        points=st.text_area('対応点JSON',height=150)
        ppm=st.number_input('出力画素密度 (px/mm)',value=2.,min_value=0.01)
    else:
        step=st.number_input('動画フレーム間隔',value=10,min_value=1)
    if st.button('校正を実行',type='primary'):
        try:
            if not Path(source).is_file():raise ValueError('校正入力ファイルを指定してください')
            if mode.startswith('レンズ'):
                result=calibrate_lens(source,(int(x),int(y)),pitch,int(step),fill_holes=fill)
            elif '円グリッド' in mode:
                result=calibrate_plane_grid(source,(int(x),int(y)),pitch,lens,step=int(step),fill_holes=fill)
            elif '四隅をクリック' in mode:
                if not rectangle_points or len(rectangle_points)!=4:raise ValueError('4隅を順にクリックしてください')
                import numpy as np
                frame=preview_frame(source,idx)
                result=calibrate_plane_rectangle(np.asarray(rectangle_points),rectangle_width,rectangle_height,
                                                 (frame.shape[1],frame.shape[0]),lens)
            else:
                import numpy as np
                data=json.loads(points);frame=load_image(source)
                result=calibrate_plane_points(np.array(data['image_points_px']),np.array(data['world_points_mm']),
                        (frame.shape[1],frame.shape[0]),lens,pixels_per_mm=float(ppm))
            save_profile(result,name)
            st.json(result)
        except Exception as exc:st.error(str(exc))
elif screen=='計測':
    st.subheader('1. 補正の選択')
    c1,c2=st.columns(2)
    with c1:lens=choose_profile('レンズひずみ補正','lens','process_lens')
    with c2:plane=choose_profile('平面・射影変換','plane','process_plane')
    if plane is None:
        mm=st.number_input('射影変換なしのときの分解能 (mm/px)。0ならpxのみ',value=0.,min_value=0.,format='%.6f')
    else:mm=0.
    st.subheader('2. 計測入力')
    source=st.text_input('計測対象の画像・動画パス')
    analysis=st.selectbox('計測方法',['foil_shift','checkerboard','edge','none'],format_func=lambda x:
        {'foil_shift':'電極箔の位置ずれ','checkerboard':'市松模様（各マスの4辺）','edge':'汎用エッジ','none':'補正のみ'}[x])
    baseline=st.number_input('電極箔の基準X座標(px)。0は初回検出を基準',value=0.) if analysis=='foil_shift' else 0.
    roi=None
    if analysis in ('foil_shift','checkerboard','edge'):
        if st.checkbox('画像上でROI（計測範囲）を指定する',value=False):
            if source and Path(source).is_file():
                try:
                    idx=frame_picker(source,'process_roi_frame')
                    original=preview_frame(source,idx)
                    corrected=MeasurementEngine(lens,plane).correct(original)
                    st.caption('矩形をドラッグまたは四隅のハンドルで調整してください。補正後の座標を使用します。')
                    roi=drag_roi(corrected,key='process_roi_cropper_'+str(Path(source).resolve())+'_'+str(idx))
                    if roi:st.caption(f'ROI: x0={roi[0]}, y0={roi[1]}, x1={roi[2]}, y1={roi[3]} px')
                except Exception as exc:st.error(str(exc))
            else:st.warning('ROI選択の前に計測対象ファイルを指定してください')
    if analysis=='checkerboard':
        color=st.selectbox('計測するマスの色',['both','dark','light'],format_func=lambda x:{'both':'黒・白の両方','dark':'黒のみ','light':'白のみ'}[x])
        minimum=st.number_input('マスの最小面積 (px²)',min_value=20,value=120,step=20)
        thresh=st.selectbox('二値化方式',['otsu','adaptive'])
    
    st.subheader('3. 保存設定')
    out=st.text_input('結果保存先','results/current')
    c1,c2,c3=st.columns(3)
    with c1:save_corr=st.checkbox('補正動画・画像を保存',True)
    with c2:save_ov=st.checkbox('確認動画・画像を保存',True)
    with c3:fmt=st.selectbox('動画形式',['mp4','avi'])
    if st.button('補正と計測を実行',type='primary'):
        try:
            if not Path(source).is_file():raise ValueError('計測対象ファイルを指定してください')
            opts=ProcessOptions(save_corr,save_ov,fmt,1,mm if mm>0 else None)
            extras={'baseline_x':baseline if baseline!=0 else None} if analysis=='foil_shift' else {}
            if analysis=='checkerboard':extras.update(polarity=color,min_area=int(minimum),threshold=thresh)
            if roi is not None:extras['roi']=roi
            engine=MeasurementEngine(lens,plane,create_analyzer(analysis,**extras),opts)
            result=(engine.process_image(source,out) if Path(source).suffix.lower() in
                    ('.png','.jpg','.jpeg','.bmp','.tif','.tiff') else engine.process_video(source,out))
            st.success(f'出力が完了しました: {out}')
            st.json(result['metadata'])
            import pandas as pd
            csv=Path(out)/'measurements.csv'
            if csv.is_file():
                st.subheader('計測結果')
                st.dataframe(pd.read_csv(csv,encoding='utf-8-sig'),use_container_width=True)
            summary=Path(out)/'summary.csv'
            if summary.is_file():
                st.subheader('フレーム別サマリー')
                st.dataframe(pd.read_csv(summary,encoding='utf-8-sig'),use_container_width=True)
            overlay_image=Path(out)/'overlay.png'
            overlay_video=Path(out)/('overlay.'+fmt)
            if overlay_image.is_file():st.image(str(overlay_image),caption='計測結果・各マスのID')
            elif overlay_video.is_file() and fmt=='mp4':
                st.video(overlay_video.read_bytes(),format='video/mp4')
        except Exception as exc:st.error(str(exc))
else:
    st.subheader('保存済みの実行結果')
    results=sorted((ROOT/'results').glob('*/manifest.json')) if (ROOT/'results').exists() else []
    for path in results[-15:][::-1]:
        with st.expander(str(path.parent)):
            manifest=json.loads(path.read_text(encoding='utf-8'))
            st.write('入力:',manifest['input'])
            st.write('解析:',manifest['analyzer'])
            st.write('出力:',', '.join(manifest['outputs']))
