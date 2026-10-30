# agent/voice-front

Claude Code の音声入力（スペース長押し）を、core（`agent/core`）への入力にする。ここで起動した Claude Code は、送った文を core に渡して返事を表示するだけで、自分では答えない。core には文字入力として届くので、wake word は要らない。

## 起動

前提は `jq`・`uv`・`curl`。

```
./agent/voice-front/start.sh              # core を http://127.0.0.1:8765 で
PORT=8799 ./agent/voice-front/start.sh    # 別ポートで
```

core が動いていなければ起動し（ログは `~/.cache/saru9000/core-<port>.log`）、stage をブラウザで開いて、このディレクトリで `claude` を起動する。`claude` を抜けると、自分で起動した core だけ止める。stage は1回クリックしないと音が出ない。

スペースを長押しして話し、離すと送られる。返事は Claude Code の画面に出て、声と動きは stage に出る。踊りのあいだは返事が踊り終わるまで返らない。
