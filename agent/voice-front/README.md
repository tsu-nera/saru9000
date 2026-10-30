# agent/voice-front

Claude Code の音声入力（スペース長押し）を、core（`agent/core`）への入力にする。ここで起動した Claude Code は、送った文を core に渡して返事を表示するだけで、自分では答えない。core には文字入力として届くので、wake word は要らない。

## 起動

前提は `jq`・`uv` と、動いている core と stage（ブラウザ）。

```
cd agent/voice-front && claude                                          # このマシンの core（http://127.0.0.1:8765）
cd agent/voice-front && CORE_URL=http://127.0.0.1:8799 claude           # 別ポートの core
```

スペースを長押しして話し、離すと送られる。返事は Claude Code の画面に出て、声と動きは stage に出る。踊りのあいだは返事が踊り終わるまで返らない。
