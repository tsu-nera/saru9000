# agent/core

vaio に常駐するサーバ。頭脳（Claude）・読み上げ（VOICEVOX か Open JTalk）・聞き取り（ReazonSpeech）・状態を持ち、stage（`agent/web`）と文字クライアント（`agent/console`）を WebSocket で繋ぐ。設計とメッセージの仕様は #18。

## 前提

- `claude` にログイン済み（サブスクの枠を使う。API の従量課金は使わない）
- `uv` がある
- キャラクターの声のエンジンが使えること。使えなければ文字だけで応答する
  - `voicevox`（サル）: VOICEVOX Engine（vaio の `home/compose.yaml`）
  - `openjtalk`（ミク）: `open_jtalk`・辞書・音響モデル（下の「Open JTalk」）
- 聞き取り（`--listen`）には `pw-record`（PipeWire）とマイク。モデルは初回に `~/.cache/saru9000/models/` へ自動で取る

## 起動

```
./agent/core/server.py                       # 0.0.0.0:8765、sonnet
./agent/core/server.py --model opus --port 8765
./agent/core/server.py --listen              # マイクで聞き取る
./agent/core/server.py --audio-in a.wav      # マイクの代わりに wav（16kHz・mono・16bit）を流す
```

`agent/web/dist` があれば `/` で stage を配信する。

vaio では tailnet からだけ使う。`8765` を wlan0（public zone）に開けない。

## 設定

`config.json` が既定、`config.local.json`（gitignore）がマシンごとの上書きで、変えたいキーだけを書く。キャラクターは `characters/<名前>.json`、全員に共通のルールは `persona.txt`。踊れる曲と、それを頼む言葉は `config.json` の `dances`（曲を足すときは stage の `agent/web/src/avatar/mmdMotion.js` と素材も足す）。読むのは起動時だけ。

例: ミクにして声を半音高くする

```json
{"character": "miku", "voice": {"pitch": 1.0}}
```

## Open JTalk

ビルド（`$P=$HOME/.local/opt/open_jtalk`）:

1. hts_engine API 1.10: `./configure --prefix=$P && make && make install`
2. Open JTalk 1.11: `CFLAGS="-O2 -std=gnu11" CXXFLAGS="-O2 -std=gnu++14" ./configure --prefix=$P --with-hts-engine-header-path=$P/include --with-hts-engine-library-path=$P/lib --with-charset=UTF-8 && make && make install`
   - `make -j` は使わない（辞書の作成でファイルのコピーがぶつかって失敗する）
   - GCC 15 以降は C23 が既定で古いコードが通らないため `-std=gnu11`
3. 辞書 `open_jtalk_dic_utf_8-1.11.tar.gz` を `$P/` に展開する

ミクの声は CUBE370 氏「MMDAgent用自作音響モデル TYPE-β」。readme に「本ソフトはフリーソフトです。自由にご使用ください。なお，著作権は作者であるCUBE370が保有しています。」とある。配布物は旧形式なので `.htsvoice` への変換が要り、vaio の `~/.cache/saru9000/voices/naip_type_b.htsvoice` を使う。モデルも変換ツールも repo には入れない。

## テスト

```
uv run --with pytest pytest agent/core
```
