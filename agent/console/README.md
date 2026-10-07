# agent/console

コンソールで saru9000 のエージェント（saru）と会話する。グラフィック（`agent/web`）より先に頭脳を固めるための入口。

## 前提

- `claude` にログイン済み（サブスク）
- `uv` がある

## 起動

```
./agent/console/chat.py                 # sonnet
./agent/console/chat.py --model opus    # モデルを変える場合
./agent/console/chat.py --listen        # キーボードの代わりにマイクで話しかける
```

既定は `sonnet`（会話の応答速度を優先）。ユーザーの `settings.json` は読まないので、そこのモデル設定は効かない。
終了は Ctrl-D か Ctrl-C。応答の後ろに所要時間・モデル・入出力トークン数を出す。

## 読み上げ（`--speak`）

```
VOICEVOX_URL=http://<vaio の tailnet アドレス>:50021 ./agent/console/chat.py --speak
```

応答を VOICEVOX Engine で合成し、`pw-play` で再生する。前提:

- VOICEVOX Engine が動いていること（vaio の `home/compose.yaml`）
- `pw-play`（PipeWire）があること

| 環境変数 | 既定 | 内容 |
|---|---|---|
| `VOICEVOX_URL` | `http://127.0.0.1:50021` | VOICEVOX Engine の URL。mouse からは vaio の tailnet アドレスを指定する |
| `VOICEVOX_SPEAKER` | `3` | 話者 ID（未決定。決まったら既定値を差し替える） |
| `VOICEVOX_SPEED` | `1.2` | 話速（VOICEVOX の `speedScale`）。上げすぎると vaio では短い塊の合成が再生に追いつかず途切れる |

読み上げ（`speech.py`）・頭脳（`brain.py`）・ペルソナは `agent/core` にある（saru-core と共用。chat.py は起動時に `sys.path` へ足して読む）。

応答は `。！？!?` と改行で区切って 1 塊ずつ合成し、再生中に次の塊を合成する。最初の塊だけは `、` でも区切り、喋り出しを早める。記号・絵文字・URL・Markdown 記法は読まない。
再生が終わってから次の `you>` を出す。VOICEVOX に繋がらない・再生に失敗した場合はその応答の読み上げだけ諦めて 1 行表示し、会話は続ける。再生中の Ctrl-C で再生を止めて終了する。

## 聞き取り（`--listen`）

```
./agent/console/chat.py --listen --speak                      # マイクで話しかけ、声で返事をもらう
./agent/console/chat.py --listen --audio-in a.wav --audio-in b.wav   # マイクの代わりに wav を順に流す
./agent/core/listen.py [WAV ...]                              # 認識結果を 1 行ずつ出すだけ（Claude は呼ばない）
```

Silero VAD で発話区間を切り出し、ReazonSpeech k2-v2（int8・2 threads）で認識する。認識は chat.py のプロセス内で行う。話し終わって `you> <認識結果>` が出たら、そのまま `answer()` に渡す。

- モデルは `~/.cache/saru9000/models/` に置く。初回の起動で自動取得する（約 160MB。あれば落とさない。取得途中の `.part` は完成扱いにしない）
- 前提: `pw-record`（PipeWire）とマイク。`--audio-in` / `listen.py WAV` に渡す wav は 16kHz・mono・16bit のみ（それ以外は形式を示してエラーにする）
- wav は実時間を待たずに流す。ファイルの終わりは発話の終わりとして扱う（複数渡しても 1 本ずつ別の発話になる）。`--audio-in` は全部流し終えたら終了する
- 半二重: saru が考えている・喋っている間のマイク入力は捨てる（自分の声を拾わないため）。割り込み（barge-in）と wake word は無い
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

## 会話ログ

1 往復ごとに `private/chat-logs/YYYY-MM-DD.jsonl` へ追記する（発話・応答・モデル・所要時間・usage）。`private/` は gitignore 済み。

## Claude Code から切り離しているもの

`tools=[]` と `setting_sources=[]` だけでは、claude.ai のコネクタ（Gmail・Slack 等、約 64K トークン）と起動ディレクトリの auto memory が毎ターン入る。`ENABLE_CLAUDEAI_MCP_SERVERS=false`・`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`・`strict_mcp_config` で止めており、1 往復目の入力は 800 トークン程度。

## 料金

API の従量課金は使わない（起動時に `ANTHROPIC_API_KEY` を外す）。Claude Code と同じサブスクの使用量枠を消費する。SDK が返す `total_cost_usd` は換算値で請求額ではないため表示していない。

## ペルソナ

`agent/core/persona.txt`（saru-core と共用）。キャラクター名は「サル」。凍結した MMDAgent-EX 用の `agent/bridge/persona.txt`（ミク）とは分けている。
