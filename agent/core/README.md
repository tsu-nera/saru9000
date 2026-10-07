# agent/core

saru-core。vaio に常駐するサーバで、頭脳（Claude）・読み上げ（VOICEVOX）・状態を持ち、stage（ブラウザ）と文字クライアントを WebSocket で繋ぐ。全体の設計と最終形は #18、この実装範囲は #20。

今の範囲は「文字か声で話しかけると、塊ごとの `speak`（wav＋母音タイムライン）が stage に届く」まで。聞き取りは #23。表情は応答文のタグで変える（#24）。「踊って」で踊る（#25）。

## 前提

- `claude` にログイン済み（サブスク。起動時に `ANTHROPIC_API_KEY` は外す）
- `uv` がある
- VOICEVOX Engine が動いていること（vaio の `home/compose.yaml`）。無い・落ちている場合は文字だけで応答する

## 起動

```
./agent/core/server.py                       # 0.0.0.0:8765、sonnet
./agent/core/server.py --model opus --port 8765
./agent/core/server.py --host 127.0.0.1      # このマシンからだけ
./agent/core/server.py --listen              # マイクで聞き取る
./agent/core/server.py --audio-in a.wav --audio-in b.wav   # マイクの代わりに wav を順に流す
```

ポートは既定 `8765`。`agent/web/dist` があれば `/` で stage を配信する。無ければ `/` は 404 で、`agent/web` で `npm run build` するよう案内を返す。

## 設定とキャラクター

`config.json` が既定（commit 済み）、`config.local.json` がマシンごとの上書き（gitignore、任意）。上書きしたいキーだけを書く。読むのは起動時だけなので、変えたら server を起動し直す。

| キー | 内容 |
|---|---|
| `character` | 演じるキャラクター。`characters/<名前>.json` の名前（`saru` / `miku`） |
| `voicevox_url` | VOICEVOX Engine の URL |
| `voice` | キャラクターの声の上書き（キーは下の `voice` と同じ）。声だけ試したいときに使う |

例: vaio でミクにして、声を少し高くする

```json
{"character": "miku", "voice": {"pitch": 0.05}}
```

`characters/<名前>.json` はキャラクターごとの名乗りと声:

| キー | 内容 |
|---|---|
| `name` | 表示名。stage の HUD と文字クライアントに出る |
| `intro` | system prompt の冒頭（誰として話すか）。後ろに共通ルールの `persona.txt` が続く |
| `voice.speaker` | VOICEVOX の話者 ID（`/speakers` で一覧） |
| `voice.speed` | 話速（`speedScale`）。1.0 は会話には遅く感じた。上げすぎると vaio では短い塊の合成が再生に追いつかない |
| `voice.pitch` | 音高（`pitchScale`）。0 で話者そのまま、±0.15 程度まで |
| `voice.intonation` | 抑揚（`intonationScale`）。1.0 で話者そのまま |

## 聞き取り（`--listen` / `--audio-in`）

Silero VAD で発話区間を切り出し、ReazonSpeech k2-v2（int8・2 threads）で認識する（`listen.py`）。`listen.py` 単体でも動く（`./agent/core/listen.py [WAV ...]`。認識結果を 1 行ずつ出すだけで Claude は呼ばない）。

- モデルは `~/.cache/saru9000/models/` に置く。初回の起動で自動取得する（約 160MB。あれば落とさない。取得途中の `.part` は完成扱いにしない）
- 前提: `pw-record`（PipeWire）とマイク。`--audio-in` / `listen.py WAV` に渡す wav は 16kHz・mono・16bit のみ（それ以外は形式を示してエラーにする）
- ファイルの終わりは発話の終わりとして扱う（複数渡しても 1 本ずつ別の発話になる）
- 割り込み（barge-in）と wake word は無い
- 発話の終わりとみなす無音は `listen.py` の `VAD_MIN_SILENCE`（0.6s）。短いと息継ぎや読点で 1 文が割れ、長いと saru が答え始めるまでの待ちが増える
- VAD が区間の始まりと判定するのは声が出てから約 0.3s 後なので、区間の直前 0.4s の音声（`PREROLL_SECONDS`）を頭に足してから、前後に 0.3s のゼロを足して認識する（足さないと「電気を消して」が「向きを消して」になった）
- 認識結果が空の区間（雑音だけ）は捨てる

テスト用の wav は VOICEVOX で作れる（`outputSamplingRate` を 16000 にするのが要点）:

```
q=$(curl -s -X POST --get --data-urlencode "text=電気を消して" "http://127.0.0.1:50021/audio_query?speaker=3")
echo "$q" | jq '.outputSamplingRate = 16000' \
  | curl -s -X POST -H "Content-Type: application/json" -d @- "http://127.0.0.1:50021/synthesis?speaker=3" -o denki.wav
./agent/core/listen.py denki.wav
```

server での動き:


- 認識した文は `text_input` と同じ経路で応答する。その前に `utterance`（`who=user`）を全員へ送る
- 聞き取り中で応答していない間の `state` は `listening`。`--listen` も `--audio-in` も無いときは今までどおり `idle`
- 半二重: 文を認識した時点で聞き取りを止め、その応答の最後の `speak_ended`（timeout を含む）を受けたら再開する。stage が無い（文字だけで応答した）ときは応答の完了で再開する。止めている間のマイク音声は VAD に渡さずに捨てる（saru の声を拾わないため）。`text_input` で始まった応答の間も同じく止める
- `--audio-in` は stage が `ready` を送ってくるまで待ってから流す（stage が無いと文字だけの応答になるため）。wav は実時間を待たずに流し、1 本ずつ応答の完了を待つ。流し終えたら聞き取りを止めて `idle` に戻り、server は動き続ける
- `--listen` と `--audio-in` は同時に指定できない
- マイクが使えない・wav が読めないときは、ログにエラーを出して聞き取りだけ止める（server は止めない）

