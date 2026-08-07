# MMDAgent-EX の音声対話に Claude Code を接続する

MMDAgent-EX の対話エンジンに Claude を接続し、音声で会話できる 3D キャラクターを実現する。Claude Code サブスクリプションの範囲内で動かすため、Anthropic API を直叩きせず、Claude Code ヘッドレスモード（`claude -p`）をサブプロセスとして呼ぶブリッジスクリプトを Plugin_AnyScript 経由で起動する。

## メッセージフロー

```
MMDAgent-EX (Julius 音声認識)
  → RECOG_EVENT_STOP|認識テキスト  (stdin 経由でブリッジへ)
  → ブリッジスクリプト (Python) が claude -p を呼ぶ
  → SYNTH_START|モデル|声|応答テキスト  (stdout 経由で MMDAgent-EX へ)
  → Open_JTalk が音声合成して発話
```

ブリッジ本体: `miku/bridge/claude_bridge.py`
人格プロンプト: `miku/bridge/persona.txt`

---

## 1. 前提

- MMDAgent-EX がビルド済みであること（`docs/mmdagent-ex-cachyos-build.md` 参照）
- `claude` CLI がインストール・ログイン済みであること。以下で確認する:

  ```bash
  claude --version
  ```

  未ログインの場合はサブスク認証（`claude login` 相当のフロー）を先に済ませておく。ブリッジは `ANTHROPIC_API_KEY` を明示的に環境から除去して起動するため、API キー課金ではなくこのログインセッションが使われる。

---

## 2. Julius ディクテーションモデルの導入

日本語音声認識（ディクテーション）には別途モデルのダウンロードが必要。デフォルト同梱のモデルには含まれない。

- 入手元: `Julius_Models_20231015.zip`（約 791MB）
  https://drive.google.com/file/d/1d82CpinrlDmY9MgjTYa-awCdLOsz16MF/view?usp=sharing
- 展開先: `Release/AppData/Julius/`（展開後 約 1.7GB）
- 展開後、`jconf_dnn_ja.txt` 等が `Release/AppData/Julius/` 直下に置かれていることを確認する

ブラウザを開かずに `gdown` で取得できる（実測 11 分）。

```bash
uvx gdown "https://drive.google.com/uc?id=1d82CpinrlDmY9MgjTYa-awCdLOsz16MF" -O Julius_Models_20231015.zip
```

zip の中身は `Julius_Models_20231015/` に包まれている。`unzip -d Release/AppData/Julius/` と展開すると 1 階層深くなり、後述の `jconf file "jconf_dnn_ja.txt" not exist` が解消しないので、中身を 1 階層上げて配置する。

```bash
unzip -q Julius_Models_20231015.zip -d /tmp/julius
mv /tmp/julius/Julius_Models_20231015/* Release/AppData/Julius/
ls Release/AppData/Julius/jconf_dnn_ja.txt
```

---

## 3. example/main.mdf への設定追記

`example/main.mdf` は git 管理外の example リポジトリ側（`docs/mmdagent-ex-cachyos-build.md` の手順で clone したもの）。既定では 3 行ともコメントアウトされているので、有効化する。

```
Plugin_Julius_lang=ja
Plugin_Julius_conf=dnn
Plugin_AnyScript_Command=python3 -u /home/tsu-nera/repo/mikumiku/miku/bridge/claude_bridge.py
```

`example/` 配下は `.gitignore` 対象でこのリポジトリの履歴に残らない。動作する構成に必要なローカル変更は以下の 3 つ。

| ファイル | 変更 |
|---|---|
| `main.mdf` | 上記 3 行の有効化 |
| `main.fst` | 3 行目の `MODEL_ADD` を `miku/Miku.pmd` に変更（Issue #2） |
| `miku/` | 初音ミクの `Miku.pmd` + `eye2.bmp` を配置（Issue #2） |

---

## 4. 起動

```bash
./Release/MMDAgent-EX ./example/main.mdf
```

マイクに向かって話しかけ、認識テキストが確定すると Claude の応答が音声合成される。

---

## 5. ブリッジ単体のテスト

MMDAgent-EX を起動せずに、ブリッジスクリプト単体で疎通確認できる。標準入力に `RECOG_EVENT_STOP|` 形式の行を流し、標準出力に `SYNTH_START|` 行が出れば OK。

正常系（応答生成の確認、claude -p 呼び出しのため数秒〜数十秒かかる）:

```bash
printf 'RECOG_EVENT_STOP|こんにちは、聞こえてる？\n' | python3 -u miku/bridge/claude_bridge.py
```

文脈維持（2 回目の入力で 1 回目の内容を覚えているか）:

