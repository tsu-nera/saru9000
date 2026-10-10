# agent/core

vaio に常駐するサーバで、頭脳（Claude）・読み上げ（VOICEVOX か Open JTalk）・状態を持ち、stage（ブラウザ）と文字クライアントを WebSocket で繋ぐ。全体の設計と最終形は #18、この実装範囲は #20。

今の範囲は「文字か声で話しかけると、塊ごとの `speak`（wav＋母音タイムライン）が stage に届く」まで。聞き取りは #23。表情は応答文のタグで変える（#24）。「踊って」で踊る（#25）。

## 前提

- `claude` にログイン済み（サブスク。起動時に `ANTHROPIC_API_KEY` は外す）
- `uv` がある
- キャラクターの声のエンジン（`voice.engine`）が使えること。使えない場合は文字だけで応答する
  - `voicevox`（サル）: VOICEVOX Engine が動いていること（vaio の `home/compose.yaml`）
  - `openjtalk`（ミク）: `open_jtalk`・辞書・音響モデルがあること（下の「Open JTalk」）

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
| `listen_mode` | 聞き取った文への応じ方。`wake`（呼びかけ。既定）か `always`（常時）。それ以外は起動時にエラー。詳しくは「聞き取り」 |
| `voicevox_url` | VOICEVOX Engine の URL |
| `open_jtalk.bin` | `open_jtalk` の実行ファイル。`~` は展開する。既定は vaio の `~/.local/opt/open_jtalk/bin/open_jtalk` |
| `open_jtalk.dic` | Open JTalk の辞書のディレクトリ。既定は `~/.local/opt/open_jtalk/open_jtalk_dic_utf_8-1.11` |
| `voice` | キャラクターの声の上書き（キーは下の `voice` と同じ）。声だけ試したいときに使う |

例: vaio でミクにして、声を半音 1 つ高くする

```json
{"character": "miku", "voice": {"pitch": 1.0}}
```

`characters/<名前>.json` はキャラクターごとの名乗りと声:

| キー | 内容 |
|---|---|
| `name` | 表示名。stage の HUD と文字クライアントに出る |
| `intro` | system prompt の冒頭（誰として話すか）。後ろに共通ルールの `persona.txt` が続く |
| `wake_words` | 呼びかけの語のリスト（必須）。`wake` モードで、聞き取った文にこのどれかが含まれると応答する。漢字の揺れ（猿）はここに並べて吸収する |
| `voice.engine` | 合成エンジン。`voicevox`（サル）か `openjtalk`（ミク）。それ以外は選択肢を示して起動を止める |

`voice` の残りのキーの意味はエンジンごとに違う。

`voicevox`:

| キー | 内容 |
|---|---|
| `voice.speaker` | VOICEVOX の話者 ID（`/speakers` で一覧） |
| `voice.speed` | 話速（`speedScale`）。1.0 は会話には遅く感じた。上げすぎると vaio では短い塊の合成が再生に追いつかない |
| `voice.pitch` | 音高（`pitchScale`）。0 で話者そのまま、±0.15 程度まで |
| `voice.intonation` | 抑揚（`intonationScale`）。1.0 で話者そのまま |

`openjtalk`:

| キー | 内容 |
|---|---|
| `voice.htsvoice` | 音響モデル（`.htsvoice`）のパス。`~` は展開する |
| `voice.speed` | 話速（`-r`）。1.0 でモデルそのまま |
| `voice.pitch` | 音高（`-fm`、半音単位の加算）。0 でモデルそのまま |
| `voice.intonation` | 抑揚（`-jf`、対数 F0 の GV の重み）。1.0 でモデルそのまま |

### Open JTalk

`open_jtalk` を塊ごとに subprocess で起動し（本文は stdin）、wav とトレース（`-ot`）を一時ディレクトリに書かせて読む。同じ文（約 6 秒分）の合成は vaio で 0.65 秒（VOICEVOX は 4.57 秒）。起動失敗・異常終了・30 秒を超えたときは VOICEVOX の失敗と同じく、その応答の残りを文字だけにする。

ビルド（vaio で試作したときの手順。`$P=$HOME/.local/opt/open_jtalk`）:

