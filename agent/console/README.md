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

既定は `sonnet`（会話の応答速度を優先）。ユーザーの `settings.json` は読まないので、そこのモデル設定は効かない。
終了は Ctrl-D か Ctrl-C。応答の後ろに所要時間・モデル・入出力トークン数を出す。

## 会話ログ

1 往復ごとに `private/chat-logs/YYYY-MM-DD.jsonl` へ追記する（発話・応答・モデル・所要時間・usage）。`private/` は gitignore 済み。

## Claude Code から切り離しているもの

`tools=[]` と `setting_sources=[]` だけでは、claude.ai のコネクタ（Gmail・Slack 等、約 64K トークン）と起動ディレクトリの auto memory が毎ターン入る。`ENABLE_CLAUDEAI_MCP_SERVERS=false`・`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`・`strict_mcp_config` で止めており、1 往復目の入力は 800 トークン程度。

## 料金

API の従量課金は使わない（起動時に `ANTHROPIC_API_KEY` を外す）。Claude Code と同じサブスクの使用量枠を消費する。SDK が返す `total_cost_usd` は換算値で請求額ではないため表示していない。

## ペルソナ

`agent/console/persona.txt`。キャラクター名は「サル」。凍結した MMDAgent-EX 用の `agent/bridge/persona.txt`（ミク）とは分けている。