## メッセージ

仕様は #18 の表を正とする。`/ws?role=stage|viewer`（省略・不明な role は `viewer`）に JSON のテキストフレームで送る。

| 方向 | type | 今の実装 |
|---|---|---|
| core → 全員 | `state` | 接続直後に現在値、以降は `listening` / `thinking` / `speaking` / `idle` の遷移 |
| core → 全員 | `utterance` | `who=agent` を塊ごとに（`name` にキャラクターの表示名）。`who=user` は聞き取りで認識した文（`text_input` では送らない） |
| core → stage | `speak` | `id`（プロセス内で増える整数）, `text`, `wav`（base64）, `visemes`。表情タグの直後の塊だけ `expression` |
| core → stage | `expression` | 応答の最後の `speak_ended`（か timeout）の後に `neutral`。読み上げられない塊にタグが付いていたときもこれで送る |
| stage → core | `speak_started` / `speak_ended` | `speak_ended` だけ使う |
| stage → core | `ready` | `--audio-in` を流し始める合図。他は検証して受けるだけ |
| core → stage | `motion` | `name=dance`。`dance` ツールが呼ばれた応答の、最後の `speak_ended` の後 |
| stage → core | `motion_ended` | `motion` の終わり。届くまで応答は終わらない |
| client → core | `text_input` | 使う |

未知の type・欠けた／型の違うフィールド・JSON でないフレームは、ログに警告を出して捨てる。

### speak の進め方

- 応答は `。！？!?` と改行（最初の塊だけ `、` も）で区切り、1 塊ずつ `speak` を送る。次の塊は、前の塊の `speak_ended` が届くか、wav の長さ＋2 秒が過ぎてから送る。stage が 1 つの音声を順に鳴らす前提に揃え、落ちた stage で固まらないよう timeout を塊ごとに持つため。合成は送信中に次の塊を先回りして行う
- 音を鳴らすのは `role=stage` の接続だけ。複数あれば最後に接続した 1 本。応答の開始時に stage が無ければ合成せず、`utterance` だけを送る
- VOICEVOX が失敗したら、その応答の残りは読み上げを諦める。`utterance` は送り続ける
- 応答中（`state` が `idle` / `listening` 以外）に来た `text_input` は捨てる

### 表情タグ

応答文の `[happy]` `[sad]` `[angry]` `[surprised]` `[relaxed]` `[neutral]` は、区切る前に抜き出して読み上げない。見つけた表情は、その後に始まる塊の `speak.expression` に載せる。ツール呼び出しを挟むと 1 往復遅れるため、文中のタグにした。

- 断片の境目で割れたタグも拾えるよう、`[` から最大 12 文字（括弧込み）は送らずに持つ
- 6 つ以外の名前、英小文字以外を含むもの、12 文字を超えるものはタグではなく文字として流す（括弧は読み上げ前の掃除で消える）

### ツール

`tools.py` の登録表（1 ツール = 名前・説明・入力 schema・async handler）が saru の使えるツールのすべて。brain の種類は知らない。`ClaudeBrain` はこれを in-process の MCP サーバ（`saru`）にして渡し、`allowed_tools` もこの表から作る（`mcp__saru__<name>`）。組み込みツール（Bash など）は `tools=[]` で無効のまま。

今あるのは `dance` だけ。

- handler は踊りを予約するだけで、すぐ返る。踊りはその応答の読み上げが全部終わってから（最後の `speak_ended` か timeout の後）、stage へ `motion {name: "dance"}` を送って始める
- `motion_ended` が届くまで `state` は `speaking` のまま、聞き取りも止めたまま。届かなければ 180 秒で諦める
- stage が無いときは踊らず、そのことを Claude に返す

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

## 頭脳（Claude）

### 会話ログ

1 往復ごとに `private/chat-logs/YYYY-MM-DD.jsonl` へ追記する（発話・応答・モデル・所要時間・usage）。`private/` は gitignore 済み。

### Claude Code から切り離しているもの

`tools=[]` と `setting_sources=[]` だけでは、claude.ai のコネクタ（Gmail・Slack 等、約 64K トークン）と起動ディレクトリの auto memory が毎ターン入る。`ENABLE_CLAUDEAI_MCP_SERVERS=false`・`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`・`strict_mcp_config` で止めており、1 往復目の入力は 800 トークン程度。

### 料金

API の従量課金は使わない（起動時に `ANTHROPIC_API_KEY` を外す）。Claude Code と同じサブスクの使用量枠を消費する。

### ペルソナ

`persona.txt` は全キャラクター共通のルール（短く答える・表情タグ・ダンス）。誰として話すかは `characters/<名前>.json` の `intro` で、選ぶのは `config.json` / `config.local.json` の `character`。凍結した MMDAgent-EX 用の `agent/bridge/persona.txt` とは共用しない。

## 手動確認

文字で話すだけなら `agent/console/client.py` を使う（`agent/console/README.md`）。メッセージを直接見るなら:


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

aiohttp・claude-agent-sdk・sherpa-onnx・numpy が無くても通るよう、`session.py` / `protocol.py` / `speech.py` / `brain.py` / `listen.py`（モジュール先頭）は標準ライブラリだけを import する。aiohttp は `server.py` だけ、Claude SDK は `ClaudeBrain` の中だけ。
