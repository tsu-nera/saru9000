# agent/core

saru-core。vaio に常駐するサーバで、頭脳（Claude）・読み上げ（VOICEVOX）・状態を持ち、stage（ブラウザ）と文字クライアントを WebSocket で繋ぐ。全体の設計と最終形は #18、この実装範囲は #20。

今の範囲は「文字で話しかけると、塊ごとの `speak`（wav＋母音タイムライン）が stage に届く」まで。聞き取り・表情・ツール・`motion` は入っていない（後続の Issue）。

## 前提

- `claude` にログイン済み（サブスク。起動時に `ANTHROPIC_API_KEY` は外す）
- `uv` がある
- VOICEVOX Engine が動いていること（vaio の `home/compose.yaml`）。無い・落ちている場合は文字だけで応答する

## 起動

```
./agent/core/server.py                       # 0.0.0.0:8765、sonnet
./agent/core/server.py --model opus --port 8765
./agent/core/server.py --host 127.0.0.1      # このマシンからだけ
```

ポートは既定 `8765`。`agent/web/dist` があれば `/` で stage を配信する。無ければ `/` は 404 で、`agent/web` で `npm run build` するよう案内を返す。

| 環境変数 | 既定 | 内容 |
|---|---|---|
| `VOICEVOX_URL` | `http://127.0.0.1:50021` | VOICEVOX Engine の URL |
| `VOICEVOX_SPEAKER` | `3` | 話者 ID |
| `VOICEVOX_SPEED` | `1.2` | 話速（`speedScale`） |

## メッセージ

仕様は #18 の表を正とする。`/ws?role=stage|viewer`（省略・不明な role は `viewer`）に JSON のテキストフレームで送る。

| 方向 | type | 今の実装 |
|---|---|---|
| core → 全員 | `state` | 接続直後に現在値、以降は `thinking` / `speaking` / `idle` の遷移（`listening` は #23） |
| core → 全員 | `utterance` | `who=saru` を塊ごとに。`user` の `utterance` は聞き取りと一緒に #23 で入れるので送らない |
| core → stage | `speak` | `id`（プロセス内で増える整数）, `text`, `wav`（base64）, `visemes`。`expression` は #24 まで無し |
| stage → core | `speak_started` / `speak_ended` | `speak_ended` だけ使う |
| stage → core | `ready` / `motion_ended` | 検証して受けるだけ |
| client → core | `text_input` | 使う |

未知の type・欠けた／型の違うフィールド・JSON でないフレームは、ログに警告を出して捨てる。

### speak の進め方

- 応答は `。！？!?` と改行（最初の塊だけ `、` も）で区切り、1 塊ずつ `speak` を送る。次の塊は、前の塊の `speak_ended` が届くか、wav の長さ＋2 秒が過ぎてから送る。stage が 1 つの音声を順に鳴らす前提に揃え、落ちた stage で固まらないよう timeout を塊ごとに持つため。合成は送信中に次の塊を先回りして行う
- 音を鳴らすのは `role=stage` の接続だけ。複数あれば最後に接続した 1 本。応答の開始時に stage が無ければ合成せず、`utterance` だけを送る
- VOICEVOX が失敗したら、その応答の残りは読み上げを諦める。`utterance` は送り続ける
- 応答中（`state` が `idle` 以外）に来た `text_input` は捨てる

### visemes

`speak.visemes` は `[{"t": 開始秒, "v": 母音}]`。`t` は wav 先頭からの秒で、`v` は `a i u e o closed`。

- 母音 `a i u e o`（無声化の `A I U E O` も同じ）はそのまま小文字
- 子音 `m b p my by py` の区間は `closed`。他の子音の区間は続く母音と同じ
- `N`・`cl`・pause・前後の無音は `closed`
- 同じ `v` が続く区間はまとめる

VOICEVOX Engine と同じ手順で区間をフレーム（24000/256 = 93.75 fps）に丸めて並べる（音素ごとに `round(秒 / speedScale * 93.75)`）。秒のまま足すと誤差が溜まって wav の長さとずれる。pause は `pauseLength`（あれば）→ `pauseLengthScale` の順に反映する。

wav の長さとの差は、VOICEVOX 実機に対するテストで確かめる（VOICEVOX に繋がらなければ skip）:

```
uv run --with pytest pytest agent/core -v -s
```

## 手動確認

```
websocat 'ws://127.0.0.1:8765/ws?role=stage'
{"type":"text_input","text":"こんにちは"}
```

先に `{"type":"state","state":"idle"}` が届き、`thinking` → `speaking` を挟んで `speak` と `utterance` が返る。`speak` を受けたら `{"type":"speak_ended","id":<speak の id>}` を送ると次の塊に進む（送らなければ wav の長さ＋2 秒で進む）。Claude のサブスク枠を少し使う。

## vaio の firewalld

vaio の wlan0（public zone）は塞いだまま、tailnet（`tailscale0` は trusted zone）からだけ使う。VOICEVOX と同じ扱いで、`8765` を public に開けないこと。

## テスト

```
uv run --with pytest pytest agent/core
```

aiohttp と claude-agent-sdk が無くても通るよう、`session.py` / `protocol.py` / `speech.py` / `brain.py`（モジュール先頭）は標準ライブラリだけを import する。aiohttp は `server.py` だけ、Claude SDK は `ClaudeBrain` の中だけ。
