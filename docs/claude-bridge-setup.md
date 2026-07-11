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
- 展開後、`jconf_dnn_ja.txt` 等が `Release/AppData/Julius/` 配下に置かれていることを確認する

```bash
unzip Julius_Models_20231015.zip -d Release/AppData/Julius/
ls Release/AppData/Julius/ | grep jconf_dnn_ja.txt
```

---

## 3. example/main.mdf への設定追記

`example/main.mdf` は git 管理外の example リポジトリ側（`docs/mmdagent-ex-cachyos-build.md` の手順で clone したもの）。以下を追記する。

```
Plugin_Julius_lang=ja
Plugin_Julius_conf=dnn
Plugin_AnyScript_Command=python3 -u /home/tsu-nera/repo/mikumiku/miku/bridge/claude_bridge.py
```

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

---

## ハマりどころ

- **`ANTHROPIC_API_KEY` が環境にあるとブリッジが自分で除去する**。サブスク認証を強制し従量課金を防ぐための挙動であり、意図的な仕様。API キーを渡しても `claude -p` には渡らない。
- **Python の `-u` 必須**。`Plugin_AnyScript_Command` の起動コマンドに `-u` を付け忘れると、stdout がパイプに対してバッファリングされ、MMDAgent-EX 側に発話メッセージが届かず「無応答」に見える。
- **エコーによる自問自答ループに注意**。スピーカーの出力音声をマイクが拾うと、キャラクターの発話がそのまま次の認識入力になり、延々と会話し続けてしまうことがある。ヘッドホンの使用を推奨する。
- **`claude -p` は起動のたびにプロセスを立ち上げるため応答まで数秒かかる**。タイムアウトは `CLAUDE_TIMEOUT_SEC`（60 秒）で打ち切り、失敗時はフォールバック発話（「ごめんなさい、うまく考えられませんでした」）で継続する。
