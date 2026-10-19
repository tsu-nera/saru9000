# saru9000

- 家の機器（照明・カメラ・エアコン等）の確認・操作は Home Assistant 経由。手順とコマンドは `home/AGENTS.md`
- 機器の正本は HA。HA に載らない補足は gitignore 済みの `private/devices.md`（repo は public なので家の情報を tracked ファイルに書かない）
- ディレクトリで作業する前に、そこの `AGENTS.md` を読む（`home/`・`agent/core/`・`agent/web/`）
- わたし自身（気分・健康・お金・過去・目標）に関わる相談では、親の `~/repo/gtd/CLAUDE.md` の決まりに従い、`~/repo/gtd/summary/README.md`（地図）を先に読む

## 文書の置き場所

- 特定の行に結び付く落とし穴は、そのコードや YAML のコメント
- コードから分からない作業の決まり・確かめ方・落とし穴は、そのディレクトリの `AGENTS.md`（`CLAUDE.md` は `@AGENTS.md` だけ）
- README は人向けに、何をするものか・前提・起動・設置の手順だけ
- コードの動きの言い換え、設定値・計測値、決めた経緯は書かない（正本はコード・HA、経緯は Issue）