```bash
printf 'RECOG_EVENT_STOP|私の名前はツネです。覚えてね。\nRECOG_EVENT_STOP|私の名前、なんだっけ？\n' | python3 -u miku/bridge/claude_bridge.py
```

異常系（`claude` が PATH 上に無い環境でも落ちず、フォールバック発話が出ることの確認）:

```bash
printf 'RECOG_EVENT_STOP|こんにちは\n' | env PATH=/usr/bin python3 -u miku/bridge/claude_bridge.py
```

実環境相当（stdin にメッセージが流れ続ける状態での連続入力）。`printf` だけのテストは stdin がすぐ EOF になるため、後述の stdin ハングを検出できない。古い入力が捨てられ、最新の発話にだけ応答すれば OK:

```bash
{ printf 'RECOG_EVENT_STOP|こんにちは\n'; sleep 2; \
  printf 'RECOG_EVENT_STOP|今日は暑いね\n'; sleep 2; \
  printf 'RECOG_EVENT_STOP|好きな食べ物は何\n'; \
  while true; do echo 'RECOG_EVENT_OVERFLOW'; sleep 0.2; done; } \
  | timeout 45 python3 -u miku/bridge/claude_bridge.py
```

---

## マイク入力レベルの調整

ゲインが高すぎると無音でも波形がクリップし、`RECOG_EVENT_OVERFLOW` が毎秒数十件飛んで音声認識が一切成立しない（判定閾値は `Plugin_Julius/Julius_Logger.h` の `ADINOVERFLOWTHRES 32000` = int16 の上限付近）。

このマシン（ALC256）の既定値は `Mic Boost` +20dB × `Capture` 100%(+30dB) の合計 +50dB で、そのままでは認識できなかった。以下で解消する。

```bash
amixer -c 0 sset 'Mic Boost' 0
amixer -c 0 sset Capture 60%
```

起動後、ログに `RECOG_EVENT_OVERFLOW` が連続していないことを確認する。PipeWire 側の音量を絞っても overflow は止まるが、他アプリに影響しない ALSA 側での調整が本筋。

---

## ハマりどころ

- **`ANTHROPIC_API_KEY` が環境にあるとブリッジが自分で除去する**。サブスク認証を強制し従量課金を防ぐための挙動であり、意図的な仕様。API キーを渡しても `claude -p` には渡らない。
- **Python の `-u` 必須**。`Plugin_AnyScript_Command` の起動コマンドに `-u` を付け忘れると、stdout がパイプに対してバッファリングされ、MMDAgent-EX 側に発話メッセージが届かず「無応答」に見える。
- **エコーによる自問自答ループに注意**。スピーカーの出力音声をマイクが拾うと、キャラクターの発話がそのまま次の認識入力になり、延々と会話し続けてしまうことがある。ヘッドホンの使用を推奨する。
- **`claude -p` に `stdin=DEVNULL` を渡さないとハングする**。MMDAgent-EX は全メッセージ（`RECOG_EVENT_OVERFLOW` 含む）を子プロセスの stdin に流し続けるため、stdin を継承した `claude -p` は EOF を待って戻ってこない。さらにブリッジ宛ての認識行を横取りする。実測では stdin が即 EOF なら 9 秒で応答、データが流れ続けると 35 秒経っても無応答。症状は「最初の 1 回だけフォールバック発話が出て以後無反応」に見える。
- **応答に数秒かかるので入力は最新 1 件だけ保持する**。stdin を順次処理すると発話が積み上がり、数分前の発話に延々と返信し続ける。ブリッジは reader スレッドで stdin を常時読み捨てつつ最新の認識結果だけを処理する（MMDAgent-EX 側のパイプ詰まり防止も兼ねる）。
- **Julius は環境音を `。` として認識する**。句読点のみの結果を弾かないと、無音のたびに `claude -p` が起動する。ブリッジは句読点除去後 2 文字未満の入力を捨てる（「うん」のような短い実発話を殺さないための閾値）。
- **`claude -p` は起動のたびにプロセスを立ち上げるため応答まで数秒かかる**（実測 9 秒前後）。タイムアウトは `CLAUDE_TIMEOUT_SEC`（60 秒）で打ち切り、失敗時はフォールバック発話（「ごめんなさい、うまく考えられませんでした」）で継続する。
- **Plugin_AnyScript が横取りするのは stdout だけ**（Linux）。`ChildProcess.cpp` の POSIX 分岐は fd 1 のみ `dup2` する（Windows 側のコメントは stderr も含むと書いてあるが実装が異なる）。ブリッジのデバッグ出力を stderr に出してもメッセージとして誤解釈されず、MMDAgent-EX の端末に混ざって表示されるだけ。