1. hts_engine API 1.10: `./configure --prefix=$P && make && make install`
2. Open JTalk 1.11: `CFLAGS="-O2 -std=gnu11" CXXFLAGS="-O2 -std=gnu++14" ./configure --prefix=$P --with-hts-engine-header-path=$P/include --with-hts-engine-library-path=$P/lib --with-charset=UTF-8 && make && make install`
   - `make -j` は使わない（辞書の作成でファイルのコピーがぶつかって失敗した）
   - GCC 15 以降は C23 が既定で古いコードが通らないため `-std=gnu11`
3. 辞書 `open_jtalk_dic_utf_8-1.11.tar.gz` を `$P/` に展開する

音響モデル: ミクの声は CUBE370 氏「MMDAgent用自作音響モデル TYPE-β」（2011 年）。readme に「本ソフトはフリーソフトです。自由にご使用ください。なお，著作権は作者であるCUBE370が保有しています。」とある。配布物は旧形式（`*.pdf` / `*.inf`）なので `.htsvoice` への変換が要る。vaio で変換済みの `~/.cache/saru9000/voices/naip_type_b.htsvoice`（48 kHz、`FRAME_PERIOD:240`）を使う。モデルも変換ツールも repo には入れない（あにまさ式ミクのモデルと同じ扱い）。

## 聞き取り（`--listen` / `--audio-in`）

Silero VAD で発話区間を切り出し、ReazonSpeech k2-v2（int8・2 threads）で認識する（`listen.py`）。`listen.py` 単体でも動く（`./agent/core/listen.py [WAV ...]`。認識結果を 1 行ずつ出すだけで Claude は呼ばない）。

- モデルは `~/.cache/saru9000/models/` に置く。初回の起動で自動取得する（約 160MB。あれば落とさない。取得途中の `.part` は完成扱いにしない）
- 前提: `pw-record`（PipeWire）とマイク。`--audio-in` / `listen.py WAV` に渡す wav は 16kHz・mono・16bit のみ（それ以外は形式を示してエラーにする）
- ファイルの終わりは発話の終わりとして扱う（複数渡しても 1 本ずつ別の発話になる）
- 割り込み（barge-in）は無い
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

### 呼びかけモード（`listen_mode`）

聞き取った文にどう応じるかを 2 つから選ぶ。`config.json` の `listen_mode` が起動時の値で、既定は `wake`。

- `wake`: キャラクターの `wake_words` を含む文にだけ応答する。含まない文はログ（info）に出して捨て、Claude にも渡さず `utterance` も送らない。捨てた文では応答が始まらないので、聞き取りは止まらずに続く
- `always`: 認識した文すべてに応答する

`wake` の判定は ReazonSpeech の認識文への文字列照合で、音響モデルは足していない。認識文と wake word のひらがなをカタカナに揃えてから部分一致で見る（「みくちゃんおはよう」も「ねえミク」「初音ミク」も通る）。位置は問わず、wake word は取り除かずに Claude へ渡す。呼びかけの後に wake word なしで続けて話せる窓は作らない（応答の直後に雑音の認識結果が続いて応答が連鎖するため）。

`text_input` はどちらのモードでも応答する（打った文は呼びかけの対象ではないため）。

実行中は `listen_mode` メッセージで切り替えられる（stage の HUD のボタン、console の `/mode`）。切り替えは `Session` の値を変えるだけで、`config.local.json` には書かない。server を起動し直すと設定の値に戻る。進行中の応答には影響せず、次に聞き取った文から効く。

server での動き:

- 認識した文は（`wake` モードでは wake word を含むものだけ）`text_input` と同じ経路で応答する。その前に `utterance`（`who=user`）を全員へ送る
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
| core → 全員 | `listen_mode` | `mode`（`wake` / `always`）。接続直後に `state` の次に現在値、以降は切り替えるたびに全員へ |
| core → 全員 | `utterance` | `who=agent` を塊ごとに（`name` にキャラクターの表示名）。`who=user` は聞き取りで認識した文（`text_input` では送らない） |
| core → stage | `speak` | `id`（プロセス内で増える整数）, `text`, `wav`（base64）, `visemes`。表情タグの直後の塊だけ `expression` |
| core → stage | `expression` | 応答の最後の `speak_ended`（か timeout）の後に `neutral`。読み上げられない塊にタグが付いていたときもこれで送る |
| stage → core | `speak_started` / `speak_ended` | `speak_ended` だけ使う |
| stage → core | `ready` | `--audio-in` を流し始める合図。他は検証して受けるだけ |
| core → stage | `motion` | `name=dance`。`dance` ツールが呼ばれた応答の、最後の `speak_ended` の後 |
| stage → core | `motion_ended` | `motion` の終わり。届くまで応答は終わらない |
| client → core | `text_input` | 使う |
| client → core | `listen_mode` | `mode` に切り替える。`wake` / `always` 以外はログに警告を出して捨てる |

