# agent/console

コンソールで saru9000 のエージェント（saru）と会話する。グラフィック（`agent/web`）より先に頭脳を固めるための入口。

## 前提

- `claude` にログイン済み（サブスク）
- `uv` がある

## 起動

```
./agent/console/chat.py                 # sonnet
./agent/console/chat.py --model opus    # モデルを変える場合
```

既定は `sonnet`（会話の応答速度を優先）。ユーザーの `settings.json` は読まないので、そこのモデル設定は効かない。応答の後ろに所要時間と実際に使われたモデル名を表示する。

終了は Ctrl-D。

## 料金

API の従量課金は使わない（起動時に `ANTHROPIC_API_KEY` を外す）。Claude Code と同じサブスクの使用量枠を消費する。SDK が返す `total_cost_usd` は換算値で請求額ではないため表示していない。

## ペルソナ

`agent/console/persona.txt`。キャラクター名は「サル」。凍結した MMDAgent-EX 用の `agent/bridge/persona.txt`（ミク）とは分けている。
