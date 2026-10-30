# agent/wakeword

呼びかけ「ミク」専用の検出モデル（openWakeWord 形式の ONNX）を学習・評価する道具。学習済みモデルは `~/.cache/saru9000/models/wakeword/miku.onnx` にでき、repo には入れない（負例に使う openWakeWord の ACAV100M 特徴量が CC BY-NC-SA のため、モデルにも非商用の制約がかかる）。経緯と結果は #108。

## 前提

- mouse（CUDA の使える NVIDIA GPU、空き: データ置き場に約 22G・作業ディレクトリに約 5G）
- `uv`、`docker`（VOICEVOX をローカルで動かす場合）
- 置き場は環境変数で変えられる
  - `WAKEWORD_DATA`（既定 `/mnt/shared/wakeword`）: ダウンロードするデータ
  - `WAKEWORD_WORK`（既定 `~/wakeword-work`）: 合成音声・特徴量・評価用の録音

以下は repo のルートで、学習用の Python 環境とキャッシュを作業ディレクトリに閉じ込めて実行する。

```
export UV_PROJECT_ENVIRONMENT=~/wakeword-work/.venv UV_CACHE_DIR=~/wakeword-work/uv-cache
alias ww='uv run --project agent/wakeword'
```

## 手順

1. データを取る（ACAV100M 特徴量 17G、MIT の残響、AudioSet の雑音、FLEURS ja）

   ```
   ww agent/wakeword/download.py
   ```

2. 評価用の録音を vaio からコピーする

   ```
   rsync -a --exclude internal --exclude direct --exclude raw vaio:asr-bench/ ~/wakeword-work/asr-bench/
   ```

3. VOICEVOX で正例・負例を合成する。vaio の VOICEVOX（既定 `http://vaio:50021`）でもできるが、vaio は 2 コアで遅く core の読み上げとも取り合うので、mouse で動かす方が速い

   ```
   docker run -d --name wakeword-voicevox -p 127.0.0.1:50121:50021 voicevox/voicevox_engine:cpu-0.25.2
   ww agent/wakeword/synth.py --voicevox http://localhost:50121 --jobs 8
   ```

4. 学習する（augment と特徴量の計算、`auto_train`、ONNX の書き出し）

   ```
   ww agent/wakeword/train.py
   ```

5. 評価する。しきい値ごとの表と、採用するしきい値が出る

   ```
   ww agent/wakeword/evaluate.py
   ```

## 後片付け

モデルファイルとスクリプトだけ残す。

```
docker rm -f wakeword-voicevox && docker rmi voicevox/voicevox_engine:cpu-0.25.2
rm -rf ~/wakeword-work /mnt/shared/wakeword
```