未知の type・欠けた／型の違うフィールド・JSON でないフレームは、ログに警告を出して捨てる。

### speak の進め方

- 応答は `。！？!?` と改行（最初の塊だけ `、` も）で区切り、1 塊ずつ `speak` を送る。次の塊は、前の塊の `speak_ended` が届くか、wav の長さ＋2 秒が過ぎてから送る。stage が 1 つの音声を順に鳴らす前提に揃え、落ちた stage で固まらないよう timeout を塊ごとに持つため。合成は送信中に次の塊を先回りして行う
- 音を鳴らすのは `role=stage` の接続だけ。複数あれば最後に接続した 1 本。応答の開始時に stage が無ければ合成せず、`utterance` だけを送る
- 合成（VOICEVOX / Open JTalk）が失敗したら、その応答の残りは読み上げを諦める。`utterance` は送り続ける
- 応答中（`state` が `idle` / `listening` 以外）に来た `text_input` は捨てる

### 表情タグ

応答文の `[happy]` `[sad]` `[angry]` `[surprised]` `[relaxed]` `[neutral]` は、区切る前に抜き出して読み上げない。見つけた表情は、その後に始まる塊の `speak.expression` に載せる。ツール呼び出しを挟むと 1 往復遅れるため、文中のタグにした。

- 断片の境目で割れたタグも拾えるよう、`[` から最大 12 文字（括弧込み）は送らずに持つ
- 6 つ以外の名前、英小文字以外を含むもの、12 文字を超えるものはタグではなく文字として流す（括弧は読み上げ前の掃除で消える）

### ツール

`tools.py` の登録表（1 ツール = 名前・説明・入力 schema・async handler）が saru の使えるツールのすべて。brain の種類は知らない。`ClaudeBrain` はこれを in-process の MCP サーバ（`core`）にして渡し、`allowed_tools` もこの表から作る（`mcp__core__<name>`）。組み込みツール（Bash など）は `tools=[]` で無効のまま。

今あるのは `dance` と `weather`。

`weather`（入力なし）は家の天気を HA から読み、1 回で全部を JSON テキストで返す（音声で待たせないため、引数で絞らせない）。

- 中身: 現在の日時、Yahoo の雨雲 sensor 3 つ（`home/packages/rain.yaml`）の state、met.no（`weather.forecast_zi_zhai`）の hourly と daily。予報の時刻は JST に直し、使う項目だけ残す
- `weather.get_forecasts` は `POST /api/services/weather/get_forecasts?return_response`。`?return_response` が無いと 400。`twice_daily` は met.no では 500
- 落とし穴: met.no の daily の `condition` に夜の値の `clear-night` が入るので、daily だけ `sunny` に置き換える
- HA が失敗したら例外を投げず「天気を取得できませんでした。」を返す
- weather entity は Assist に公開しない（公開すると HA 標準の intent が「現在の天気」だけ答えて Claude に届かない）

`dance`:

- handler は踊りを予約するだけで、すぐ返る。踊りはその応答の読み上げが全部終わってから（最後の `speak_ended` か timeout の後）、stage へ `motion {name: "dance"}` を送って始める
- `motion_ended` が届くまで `state` は `speaking` のまま、聞き取りも止めたまま。届かなければ 180 秒で諦める
- stage が無いときは踊らず、そのことを Claude に返す

### visemes

`speak.visemes` は `[{"t": 開始秒, "v": 母音}]`。`t` は wav 先頭からの秒で、`v` は `a i u e o closed`。

- 母音 `a i u e o`（無声化の `A I U E O` も同じ）はそのまま小文字
- 子音 `m b p my by py` の区間は `closed`。他の子音の区間は続く母音と同じ
- `N`・`cl`・pause・前後の無音は `closed`
- 同じ `v` が続く区間はまとめる（長さ 0 の区間は先に捨てる）

