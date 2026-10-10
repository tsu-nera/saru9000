# home

自宅サーバ vaio で動かすスマートホーム基盤（`compose.yaml`: Home Assistant・go2rtc・Matter Hub・VOICEVOX）と、
それを mouse・vaio のどちらからでも操作するスクリプト。

## 原則

- **機器の正本は HA**。entity ID・表示名・Area・状態は HA に問い合わせる。HA に載らない補足（型番・赤外線仕様・判断の経緯）は gitignore 済みの `private/devices.md`
- 操作は基本 HA 経由。メーカーの API を直接叩くのは HA を挟まない切り分けの時だけ
- スクリプトは mouse・vaio のどちらでも同じように動き、出力は JSON。worktree から実行しても main checkout の `.env` を読む
- vaio 上では ssh・scp を挟まず手元で実行する（`ha.on_host()` が hostname を `config.json` の `ssh_host_hostname` と比べる）。`voice.py listen` は mouse のヘッドホン用なので mouse 専用
- 接続先（HA の URL・ssh 先・コンテナ名）は `config.json`

## やりたいこと → コマンド

| やりたいこと | コマンド |
|---|---|
| Area 内の機器と状態を見る | `python3 home/ha.py states --area mein`（area_id は `ws config/area_registry/list`） |
| ドメインで絞って見る | `python3 home/ha.py states --domain light` |
| 1 entity の詳細 | `python3 home/ha.py state light.xxx` |
| 点ける・消す（複数可） | `python3 home/ha.py call light.turn_on light.xxx light.yyy`（スイッチ類は `switch.turn_on` / `turn_off`） |
| いつ何が変わったか | `python3 home/ha.py history script.xxx light.xxx --minutes 30`（script は `on` が実行中） |
| 明るさなど service data 付き | `python3 home/ha.py call light.turn_on light.xxx --data '{"brightness_pct": 30}'` |
| entity ID・表示名を変える | `python3 home/ha.py ws config/entity_registry/update '{"entity_id": "light.old", "new_entity_id": "light.new"}'` |
| Area に入れる（device ごと） | `python3 home/ha.py ws config/device_registry/update '{"device_id": "…", "area_id": "mein"}'` |
| Area に入れる（device の無い entity） | `python3 home/ha.py ws config/entity_registry/update '{"entity_id": "…", "area_id": "mein"}'` |
| integration の entry を探す | `python3 home/ha.py ws config_entries/get '{"domain": "switchbot_cloud"}'` |
| entry を無効化・有効化 | `python3 home/ha.py ws config_entries/disable '{"entry_id": "…", "disabled_by": "user"}'`（有効化は `null`） |
| 部屋の様子を見る | `python3 home/camera.py on` → `python3 home/camera.py snap -o <scratchpad>/snap.jpg` → 画像を読む |
| カメラを止める | `python3 home/camera.py off` |
| Google Home に見せている機器 | `python3 home/matter_hub.py devices` |
| Google Home に機器一覧を読み直させる | `python3 home/matter_hub.py kick`（ラベルを変えた後・Offline の時） |
| 声で Google に頼んで結果を見る | `python3 home/voice.py say "OK Google、、、〇〇をオンにして" --expect <entity_id>` |
| 家の音をヘッドホンで生で聞く | `python3 home/voice.py listen --seconds 40 -o <scratchpad>/home.wav`（別端末・background で流しながら `say` する） |
| 録った wav を文字起こし | `python3 home/voice.py transcribe <scratchpad>/home.wav`（小さい音を持ち上げてから） |
| Google Home アプリの画面を見る・押す | `python3 home/waydroid.py start` → `shot -o <scratchpad>/home.png` → 画像を読む → `tap X Y` |
| Nest Mini に読み上げさせる | `python3 home/ha.py call tts.speak tts.xxx --data '{"media_player_entity_id": "media_player.xxx", "message": "…", "language": "ja"}'` |
| SwitchBot を HA 抜きで確認 | `python3 home/switchbot.py devices` / `status <deviceId>` / `command <deviceId> turnOn` |
| 電球の時間帯調整（Adaptive Lighting）の今の目標値 | `python3 home/ha.py state switch.adaptive_lighting_denkyu`（`brightness_pct`・`color_temp_kelvin`・`manual_control`） |
| その設定を変える | `home/packages/adaptive_lighting.yaml` を直して merge → vaio の main で pull → HA を再起動 |
| 光目覚まし（アラームの少し前から電球が明るくなる） | スマホの時計アプリでアラームを設定し、sleep mode を on: `python3 home/ha.py call switch.turn_on switch.adaptive_lighting_denkyu_sleep_mode`。設定を変えるなら `home/packages/wake_light.yaml` を直して merge → vaio で pull → `python3 home/ha.py call automation.reload` |
| 部屋の騒音（1分ごとの Leq・max・L90） | `python3 home/ha.py history sensor.noise_leq sensor.noise_max sensor.noise_l90 --minutes 10`（単位は dBFS。下の「騒音 sensor」） |
| 外気（met.no の気温・湿度・露点・気圧、Kp 指数、最新の地震、気象警報・注意報）を見る | `python3 home/ha.py state sensor.outdoor_temperature`（ほか `sensor.outdoor_humidity` / `outdoor_dew_point` / `outdoor_pressure` / `kp_index` / `latest_earthquake` / `weather_warnings`）。設定は `home/packages/outdoor.yaml` を直して merge → vaio で pull → `python3 home/ha.py call template.reload` |
| 赤外線を Remo から直接送る | `python3 home/ir/<機器>.py on`（Remo ローカル API。建物 Wi-Fi 内からのみ） |

