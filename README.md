# Vision Measurement Platform

画像・動画を補正し、寸法や位置の変化を数値にするPythonツールです。

レンズ校正と平面校正を共通機能として実装しています。電極箔の位置ずれ計測を最初の解析機能とし、市松模様の各マス4辺の計測やエッジ検出にも対応します。Streamlit、CLI、Python APIは同じ処理を呼び出します。

このリポジトリは初期検証版です。現場設備での測定精度はまだ確認していません。

## 最初に試す

Python 3.11と[uv](https://docs.astral.sh/uv/)を使用します。WindowsのPowerShellで次を実行してください。

```powershell
uv sync --group dev
uv run streamlit run src/vision_measurement/gui.py
```

CLIで合成動画を処理する場合は、次のコマンドを使います。

```powershell
uv run vmeasure process tests/fixtures/foil_shift.mp4 `
  --analysis foil_shift --scale-mm-per-pixel 0.25 `
  --output-dir results/foil_demo
```

`results/foil_demo/` にCSV、補正動画、エッジを重ねた確認動画、処理条件を保存します。

## このツールでできること

| 処理 | 入力 | 出力 |
| --- | --- | --- |
| レンズ校正 | 動かした円グリッドのAVI | カメラ行列、ひずみ係数、RMS |
| 平面校正 | 固定円グリッド、画像をクリックした長方形4隅、または対応点 | 射影行列、mm/px、RMS |
| 補正 | 画像・動画、保存済みの校正JSON | 補正画像・動画 |
| 電極箔の位置ずれ | エッジの見える動画 | 左右端、幅、中心、基準位置との差 |
| 市松模様 | 白黒マスが写った画像・動画 | 全マスID、上・右・下・左の4辺、平均・母標準偏差 |
| 汎用エッジ | 画像・動画 | Cannyエッジの可視化、検出画素数 |

レンズ補正と射影変換は、どちらも省略できます。mm換算する場合は、平面校正または分解能の指定が必要です。

## GUIで長方形の四隅をクリックして射影校正する

円グリッド以外にも、実寸が分かる長方形を使えます。操作は次のとおりです。

1. GUIを開き、「校正管理」→「平面校正（長方形の四隅をクリック）」を選びます。
2. 画像またはAVI/MP4のローカルパスを入力します。動画ではフレーム番号も選べます。
3. 長方形の実寸幅・高さをmmで入力します。
4. 画像上の四隅を「左上 → 右上 → 右下 → 左下」の順にクリックします。
5. プレビューを確認し、名前を付けて校正JSONを保存します。

先に `uv run python tests/generate_fixtures.py` で生成した `tests/fixtures/rectangle_tilted.png` では、幅100 mm・高さ60 mmとして試せます。
誤クリック時は「4点をやり直す」を押してください。
クリック時の画像は表示用に縮小することがありますが、保存する座標は元解像度のpxです。

この校正では表示用の出力画素密度(px/mm)をクリックした四辺の長さから推定します。
4点の当てはめ残差はほぼ0になるため、RMSが小さくても独立した寸法精度の確認にはなりません。
基準となる長方形は実際の計測対象と同一平面上に設置してください。

CLIで同じ校正を行う場合は対応点ファイルを利用できます。クリック操作はGUI専用です。

```powershell
uv run vmeasure plane-rectangle tests/fixtures/rectangle_tilted.png `
  examples/rectangle_points.json --width-mm 100 --height-mm 60 `
  --output profiles/rectangle_demo.json
```

## GUIでROIをドラッグして指定する

「計測」画面で入力画像・動画を指定し、「画像上でROI（計測範囲）を指定する」にチェックを入れます。
動画ならROIを指定するフレームを選べます。枠のドラッグとハンドル操作で範囲を調整します。
レンズや平面の校正を指定している場合は、その補正後の画像上でROIを指定します。
ROIは電極箔の位置ずれ、市松模様、一般エッジ検出に適用できます。

CLIからは `--roi x0,y0,x1,y1` と指定します。
座標は補正後のフレームにおけるピクセル単位です。

## 市松模様の各マス計測

以前のHTML版の方法に合わせ、二値化した領域は「マスの検出」に使い、
測定値は元のグレースケール画像の白黒境界を再探索して計算します。
各辺の複数位置で明暗変化を調べ、直線をフィットして交点から4隅を求めます。
収縮処理で狭めた輪郭は寸法の計算に使いません。

検出したマスに左上から順にIDを付け、`measurements.csv` に1マス1行で保存します。
上・右・下・左の辺長、4辺平均、標準偏差（母標準偏差、N=4）、色とフレーム番号を記録します。
`summary.csv` にはフレーム単位の検出数・平均・標準偏差を保存します。
`overlay.png` または `overlay.mp4` ではIDと各マスの輪郭を確認できます。

```powershell
uv run vmeasure process tests/fixtures/checkerboard_tiles.png `
  --analysis checkerboard --scale-mm-per-pixel 0.2325581395 `
  --output-dir results/checkerboard_demo
```

上記の分解能は**合成サンプル専用の既知値**です。実画像には流用しないでください。
`tests/generate_fixtures.py` が作る `tests/fixtures/checkerboard_tiles.png` は黒18、白17の計35マスを含むテスト画像です。
`examples/checkerboard_verified/` に、テスト時の各辺CSV・サマリーを用意しています。確認画像はCLI実行で生成します。

面積、照明、反射、外周の欠け方によって検出数が変わります。
HTML版とアルゴリズムの考え方は共通ですが、値の完全一致は保証しません。
現場画像で境界線を重ねて確認し、基準器の既知寸法との誤差を測定してください。

## 3本の動画を使う例

校正用の2本と計測用の1本を、別々に指定できます。

```powershell
uv run vmeasure lens-calibrate lens.avi --grid 14x10 --pitch-mm 14 --output profiles/lens_A.json
uv run vmeasure plane-grid plane.avi --grid 14x10 --pitch-mm 14 --lens profiles/lens_A.json --output profiles/plane_A.json
uv run vmeasure process target.avi --lens profiles/lens_A.json --plane profiles/plane_A.json --analysis foil_shift --output-dir results/run_001
```

校正を繰り返す必要はありません。保存したJSONを別の動画へ適用できます。ただし、レンズのピント・ズーム・撮影解像度が変わった場合は再校正が必要です。射影校正は、カメラと計測面の相対姿勢が変わった場合にやり直します。

## サンプル動画とテスト

`tests/fixtures/` に、プログラムで生成した短いMP4を入れています。

| ファイル | 内容 |
| --- | --- |
| `lens_grid.mp4` | 姿勢を変えた14×10円グリッド |
| `plane_grid.mp4` | 固定した14×10円グリッド |
| `foil_shift.mp4` | 幅方向に左右へ動く明色の箔を模した映像 |

サンプルは合成映像です。実際の設備動画ではありません。動画の元データを作るコードは `tests/generate_fixtures.py` にあります。

```powershell
uv run python tests/generate_fixtures.py
uv run pytest -q
```

テストでは、円グリッド検出、レンズ校正、射影校正、動画出力、位置ずれ計測、保存データを確認します。合成動画で動いても、現場動画での精度を保証するものではありません。

## 結果の保存先

1回の実行ごとにフォルダを分けます。

```text
results/run_001/
  measurements.csv    # 位置ずれはフレームごと、市松模様はフレーム×マスIDごと
  summary.csv         # 市松模様などのフレーム別集計（必要な場合）
  corrected.mp4       # 補正結果。必要なときだけ保存
  overlay.mp4         # エッジと基準位置を重ねた確認動画
  manifest.json       # 元動画のSHA-256、校正値、処理条件、ソフトウェア版
```

動画の既定形式はMP4です。容量を優先する確認用途を想定しています。`--video-format avi` でMJPG/AVIを選べます。どちらも再エンコードするため、元動画の画質やメタデータを完全には保ちません。音声も保存しません。

元動画を上書きせず、`manifest.json` にそのSHA-256を記録します。計測結果は、保存動画を再読み込みせず、補正直後のフレームから算出します。

## ファイル構成

```text
src/vision_measurement/
  calibration.py   # 円グリッド検出・幾何校正・4隅の射影校正
  checkerboard.py  # マス検出と4辺のエッジフィット
  processing.py    # レンズ補正・射影変換・動画入出力
  analysis.py      # 計測モジュール
  io.py            # 校正ファイル・ハッシュ・動画入力
  cli.py           # vmeasureコマンド
  gui.py           # Streamlitの画面
  gui_interaction.py # 画像クリック・ドラッグROI
```

Pythonからは `MeasurementEngine` に画像を渡して処理できます。

```python
from vision_measurement.processing import MeasurementEngine
from vision_measurement.analysis import FoilShiftAnalyzer
from vision_measurement.io import load_profile

engine = MeasurementEngine(
    lens=load_profile('profiles/lens_A.json'),
    analyzer=FoilShiftAnalyzer(),
)
corrected, measurement = engine.process_frame(frame, index=0)
```

このAPIはフレーム入力を扱うため、後からカメラ取得処理と接続できます。

## 校正に関する注意

円グリッドは中心間距離を実測したものを使います。白抜きのあるドットにも対応するため、黒塗り補正を初期状態で有効にしています。

校正RMSが小さくても、寸法精度が保証されるわけではありません。独立した基準器で結果を確認してください。平面校正で検証RMSが大きいときは、撮影中にボードが動いていないか確認します。

射影変換で補正できるのは、校正した平面上の座標です。平面から高さのある物体には、同じ変換をそのまま適用できません。

## 現在の制限

長方形の4隅はGUIでクリックできます。任意の4点以上の実座標を使う上級者向け校正は、引き続きGUIのJSON入力欄またはCLIの対応点ファイルで指定します。円グリッド動画では、主に固定状態のフレームを使います。時々刻々と姿勢が変化する平面の追跡補正は対象外です。

電極箔解析は、単純な明暗境界を想定した初期実装です。幅方向の蛇行、反射、背景の変化が大きい現場では、ROI・しきい値・エッジ候補の選び方を検証する必要があります。

## 開発方針

今後の計測手法は `analysis.py` の `Analyzer` インターフェースに追加します。レンズ補正や射影変換のコードは計測手法から独立させています。

READMEは読み手が必要な手順を探せるよう、使用方法・仕様・制限事項を分けて記載しています。文章の整理には [yomiyasu](https://github.com/nanaism/yomiyasu) の考え方を参考にしました。

## 補足：uv.lockについて

この初期版には `uv.lock` を同梱していません。依存関係は `pyproject.toml` に記載してあります。初回の `uv sync` 時にロックファイルを生成します。生成後は必要に応じてGitで管理してください。

## 動作確認動画

[電極箔のエッジ検出確認動画](examples/foil_shift_overlay_example.mp4)を同梱しています。合成動画の解析結果にエッジ線を重ねたものです。入力動画は`tests/fixtures/foil_shift.mp4`です。

## 今回の検証範囲

共通エンジンに対して10件の自動テストを実行し、成功しました。
長方形の4点射影、全35マスの検出・各辺長、ROI内の出力とCSV生成を含みます。
GUIのマウス操作自体は実ブラウザでの手動確認が必要です。
実験映像への計測精度も未検証です。