# agent/core

起動・設定・セットアップは README.md。ここには作業するときの決まりと、コードからは分からない落とし穴だけを書く。

## 確かめ方

- テスト: `uv run --with pytest pytest agent/core`。VOICEVOX・Open JTalk の実機テストは繋がらなければ skip する
- 会話を通して確かめる: 別ポートで起動し（`./agent/core/server.py --host 127.0.0.1 --port 8799`）、console に行を流す（`printf '明日の予定は？\n来週は？\n' | CORE_URL=http://127.0.0.1:8799 ./agent/console/client.py`）。続けて送った行は同じ会話になる。サブスクの枠を使う。終わったら server を止める
- 聞き取りの wav は VOICEVOX で作れる。`audio_query` の `outputSamplingRate` を 16000 にしてから `synthesis` に渡し、`./agent/core/listen.py <wav>` で認識だけ見る

## 決まり

- aiohttp・claude-agent-sdk・sherpa-onnx・numpy が無くてもテストが通るよう、`server.py` 以外のモジュール先頭は標準ライブラリと兄弟モジュールだけを import する。重い依存は使う関数の中で import する
- ツールは `tools.py` の登録表が正本。いつ・どう使うかは各ツールの description に書き、`persona.txt` には書かない。踊りはツールではない（固定の言葉で、Claude を通さない）
- `persona.txt` は凍結した MMDAgent-EX 用の `agent/bridge/persona.txt` と共用しない
- 会話ログは `private/chat-logs/`（gitignore）。repo は public なので、会話や家の情報を tracked ファイルに書かない

## 落とし穴

- HA の Assist に機器や weather entity を公開しない。core は Claude の前に HA の会話 API を試すので、公開すると HA 標準の intent が答えて Claude に届かない（設定 → 音声アシスタント → 公開。新しい機器の自動公開も切ってある）
- 機器を伴わない「今何時」などは HA が答える。HA に一致しない文でも、Claude の前に HA への往復が毎回 1 回入る
- 試しに入れた予定は `python3 home/ha.py ws calendar/event/delete '{"entity_id": "…", "uid": "…"}'` で消す（uid は読んだ予定に入っている）