## 落とし穴

- **registry と config entry の操作は websocket にしか無い**（REST に無い、flow 一覧の GET も 405）。`ha.py ws` を使う。`ha.py` は HA コンテナ内の python3 に ssh 越しにスクリプトを渡して実行するので、mouse に依存ライブラリは要らない。vaio 上で動かすにはユーザーが docker グループに要る
- **日本語名から作られた entity ID は中国語読みになる**（`light.sumatodian_qiu_zuo` など）。integration を足したら `ws config/entity_registry/update` でローマ字に付け替える
- **赤外線機器の state は最後に送ったコマンド**で、実機の状態ではない。取りこぼしもある。点いたかはカメラで確かめる
- integration の追加は REST の config flow: `POST /api/config/config_entries/flow`（`{"handler": "<domain>"}`）→ 返った `data_schema` の項目を `POST /api/config/config_entries/flow/<flow_id>` へ。`ha.rest()` で叩ける。秘密値は argv に出さず `ha.secret()` で読む
- SwitchBot は BLE 直結（vaio 内蔵 BT）だと接続が詰まるので Cloud integration を使う。
- モニターの on/off は HA の `command_line`（vaio の git 外 `home/config/configuration.yaml`。root 所有なので sudo で編集し `ha.py call command_line.reload`。表示名もここの `name`）。on/off は `/config/.ssh` の HA 専用鍵で vaio に ssh し、`authorized_keys` の `command=` で `home/monitor/dpms.sh` だけに制限。状態は ssh せず sysfs の `dpms` から読む
- niri の DPMS off は何か入力があると勝手に復帰する。HA の状態は sysfs を読むので追従する
- カメラの snap は照明が消えていると真っ黒。go2rtc を止めると HA の entity は `unavailable`
- **Matter Hub を再起動して増えた機器は Google Home で Offline のまま**。Hub の `configurationVersion` は HA entity の追加では上がらず、起動時に増えた機器を Google が読み直さない。再起動せず `matter_hub.py kick` する。script は Google からコンセント型の機器に見え、ON で実行・すぐ OFF に戻る
- Cast（Nest Mini 等）で鳴らすと、スピーカーが HA の `/api/tts_proxy/*.mp3` を取りに来る。vaio の firewalld（建物 Wi-Fi 側）は 8123 を Google の機器の IP にだけ開けてある（建物 Wi-Fi は共有なので全開放しない）。IP が DHCP で変わると「Failed to cast media ... Reachable from the cast device」で無音になる
- `home/config/packages`（root 所有の空ディレクトリ）は git 管理の `home/packages` をコンテナの `/config/packages` に重ねるマウント先。消すと HA から packages が丸ごと見えなくなり、再起動で Adaptive Lighting の YAML switch が削除される。消してしまったら `sudo mkdir -p home/config/packages` して `docker compose up -d --force-recreate homeassistant`
- trigger-based template の直下の `variables:` は actions より前に評価される。`rest_command` の `response_variable` を使う計算は actions の中の `- variables:` ステップに書く

