# agent/console

core（`agent/core`）に繋いで、文字で話すクライアント。声を出せない場所（コワーキング等）から、tailnet 越しに vaio の core と話して開発するための入口。音は鳴らさない（鳴らすのは stage）。

## 起動

前提は `uv` と、動いている core。

```
./agent/console/client.py                                                  # このマシンの core（http://127.0.0.1:8765）
CORE_URL=http://<vaio の tailnet アドレス>:8765 ./agent/console/client.py   # vaio の core
```

`you> ` に 1 行打つと送り、応答を `サル> ` などの行に表示する。core が聞き取りをしていれば、声への応答もここに流れる。`/mode wake`（呼びかけにだけ応答）・`/mode always`（全部に応答）で core の聞き取りの応じ方を切り替える。終了は Ctrl-D。

## テスト

```
uv run --with pytest --with aiohttp pytest agent/console agent/core
```
