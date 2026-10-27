"""vmeasure CLI。GUIでも同じライブラリを呼び出す。"""
from pathlib import Path
import json
import typer
from .calibration import calibrate_lens, calibrate_plane_grid, calibrate_plane_points, calibrate_plane_rectangle
from .io import dump_json, load_profile, load_image
from .processing import MeasurementEngine, ProcessOptions
from .analysis import create_analyzer

app=typer.Typer(help='画像・動画の幾何校正と定量計測',no_args_is_help=True)


def grid_size(value: str):
    try:
        a,b=value.lower().split('x');return int(a),int(b)
    except Exception as exc:raise typer.BadParameter('14x10 の形式で指定してください') from exc

@app.command('lens-calibrate')
def lens_calibrate(input:Path,output:Path=Path('profiles/lens.json'),grid:str='14x10',
                   pitch_mm:float=14.,step:int=10,max_checked:int=300,
                   fill_holes:bool=True):
    """円グリッド動画からレンズ係数を推定する。"""
    result=calibrate_lens(input,grid_size(grid),pitch_mm,step,max_checked,fill_holes=fill_holes)
    dump_json(output,result)
    typer.echo(f'保存: {output} / RMS={result["rms_reprojection_px"]:.4f} px')

@app.command('plane-grid')
def plane_grid(input:Path,output:Path=Path('profiles/plane.json'),lens:Path|None=None,
               grid:str='14x10',pitch_mm:float=14.,step:int=15,
               fill_holes:bool=True,max_motion_px:float=2.5):
    """静止画または固定円グリッド動画で平面校正する。"""
    l=load_profile(lens,'lens') if lens else None
    result=calibrate_plane_grid(input,grid_size(grid),pitch_mm,l,step=step,
                                 max_stationary_motion_px=max_motion_px,fill_holes=fill_holes)
    dump_json(output,result)
    typer.echo(f'保存: {output} / {1/result["pixels_per_mm"]:.5f} mm/px')

@app.command('plane-points')
def plane_points(image:Path,correspondences:Path,output:Path=Path('profiles/plane.json'),
                 lens:Path|None=None,pixels_per_mm:float=2.):
    """JSONで指定した画像座標と実寸座標の対応点から射影行列を求める。"""
    frame=load_image(image)
    data=json.loads(correspondences.read_text(encoding='utf-8'))
    import numpy as np
    result=calibrate_plane_points(np.asarray(data['image_points_px']),
                                   np.asarray(data['world_points_mm']),
                                   (frame.shape[1],frame.shape[0]),
                                   load_profile(lens,'lens') if lens else None,pixels_per_mm)
    dump_json(output,result);typer.echo(f'保存: {output}')

@app.command('plane-rectangle')
def plane_rectangle(image:Path,points:Path,
                    width_mm:float=typer.Option(...,help="長方形の実寸幅 mm"),
                    height_mm:float=typer.Option(...,help="長方形の実寸高さ mm"),
                    output:Path=Path('profiles/plane.json'),lens:Path|None=None):
    """4点クリックで得た座標JSONと実寸から射影行列を求める。"""
    frame=load_image(image)
    data=json.loads(points.read_text(encoding='utf-8'))
    import numpy as np
    coords=data['image_points_px'] if isinstance(data,dict) else data
    result=calibrate_plane_rectangle(np.asarray(coords),width_mm,height_mm,
                                     (frame.shape[1],frame.shape[0]),
                                     load_profile(lens,'lens') if lens else None)
    dump_json(output,result)
    typer.echo(f'保存: {output} / {1/result["pixels_per_mm"]:.5f} mm/px')

@app.command('process')
def process(input:Path,output_dir:Path=Path('results/latest'),lens:Path|None=None,
            plane:Path|None=None,analysis:str='foil_shift',
            scale_mm_per_pixel:float|None=None,video_format:str='mp4',
            frame_step:int=1, save_video:bool=True, save_overlay:bool=True,
            baseline_x:float|None=None, roi:str|None=None,
            polarity:str='both',threshold:str='otsu',min_area:int=120,
            foil_min_separation:int=15, foil_blur:int=5, foil_sobel:int=3,
            foil_min_gradient:float=4., bottom_polarity:str='bright',
            bottom_blur:int=5, bottom_sobel:int=3, bottom_min_gradient:float=40.,
            bottom_column_step:int=4, bottom_tracking_window:float=40.,
            bottom_min_coverage:float=.60, bottom_fit_tolerance:float=6.,
            bottom_reference_x:float|None=None, bottom_baseline_mode:str='first_valid',
            bottom_baseline_y:float|None=None, bottom_baseline_frames:int=10,
            bottom_save_points:bool=False):
    """任意の画像・動画を補正し、計測CSVと確認動画を保存する。"""
    if video_format not in ('mp4','avi'):raise typer.BadParameter('video-formatはmp4またはavi')
    options={}
    if analysis=='foil_shift':
        options.update(baseline_x=baseline_x,min_separation_px=foil_min_separation,
                       gaussian_kernel=foil_blur,sobel_kernel=foil_sobel,
                       min_gradient=foil_min_gradient)
    if analysis=='foil_bottom':
        options.update(polarity=bottom_polarity,gaussian_kernel=bottom_blur,
                       sobel_kernel=bottom_sobel,min_gradient=bottom_min_gradient,
                       column_step=bottom_column_step,tracking_window_px=bottom_tracking_window,
                       min_coverage=bottom_min_coverage,fit_tolerance_px=bottom_fit_tolerance,
                       reference_x_px=bottom_reference_x,baseline_mode=bottom_baseline_mode,
                       baseline_y_px=bottom_baseline_y,baseline_frames=bottom_baseline_frames,
                       save_contour_points=bottom_save_points)
    if analysis=='checkerboard':
        options.update(polarity=polarity,threshold=threshold,min_area=min_area)
    if roi and analysis in ('foil_shift','foil_bottom','checkerboard','edge'):
        try:options['roi']=tuple(map(int,roi.split(',')))
        except ValueError as exc:raise typer.BadParameter('roiは x0,y0,x1,y1') from exc
        if len(options['roi'])!=4:raise typer.BadParameter('roiは4値')
    engine=MeasurementEngine(load_profile(lens,'lens') if lens else None,
          load_profile(plane,'plane') if plane else None,
          create_analyzer(analysis,**options),
          ProcessOptions(save_video,save_overlay,video_format,frame_step,scale_mm_per_pixel))
    if input.suffix.lower() in ('.png','.jpg','.jpeg','.bmp','.tif','.tiff'):
        result=engine.process_image(input,output_dir)
    else:result=engine.process_video(input,output_dir)
    typer.echo(f'結果保存: {output_dir} / 解析: {result["analyzer"]}')

if __name__=='__main__': app()
