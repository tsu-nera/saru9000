# home

家の機器の確認・操作のしかたと、コードや HA からは分からない落とし穴。設置・入れ直しの手順は README.md。

## 原則

- 機器の正本は HA。entity ID・表示名・Area・状態は HA に問い合わせる。HA に載らない補足（型番・赤外線仕様・ID）は gitignore 済みの `private/devices.md`
- 操作は HA 経由。メーカーの API を直接叩くのは HA を挟まない切り分けの時だけ
- スクリプトは mouse・vaio のどちらでも同じように動き、出力は JSON。worktree から実行しても main checkout の `.env` を読む。vaio 上では ssh を挟まず手元で実行する
- 秘密値（`.env`、vaio の git 外 `home/config/secrets.yaml`）は表示・ログ出力しない

## やりたいこと → コマンド

| やりたいこと | コマンド |
|---|---|
| Area・ドメインで絞って状態を見る | `python3 home/ha.py states --area mein` / `--domain light`（area_id は `ws config/area_registry/list`） |
| 1 entity の詳細 | `python3 home/ha.py state light.xxx` |
| service を呼ぶ（複数 entity 可） | `python3 home/ha.py call light.turn_on light.xxx light.yyy --data '{"brightness_pct": 30}'` |
| いつ何が変わったか | `python3 home/ha.py history script.xxx light.xxx --minutes 30`（script は `on` が実行中） |
| entity ID・表示名・Area を変える | `python3 home/ha.py ws config/entity_registry/update '{"entity_id": "…", "new_entity_id": "…"}'`（Area は device ごとなら `config/device_registry/update`） |
| integration の entry を探す・無効化 | `python3 home/ha.py ws config_entries/get '{"domain": "…"}'` / `config_entries/disable` |
| 部屋の様子を見る | `python3 home/camera.py on` → `snap -o <scratchpad>/snap.jpg` → 画像を読む → `off` |
| Google Home に見せている機器・読み直させる | `python3 home/matter_hub.py devices` / `kick` |
| 声で Google に頼んで結果を見る | `python3 home/voice.py say "OK Google、、、〇〇をオンにして" --expect <entity_id>` |
| 家の音をヘッドホンで聞く（mouse 専用） | `python3 home/voice.py listen --seconds 40 -o <scratchpad>/home.wav` |
| 録った wav を文字起こし | `python3 home/voice.py transcribe <scratchpad>/home.wav` |
| Google Home アプリを見る・押す | `python3 home/waydroid.py start` → `shot -o <scratchpad>/home.png` → `tap X Y` |
| Nest Mini に読み上げさせる | `python3 home/ha.py call tts.speak tts.xxx --data '{"media_player_entity_id": "media_player.xxx", "message": "…", "language": "ja"}'` |
| SwitchBot・Remo を HA 抜きで確認 | `python3 home/switchbot.py devices` / `python3 home/ir/<機器>.py on`（Remo ローカル API。建物 Wi-Fi 内からのみ） |
| ゴミの日の予定を見る・直す | Google カレンダーの「ゴミ」を直す（HA には `calendar.gomi` として届く。繰り返し予定・年末年始は sensor 側で 1月1〜3日を落とす） |
| core・声で頼める文（HA の sentence trigger）を足す | `home/packages/voice_commands.yaml` |
| `home/packages/*.yaml` の変更を反映 | merge → vaio の main で pull → `automation.reload` / `template.reload` / `script.reload`。`rest_command` を初めて足した時・`adaptive_lighting.yaml`・`www/` を初めて作った時は HA の再起動 |

## 検証ループ（人を介さずに確かめる）

HA の設定や Google 連携を変えたら、入力と観測を組み合わせて agent だけで確かめる。

| 入力 | 観測 |
|---|---|
| HA の service（`ha.py call`） | HA の state・履歴（`ha.py state` / `history`） |
| Google Home アプリのタップ（`waydroid.py tap`） | 部屋の明るさ（`camera.py snap`。消灯時は真っ黒） |
| vaio のスピーカーで話しかける（`voice.py say`） | vaio のマイクの文字起こし（`voice.py` の `transcript`） |
| | Google Home アプリの表示（`waydroid.py shot`） |

判定は `last_triggered`（`voice.py --expect`）→ 機器の state → カメラの順。返事の中身は `transcript` で見る。録音のどこで鳴ったかは 0.1 秒ごとの RMS で分かる。

- 合成音声で試す時は Google Home アプリで Voice Match をオフにする。オンだと「ねえグーグル」以外の wake word にほぼ反応せず、既製ルーティンは本人と判定された声でしか動かない
- core（wake word ミク/サル）は試験音声に反応しない
- Waydroid の表示言語が英語だと既製ルーティンの開始フレーズも英語で出る。`settings put system system_locales ja-JP` と `setprop persist.sys.locale ja-JP` の後に Waydroid を再起動
- Waydroid（mouse）は NAT 内なので Cast 機器のページ（設定・再起動）は「Not available」。クラウド経由の機器一覧と自動化は使える
- `waydroid shell` は受け取った stdin/stdout/stderr のファイルを root 所有に変える。直接呼ばず `waydroid.py` を使う

## 落とし穴

### HA

