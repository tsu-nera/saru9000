# agent/console

core（`agent/core`）に繋いで、saru と文字で話すクライアント。声を出せない場所（コワーキング等）から、tailnet 越しに vaio の core と話して開発するための入口。

client は Claude も VOICEVOX も知らない。core の `/ws?role=viewer` に `text_input` を送り、返ってくる `utterance`（`who=saru`）を表示するだけで、音も鳴らさない（鳴らすのは stage）。

## 前提

- `uv` がある
- core が動いていること（`./agent/core/server.py`、`agent/core/README.md`）

## 起動

```
./agent/console/client.py                                         # このマシンの core（http://127.0.0.1:8765）
CORE_URL=http://<vaio の tailnet アドレス>:8765 ./agent/console/client.py   # vaio の core
```

| 環境変数 | 既定 | 内容 |
|---|---|---|
| `CORE_URL` | `http://127.0.0.1:8765` | core の URL |

`you> ` に 1 行打つと送り、`<キャラ名>> `（例: `サル> `）に続けて応答を塊ごとに表示する。core の `state` が `thinking` / `speaking` 以外に戻ったら次の `you> ` を出す。終了は Ctrl-D か Ctrl-C。

core に繋がらないときは URL を 1 行表示して終了する（終了コード 1）。途中で core が切断したときも 1 行表示して終了する。

core が聞き取り（`--listen`）をしていると、声で話しかけた応答も `<キャラ名>> ` の行に流れてくる。

### 聞き取りの呼びかけモード

`/mode wake`（呼びかけにだけ応答）か `/mode always`（全部に応答）を打つと、`text_input` ではなく `listen_mode` を送る。応答の turn は始まらないので、core の `listen_mode` を `[mode: wake]` の 1 行で表示してから次の `you> ` を出す。`/mode` の後が `wake` / `always` 以外なら、使い方を表示するだけで何も送らない。接続直後と、他の client（stage の HUD など）が切り替えたときも同じ 1 行が出る。`text_input` は `wake` モードでも応答する。

## 以前の console から移ったもの

頭脳・読み上げ・聞き取りは core に移り、console にあった会話スクリプトは削除した。

| 以前 | 今 |
|---|---|
| `--model` | `server.py --model`（`agent/core/README.md`） |
| `--speak` | core が VOICEVOX で合成し、stage（`agent/web`）が鳴らす |
| `--listen` / `--audio-in` | `server.py --listen` / `--audio-in` |
| 会話ログ・ペルソナ・料金 | `agent/core/README.md` の「頭脳（Claude）」 |

## テスト

```
uv run --with pytest --with aiohttp pytest agent/console agent/core
```

fake の core（aiohttp の test server）に繋いで確かめる。