## 検証ループ（人を介さずに確かめる）

HA の設定や Google 連携を変えたら、入力と観測をこの組み合わせで回して agent だけで確かめる。

| 入力 | 観測 |
|---|---|
| HA の service（`ha.py call`） | HA の state・履歴（`ha.py state` / `history`） |
| Google Home アプリのタップ（`waydroid.py tap`） | 部屋の明るさ（`camera.py snap`。消灯時は真っ黒） |
| vaio のスピーカーで話しかける（`voice.py say`） | vaio のマイクの文字起こし（`voice.py` の `transcript`） |
| | Google Home アプリの表示（`waydroid.py shot`） |

判定は `last_triggered`（`voice.py --expect`）→ 機器の state → カメラの順。返事の中身は `transcript` で見る。

### 家の音を直接聞く

人が耳で確かめたい時は、mouse にヘッドホンを挿して `voice.py listen`。vaio のマイクを `pw-record --raw -` で ssh 越しに流し、
mouse で +20dB（リミッター付き）して `pw-play` する。`-o` で素の録音も残るので、聞いた後に `transcribe` で照らし合わせられる。
家側では何も鳴らない（聞くだけ）。

- **Google スピーカーの返事は vaio のマイクではかなり小さくしか録れない**。そのまま文字起こしすると落ちるので、`say` / `transcribe` は ffmpeg の `dynaudnorm` で持ち上げてから ReazonSpeech に渡す
- 録音のどこで鳴ったかは 0.1 秒ごとの RMS を見ると分かる（返事の回数・間隔の切り分け）

- **合成音声で試す時は Google Home アプリで Voice Match をオフにする**。オンだと「ねえグーグル」以外の wake word にほぼ反応せず、既製ルーティンは本人と判定された声でしか動かない
- Google 側のルーティン（開始フレーズ → HA の機器をオン）は Waydroid の Google Home アプリから `waydroid.py tap` で編集できる
- Waydroid の表示言語が英語だと既製ルーティンの開始フレーズも英語（"I'm home"）で表示される。日本語で確認するには `settings put system system_locales ja-JP` と `setprop persist.sys.locale ja-JP` の後に Waydroid を再起動
- `voice.py` は試験中だけ vaio の出力音量を 1.0 にし、終わったら戻す。
- saru-core（wake word ミク/サル）は試験音声に反応しない
- Waydroid（mouse）は NAT 内なので Cast 機器のページ（設定・再起動）は「Not available」。クラウド経由の機器一覧と自動化は使える
- `waydroid shell` は受け取った stdin/stdout/stderr のファイルを root 所有に変える（シェルで `> file` すると自分で読めなくなる）。`waydroid.py` はパイプで受けている
- Waydroid は省電力でコンテナが FROZEN になり shell が返らなくなる。`waydroid.py start` が再起動と `persist.waydroid.suspend false` をする

## 秘密値（repo 直下 `.env`、gitignore 済み）

