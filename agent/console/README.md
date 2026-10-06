# agent/console

コンソールで saru9000 のエージェント（ミク）と会話する。グラフィック（`agent/web`）より先に頭脳を固めるための入口。

## 前提

- `claude` にログイン済み（サブスク）
- `uv` がある

## 起動

```
./agent/console/chat.py
./agent/console/chat.py --model sonnet   # モデルを指定する場合
```

終了は Ctrl-D。

## 料金

API の従量課金は使わない（起動時に `ANTHROPIC_API_KEY` を外す）。Claude Code と同じサブスクの使用量枠を消費する。SDK が返す `total_cost_usd` は換算値で請求額ではないため表示していない。

## ペルソナ

`agent/bridge/persona.txt` を共用する。