母音タイムラインはエンジンの中で作り、`Synthesis.visemes` として session に渡す。session はエンジンの種類を知らない。

Open JTalk はトレース（`-ot`）の `[Output label]` 節から作る。1 行 1 音素で `開始 終了 フルコンテキストラベル`、時刻は 100 ns 単位。音素名はラベルの `-` と `+` の間（例: `2500000 3350000 k^o-N+n=i/A:...` は 0.25〜0.335 秒が `N`）。最後のラベルの終了時刻と wav の長さの差は、実機テストで確かめる（`open_jtalk`・辞書・`naip_type_b.htsvoice` が無ければ skip）。

VOICEVOX は Engine と同じ手順で区間をフレーム（24000/256 = 93.75 fps）に丸めて並べる（音素ごとに `round(秒 / speedScale * 93.75)`）。秒のまま足すと誤差が溜まって wav の長さとずれる。pause は `pauseLength`（あれば）→ `pauseLengthScale` の順に反映する。

wav の長さとの差は、VOICEVOX 実機に対するテストで確かめる（VOICEVOX に繋がらなければ skip）:

```
uv run --with pytest pytest agent/core -v -s
```

## 頭脳（Claude）

### 会話ログ

1 往復ごとに `private/chat-logs/YYYY-MM-DD.jsonl` へ追記する（発話・応答・モデル・所要時間・usage）。`private/` は gitignore 済み。

Claude に送る文の頭には現在の日時（JST・曜日つき、例 `[2026-10-10(土) 15:04]`）を付ける。system prompt に時計が無く、「明日の火曜」のような食い違いを解けないため。会話ログの `user` と HA に渡す文には付けない。

### Home Assistant を先に試す

聞き取り・`text_input` の文から wake word と句読点を除き、HA の `/api/conversation/process`（`language: ja`、`agent_id: conversation.home_assistant`）に渡す。一致すれば HA の返事だけを読み上げ、Claude は呼ばない。会話ログには `model: home-assistant` で残る。

- 一致しない（`response_type: error`、`no_intent_match` を含む）・接続失敗・タイムアウト（10 秒）の時は警告を出して Claude へ回す。Claude には wake word 付きの元の文を渡す
- 受ける文とその返事は `home/packages/voice_commands.yaml` に書く。core は文言を持たない
- HA の URL・トークンは `home/ha.py` が読む（`home/config.json` と `.env` の `HA_TOKEN`）
- 落とし穴: HA に一致しない文でも、Claude の前に HA への往復が毎回 1 回入る
- 落とし穴: HA の標準の言い回し（intent）も一致する。Assist に機器を公開すると「電気消して」などで HA が機器を直接動かし Claude に届かないので、公開はすべて外し、新しい機器の自動公開も切ってある（設定 → 音声アシスタント → 公開）。機器を伴わない「今何時」などは HA が答える

### Claude Code から切り離しているもの

`tools=[]` と `setting_sources=[]` だけでは、claude.ai のコネクタ（Gmail・Slack 等、約 64K トークン）と起動ディレクトリの auto memory が毎ターン入る。`ENABLE_CLAUDEAI_MCP_SERVERS=false`・`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`・`strict_mcp_config` で止めており、1 往復目の入力は 800 トークン程度。

### 料金

API の従量課金は使わない（起動時に `ANTHROPIC_API_KEY` を外す）。Claude Code と同じサブスクの使用量枠を消費する。

### ペルソナ

`persona.txt` は全キャラクター共通のルール（短く答える・表情タグ・ダンス・天気）。誰として話すかは `characters/<名前>.json` の `intro` で、選ぶのは `config.json` / `config.local.json` の `character`。凍結した MMDAgent-EX 用の `agent/bridge/persona.txt` とは共用しない。

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

aiohttp・claude-agent-sdk・sherpa-onnx・numpy が無くても通るよう、`session.py` / `protocol.py` / `speech.py` / `brain.py` / `listen.py`（モジュール先頭）/ `home.py`（モジュール先頭）は標準ライブラリだけを import する。`home/ha.py` は呼ぶ時に import する。aiohttp は `server.py` だけ、Claude SDK は `ClaudeBrain` の中だけ。
