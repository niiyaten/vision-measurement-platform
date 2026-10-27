"""Streamlit GUI。処理はAPI層へ委譲。"""
from pathlib import Path
import json
import tempfile
import streamlit as st
from vision_measurement.calibration import calibrate_lens,calibrate_plane_grid,calibrate_plane_points
from vision_measurement.io import dump_json,load_profile,load_image
from vision_measurement.processing import MeasurementEngine,ProcessOptions
from vision_measurement.analysis import create_analyzer

st.set_page_config(page_title='画像・動画計測',layout='wide')
st.title('画像・動画計測プラットフォーム')
st.caption('校正データを再利用し、補正と計測を共通の処理で実行します。動画・画像はローカルPCで処理します。')
ROOT=Path.cwd();PROFILES=ROOT/'profiles';PROFILES.mkdir(exist_ok=True)

def choose_profile(label,kind,key):
    paths=sorted(PROFILES.glob('*.json'))
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
    mode=st.radio('校正の種類',['レンズ校正（円グリッド動画）','平面校正（円グリッド画像・動画）','平面校正（4点以上の手動指定）'])
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
    if '手動指定' in mode:
        st.info('画像上の対応点4個以上を、画像座標(px)と実座標(mm)の組で入力します。正確な寸法の分かる点を使ってください。')
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
    if lens is None and plane is None:
        mm=st.number_input('射影変換なしのときの分解能 (mm/px)。0ならpxのみ',value=0.,min_value=0.,format='%.6f')
    else:mm=0.
    st.subheader('2. 計測入力')
    source=st.text_input('計測対象の画像・動画パス')
    analysis=st.selectbox('計測方法',['foil_shift','checkerboard','edge','none'],format_func=lambda x:
        {'foil_shift':'電極箔の位置ずれ','checkerboard':'市松模様（格子交点）','edge':'汎用エッジ','none':'補正のみ'}[x])
    baseline=st.number_input('電極箔の基準X座標(px)。0は初回検出を基準',value=0.) if analysis=='foil_shift' else 0.
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
            engine=MeasurementEngine(lens,plane,create_analyzer(analysis,**extras),opts)
            result=(engine.process_image(source,out) if Path(source).suffix.lower() in
                    ('.png','.jpg','.jpeg','.bmp','.tif','.tiff') else engine.process_video(source,out))
            st.success(f'出力が完了しました: {out}')
            st.json(result['metadata'])
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