| 変数 | 用途 |
|---|---|
| `HA_TOKEN` | HA の long-lived access token |
| `NATURE_REMO_API_KEY` | Nature Remo Cloud API（`Authorization: Bearer`、`https://api.nature.global/1/...`） |
| `SWITCHBOT_TOKEN` / `SWITCHBOT_SECRET` | SwitchBot Cloud API v1.1（HMAC 署名は `switchbot.py`） |
| `HAMH_HTTP_AUTH_PASSWORD` | Matter Hub の Web UI |

値を表示・ログ出力しない。環境変数に同名があればそちらが優先される。

mouse と vaio の両方に同じ `.env` を置く（自動同期はしない）。変えたら手でコピーする: `scp .env vaio:repo/saru9000/.env && ssh vaio chmod 600 repo/saru9000/.env`（vaio で変えたら逆向き）

## Nature Remo

HA の integration はカスタム（`NaNaLinks/homeassistant_nature_remo`、vaio の `home/config/custom_components/` に手置き、git 外）。直接叩く時:

- センサー値: `GET /1/devices` の `newest_events`（`te` 温度・`hu` 湿度・`il` 照度・`mo` 人感）。更新は数分〜十数分おき
- プリセット家電: `POST /1/appliances/{id}/aircon_settings` など。学習・生信号は `POST /1/signals/{id}/send`
- リモコンの無い機器は生信号（`{"freq":38,"data":[µs...],"format":"us"}`）を `POST /1/appliances` → `POST /1/appliances/{id}/signals` で登録すると Remo アプリと HA（`remote.*`）に出る
- appliance・signal の ID は `private/devices.md`

## Adaptive Lighting（電球の時間帯調整）

SwitchBot 電球の色温度・明るさを太陽位置（日の出・南中・日の入り・真夜中を放物線でつないだ -1〜+1）で変える custom integration
（`basnijholt/adaptive-lighting`、vaio の `home/config/custom_components/` に手置き、git 外。HACS は使っていない）。
照度センサーは使わない。設定は `home/packages/adaptive_lighting.yaml`（git 管理）。compose で `/config/packages` に渡し、vaio の `configuration.yaml` の `homeassistant: packages: !include_dir_named packages` で読み込む。

入れ直し: release の tarball から `custom_components/adaptive_lighting` を置き、`configuration.yaml` に上の packages を足して HA を再起動。

- YAML は HA の起動時（`async_setup`）に取り込まれるので、値を変えたら再起動する（entry の reload で反映されるかは未確認）。YAML で作った entry は UI の設定画面から編集できない
- UI で作った entry が残っていると、同じ `name` の YAML は取り込まれても UI 側の値が勝つ。UI の entry は消してから YAML に移す

- **`detect_non_ha_changes` は true 必須**。SwitchBot Cloud は点灯の state を数秒後のポーリングで別 context として上げるので、false だと Adaptive Lighting が「HA の外で点けられた」と見て点けた直後に手動扱い（`manual_control`）にし、追従を止める。true にすると `interval` ごとに `update_entity` で Cloud API を叩く（電球の数 × 1日の interval 回数）
- 手動や Google Home で明るさ・色を変えると `take_over_control` で次に消すまでその電球は追従しない。`manual_control` 属性に入る

### 光目覚まし

`home/packages/wake_light.yaml`。スマホの時計アプリのアラーム（Companion app の Next alarm センサー）の少し前から、電球を暖色・暗めから白・最大へ段階的に上げる。sleep mode が on の時だけ動き、始めに sleep mode を切る。終了後は消すまでそのまま。

