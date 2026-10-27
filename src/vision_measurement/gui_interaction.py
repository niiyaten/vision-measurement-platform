"""Reusable local GUI interaction primitives (image clicks and ROI crop)."""
from __future__ import annotations
from pathlib import Path
import cv2
import numpy as np
import streamlit as st
from PIL import Image, ImageDraw

IMAGE_EXTENSIONS={'.png','.jpg','.jpeg','.bmp','.tif','.tiff'}


def preview_frame(source: str, frame_index: int = 0) -> np.ndarray:
    """Load still image or frame of video without writing a temporary image."""
    from .io import load_image
    path=Path(source)
    if not path.is_file():raise ValueError('既存の画像・動画ファイルを指定してください')
    if path.suffix.lower() in IMAGE_EXTENSIONS:return load_image(path)
    cap=cv2.VideoCapture(str(path))
    if not cap.isOpened():raise ValueError(f'動画を開けません: {path}')
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES,max(0,int(frame_index)))
        ok,frame=cap.read()
        if not ok:raise ValueError('指定したフレームを読み込めません')
        return frame
    finally:
        cap.release()


def frame_picker(source: str, key: str) -> int:
    """Return a chosen frame index, 0 for a still image."""
    if not source or not Path(source).is_file():return 0
    if Path(source).suffix.lower() in IMAGE_EXTENSIONS:return 0
    cap=cv2.VideoCapture(source)
    try:
        count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if cap.isOpened() else 0
    finally:cap.release()
    return st.number_input('確認する動画フレーム番号',min_value=0,max_value=max(0,count-1),
                           value=0,step=1,key=key)


def pil_preview(frame: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))


def four_clicks(frame: np.ndarray, identity: str, key: str) -> list[list[float]]:
    """Capture exactly four clicks in original pixel coordinates.

    The input image is resized for display only; original coordinates are retained.
    A source/frame change clears previous clicks to prevent accidental reuse.
    """
    from streamlit_image_coordinates import streamlit_image_coordinates
    identity_key=key+'_identity'
    points_key=key+'_points'
    event_key=key+'_last_event'
    nonce_key=key+'_nonce'
    if st.session_state.get(identity_key)!=identity:
        st.session_state[identity_key]=identity
        st.session_state[points_key]=[]
        st.session_state[event_key]=None
        st.session_state[nonce_key]=st.session_state.get(nonce_key,0)+1
    points=st.session_state[points_key]
    if st.button('4点をやり直す',key=key+'_clear'):
        points=[]
        st.session_state[points_key]=[]
        st.session_state[event_key]=None
        st.session_state[nonce_key]+=1
        st.rerun()
    rgb=pil_preview(frame)
    max_width=900
    ratio=min(1.,max_width/rgb.width)
    preview=rgb.resize((max(1,round(rgb.width*ratio)),max(1,round(rgb.height*ratio))))
    draw=ImageDraw.Draw(preview)
    for i,(x,y) in enumerate(points):
        px,py=round(x*ratio),round(y*ratio)
        draw.ellipse((px-5,py-5,px+5,py+5),outline='red',width=3)
        draw.text((px+7,py-15),str(i+1),fill='red')
    if len(points)>1:
        draw.line([(int(x*ratio),int(y*ratio)) for x,y in points],fill='orange',width=2)
    labels=['左上','右上','右下','左下']
    st.write('指定順序：左上 → 右上 → 右下 → 左下')
    st.caption('クリック済み：'+str(len(points))+'/4'+(' ｜ 次：'+labels[len(points)] if len(points)<4 else ' ｜ 完了'))
    event=streamlit_image_coordinates(preview,key=f'{key}_canvas_{st.session_state[nonce_key]}')
    if event is not None and len(points)<4:
        identity_event=(event.get('unix_time'),event.get('x'),event.get('y'))
        if identity_event!=st.session_state.get(event_key):
            st.session_state[event_key]=identity_event
            x=float(event['x'])/ratio;y=float(event['y'])/ratio
            x=min(frame.shape[1]-1,max(0,x));y=min(frame.shape[0]-1,max(0,y))
            points.append([x,y])
            st.session_state[points_key]=points
            st.rerun()
    if points:st.caption('画像座標 (px)：'+', '.join(f'{labels[i]} ({x:.1f}, {y:.1f})' for i,(x,y) in enumerate(points)))
    return points


def drag_roi(frame: np.ndarray, key: str) -> tuple[int,int,int,int] | None:
    """Select a rectangle by dragging its edges/corners in the viewer."""
    from streamlit_cropper import st_cropper
    image=pil_preview(frame)
    rect=st_cropper(image,realtime_update=True,return_type='box',key=key,box_color='#1d82f5')
    if not rect:return None
    x0=int(rect['left']);y0=int(rect['top'])
    x1=x0+int(rect['width']);y1=y0+int(rect['height'])
    if not (0<=x0<x1<=frame.shape[1] and 0<=y0<y1<=frame.shape[0]):
        st.warning('ROIが画像範囲内に収まるように指定してください')
        return None
    return (x0,y0,x1,y1)