- registry と config entry の操作は websocket にしか無い（REST に無い）。`ha.py ws` を使う。vaio 上で動かすにはユーザーが docker グループに要る
- integration の追加は REST の config flow: `POST /api/config/config_entries/flow`（`{"handler": "<domain>"}`）→ 返った `data_schema` の項目を `POST /api/config/config_entries/flow/<flow_id>` へ。OAuth の integration はブラウザでの承認が要る。承認後に my.home-assistant.io の 404 や HA の 500 が出ても entry はできていることがあるので、まず `config_entries/get` を見る
- 日本語名から作られた entity ID は中国語読みになる（`light.sumatodian_qiu_zuo` など）。integration を足したら `ws config/entity_registry/update` でローマ字に付け替える
- entity registry の `labels` は置き換え。`config/entity_registry/update` で label を足す時は、付いている label（`script.tadaima` / `script.ittekimasu` の `matter` など）も含めて渡す。core が動かしてよい script は label `core` で決まり、付け外しは core の再起動で反映される
- trigger-based template の直下の `variables:` は actions より前に評価される。`rest_command` の `response_variable` を使う計算は actions の中の `- variables:` ステップに書く
- `home/config/packages`（root 所有の空ディレクトリ）は `home/packages` をコンテナに重ねるマウント先。消すと HA から packages が丸ごと見えなくなり、再起動で Adaptive Lighting の switch が削除される。消したら `sudo mkdir -p home/config/packages` して `docker compose up -d --force-recreate homeassistant`
- REST（`POST /api/states`）で作った entity（騒音・画面時間）は HA を再起動すると次の送信まで消え、registry に載らない（Area に入れられない）

### 機器

- 赤外線機器の state は最後に送ったコマンドで、実機の状態ではない。取りこぼしもある。点いたかはカメラで確かめる
- Nature Remo の `climate.aircon` には turn_on が無い。止まっている時に温度・風量を送るとモードが無くて失敗するので、`script.aircon_power_on` を先に通す
- Nature Remo Cloud API を直接叩くなら: センサー値は `GET /1/devices` の `newest_events`（`te` `hu` `il` `mo`、更新は数分〜十数分おき）。リモコンの無い機器は生信号（`{"freq":38,"data":[µs...],"format":"us"}`）を `POST /1/appliances` → `POST /1/appliances/{id}/signals` で登録すると Remo アプリと HA（`remote.*`）に出る。appliance・signal の ID は `private/devices.md`
- SwitchBot は BLE 直結（vaio 内蔵 BT）だと接続が詰まるので Cloud integration を使う
- 手動や Google Home で電球の明るさ・色を変えると、次に消すまでその電球は Adaptive Lighting に追従しない（`manual_control` 属性に入る）
- モニターの on/off は HA の `command_line`（vaio の git 外 `home/config/configuration.yaml`、root 所有。編集後 `command_line.reload`）。HA 専用鍵で vaio に ssh し、`authorized_keys` の `command=` で `home/monitor/dpms.sh` だけに制限している。niri の DPMS off は入力で勝手に復帰するが、state は sysfs を読むので追従する
- カメラの snap は照明が消えていると真っ黒。go2rtc を止めると HA の entity は `unavailable`

### Google

- Matter Hub を再起動して増えた機器は Google Home で Offline のまま（起動時に増えた機器を Google が読み直さない）。再起動せず `matter_hub.py kick` する。script は Google からコンセント型の機器に見え、ON で実行・すぐ OFF に戻る
- Cast（Nest Mini 等）で鳴らすと、スピーカーが HA の `/api/tts_proxy/*.mp3` を取りに来る。vaio の firewalld（建物 Wi-Fi 側）は 8123 を Google の機器の IP にだけ開けてある（建物 Wi-Fi は共有なので全開放しない）。IP が DHCP で変わると「Failed to cast media ... Reachable from the cast device」で無音になる
- Google スピーカーの返事は vaio のマイクではかなり小さく録れる。`voice.py` は `dynaudnorm` で持ち上げてから文字起こしする

### センサー・地図

- 騒音 sensor の値は dBFS（マイク入力の上限を 0 とした相対値）で dB SPL ではない。マイクの音量・ゲインは会話エージェントと共有なので触らない
- 画面時間が 0 分のままなら、まず `sensor.cachyos_active_app` が `none` で止まっていないか見る（go-hass-agent 側が niri の前面ウィンドウを取れていない）
- 騒音・画面時間・外気などの表示用 sensor を dailybuild の取得対象に足さない（dailybuild は元の sensor を読む。経路が2本になる）
- 大気質: WAQI（`sensor.waqi_*`）は指数、Google は濃度で、同じ PM2.5 でも直接比べられない。`google_aqi_jp` は数値でなくレベル文字列
- ダッシュボードの設定は HA の `.storage` にあり git に入らない。読むのは `ha.py ws lovelace/config '{"url_path": "…"}'`、書くのは `lovelace/config/save`。他のカードを巻き込まないよう、保存前に JSON を退避して差分を取る
- ダッシュボードの `url_path` はハイフン必須で、作った後は変えられない
- 地図カードの JS（`/local/map-card.js`）を更新したら、resource の URL のクエリのバージョンを変える（変えないとブラウザのキャッシュが残る）
- 花粉のタイルのキーは URL に直接入るのでダッシュボードの設定に載る。キーを回したらダッシュボードの URL も直す
- 花粉のタイルは Google Pollen API の `TREE_UPI`（スギ・ヒノキを含む）。植物単位のタイルは 400 で使えない
- 浸水深のタイル（国土地理院「重ねるハザードマップ」）は出典表示「国土地理院（重ねるハザードマップ）」を残す。想定区域の外は 404 で透明になる
- 表示条件付きのカード（花粉・防災の地図）を確かめる時は、しきい値を一時的に変えて `template.reload` し、確認後に戻す
- entity に `latitude` / `longitude` attribute を付けると左メニューの「マップ」に載り、遠い地点まで含めようとして縮小される。地震などの遠い地点の座標は attribute に入れない