- 前提: アラームを鳴らすスマホの Companion app で「設定 → Companion App → センサーの管理 → Next alarm」を有効にする。アラームが無いと state は `unavailable`。属性 `Package` にアラームを入れたアプリが入る
- sleep mode が残ると、太陽位置に関係なく夜の色と明るさのまま朝を迎える。昼に残っていれば別の automation が切る
- **sleep mode を変えると `manual_control` がリセットされる**（`reset_manual_control_on_sleep_mode_change` 既定 true）。sleep を切ってから manual にする順序を崩さない
- **ランプ中に電球を消しても、次の段で点け直される**。SwitchBot Cloud は命令の反映が遅く、手で消した off が後から届いた段の点灯に上書きされる。止めたいときは `python3 home/ha.py call automation.turn_off automation.wake_light`（実行中の動作も止まる）→ `automation.turn_on` で戻す
- 点けた直後は、Cloud の state がしばらく `off` のまま残る。state で判定を足すときは開始後に変わった state だけを見る

## 騒音 sensor

`home/noise.py` が vaio のマイクを `pw-record --raw -` で常時読み、1秒ごとの音量から1分ごとに3値を HA に送る（`POST /api/states`）。
`sensor.noise_leq`（1分のエネルギー平均）・`sensor.noise_max`（1秒値の最大）・`sensor.noise_l90`（1秒値の下位10%点＝暗騒音）。
`state_class: measurement` 付きなので HA が長期統計を残す。録音は保存しない。

- **値は dBFS（マイク入力の上限を 0 とした相対値）で、騒音計の dB SPL ではない**。マイクの音量設定が変わると全体がずれる。無音は -120
- マイクの音量・ゲインは触らない（会話エージェントと共有）。VOICEVOX や `voice.py say` の再生音もそのまま入る
- REST で作った entity なので HA を再起動すると次の送信（最長1分）まで消える。entity registry には載らない（Area に入れられない）

設置（vaio で一度だけ）:

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/repo/saru9000/home/noise.service ~/.config/systemd/user/noise.service
systemctl --user daemon-reload
systemctl --user enable --now noise
systemctl --user status noise          # CPU・メモリもここで見る
journalctl --user -u noise -f          # HA に届かなかった分は "post failed" が出る
```

`noise.py` を変えたら vaio で pull して `systemctl --user restart noise`。

## 外気

`home/packages/outdoor.yaml`。キー不要の取得元だけを使う。

- 気温・湿度・露点・気圧: `weather.forecast_zi_zhai`（met.no）の attribute を template sensor にしたもの。予報モデルの値で実測ではない
- Kp 指数（NOAA SWPC）
- 最新の地震（P2P地震情報）。最大震度・津波の有無は仕様（`https://www.p2pquake.net/swagger-ui/specification.yaml`）の値を日本語に直している
- 気象警報・注意報（気象庁の bosai JSON）。発表中の件数が state、名称が attributes の `warnings`。自宅の区域コードは vaio の git 外 `home/config/secrets.yaml` の `jma_warning_area_code`。コード→名称は気象庁防災情報 XML の個別コード表（`https://xml.kishou.go.jp/tec_material.html`）の「警報等情報要素コード管理表」
- 取得は `rest_command` → trigger-based template。`rest_command` を初めて足した時は `template.reload` では読まれず、HA の再起動が要る

## 大気質

`home/packages/air_quality.yaml`。Google Air Quality API の自宅座標の推計値（`sensor.google_aqi` `google_aqi_jp` `google_pm25` `google_pm10` `google_no2` `google_o3`）。作りは `pollen.yaml` と同じ。

- URL（API キー入り）は vaio の git 外 `home/config/secrets.yaml` の `google_air_quality_url`。キーは Pollen と共通。座標は `zone.home` から POST body に入れる
- **`sensor.google_aqi` は Universal AQI で 100 が最良**（大きいほど悪い WAQI と逆）。`google_aqi_jp` は数値でなく「2 - シアン」のようなレベル文字列
- **WAQI（`sensor.waqi_*`）は指数、Google は濃度（µg/m³・ppb）**。同じ PM2.5 でも数字は直接比べられない。WAQI は離れた観測局の値、Google は自宅の座標の推計
- API が返さなかったコードの sensor は前の値を保つ。`rest_command` を初めて足した時は HA の再起動が要る（外気と同じ）
