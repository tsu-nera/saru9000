# MMDAgent-EX を CachyOS でビルドして起動する

公式のビルド手順は Debian/Ubuntu（`apt`）前提のため、CachyOS（Arch 系）ではそのままでは通らない。実際にハマったポイントと対処をまとめる。

- 公式ビルド手順: https://mmdagent-ex.dev/docs/build/
- 公式起動手順: https://mmdagent-ex.dev/docs/run/
- リポジトリ: https://github.com/mmdagent-ex/MMDAgent-EX

環境: CachyOS (Arch 系, rolling) / GCC 16 / Wayland (niri) + pipewire。

---

## 1. 依存パッケージ（Debian 名 → Arch 名に読み替え）

`requirements-linux.txt` は Debian パッケージ名で書かれている。CachyOS では pacman 名へ読み替える。多くは標準で入っているが、追加が必要だったのは以下。

```bash
sudo pacman -S --needed poco librdkafka re2 sox librabbitmq-c
```

### ハマりどころ

- **`rabbitmq-c` ではなく `librabbitmq-c`**。名前が違う。
- **pacman は 1 つでもパッケージが見つからないとトランザクション全体を中止する**。名前ミスがあると「他は入ったつもり」で先に進めてしまうので注意。
- **`pulseaudio` は入れない**。CachyOS は既定で `pipewire` + `pipewire-pulse` が動いており、`pulseaudio` を入れると競合する。PulseAudio 互換は `pipewire-pulse` が提供するので不要。

---

## 2. ビルド（GCC 16 = C23 デフォルトの罠）

CMake 構成 → ビルド:

```bash
cmake -S. -Bbuild -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

このままだと **GCC 16** で 2 箇所エラーになる。

### 2-1. Julius（古い C コード）が C23 で落ちる

GCC 15 以降は既定が C23 になり、さらに GCC 14 以降で一部の警告がデフォルトでエラーに昇格している。そのため Julius でこうなる:

- 空の `()` が「引数なし `(void)`」扱いになり、K&R スタイルの関数ポインタ呼び出しが `too many arguments` エラー
- `incompatible-pointer-types` などがエラー扱い

C 標準を `gnu17` に固定し、該当警告をエラーから降格させて回避する:

```bash
cmake -S. -Bbuild -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_FLAGS="-std=gnu17 -Wno-error=incompatible-pointer-types -Wno-error=int-conversion -Wno-error=implicit-function-declaration -Wno-error=implicit-int"
cmake --build build -j$(nproc)
```

### 2-2. 新しい Poco で JSON ヘッダが分割された

`Plugin_RabbitMQ` が `Poco::JSON::Object` / `Poco::JSON::Array` 未宣言でビルドエラーになる。新しい Poco ではヘッダが分割されているため、include を追加する。

- `Plugin_RabbitMQ/RabbitMQ.cpp`
- `Plugin_RabbitMQ/Plugin_RabbitMQ.cpp`

の両方で、既存の `#include <Poco/JSON/Parser.h>` の下に追記:

```cpp
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Array.h>
```

ここまでで本体 + 全 13 プラグインが `Release/` 以下に生成される。`ldd Release/MMDAgent-EX` で未解決ライブラリが無いことも確認できる。

> 補足: `cmake --build` を `tee` 等のパイプ経由で回すと、シェルによっては終了コードが `tee` のものになり成功に見える。実際の成否は `Release/MMDAgent-EX` の生成有無とログの `error:` で確認するのが確実。

---

## 3. サンプルコンテンツの取得

モデル・音声などのサンプルは別リポジトリ。**submodule 込み**で取得する。

```bash
git clone --recursive https://github.com/mmdagent-ex/example
```

### ハマりどころ

- モデル本体（`gene` など）は **submodule**。`main.mdf` は superproject 側なので先に現れるが、submodule のダウンロードはその後も続く。**`main.mdf` の出現＝完了ではない**。完了判定は git プロセスの終了で見る。

---

## 4. 起動時の `failed to load mecab dictionary`（最大の罠）

起動はできるが、画面に赤字で

```
Open_JTalk: failed to load mecab dictionary in ".../Release/AppData/Open_JTalk"
```

が出る（日本語音声合成が無効）。

### 原因

本体リポジトリの `Release/AppData/Open_JTalk/*`（`sys.dic` は約 63MB 等）は **Git LFS 管理**だが、**リポジトリに `.gitattributes` が存在しない**。そのため:

- git-lfs がこれらを「pull すべき LFS ファイル」と認識できない
- 通常の clone では実体ではなく **ポインタファイル（約 130 バイト）** のまま
- 結果、辞書が読めず Open_JTalk が失敗する

`du -sh Release/AppData/Open_JTalk/sys.dic` が数 KB なら、それは実体ではなくポインタ。中身を見ると `version https://git-lfs.github.com/spec/v1 ...` になっている。

### 対処

git-lfs を入れ、対象パス用の `.gitattributes` を自分で用意してから pull する（`git lfs fetch --all` だけでは辞書は対象外で拾えない点に注意）。

```bash
sudo pacman -S --needed git-lfs
git lfs install

cd MMDAgent-EX
# .gitattributes が無いので対象パスに filter=lfs を明示する
echo 'Release/AppData/Open_JTalk/** filter=lfs diff=lfs merge=lfs -text' > .gitattributes

git lfs pull --include="Release/AppData/Open_JTalk/**"
# sys.dic が 63,116,776 バイト（約 61M）になれば実体取得成功
```

---

## 5. 起動

```bash
./Release/MMDAgent-EX ./example/main.mdf
```

3D キャラクター（Gene）が表示されれば成功。

- Wayland（niri）環境でも、`DISPLAY=:1` の **XWayland** 経由で問題なく表示された（バイナリは libX11 をリンク）。
- スクリーンショットは `grim` で取得できる。
- 手元では 4x MSAA で約 118fps 出ていた。

---

## まとめ（チェックリスト）

- [ ] Debian 名 → Arch 名に読み替え、`librabbitmq-c` を忘れない
- [ ] `pulseaudio` は入れない（pipewire と競合）
- [ ] GCC 16 対策で `-std=gnu17` + 各種 `-Wno-error=...` を付ける
- [ ] Poco の JSON include を RabbitMQ プラグインに追加
- [ ] example は `--recursive` で clone、submodule 完了まで待つ
- [ ] LFS 辞書は `.gitattributes` を用意して `git lfs pull`（ポインタのままだと mecab エラー）
