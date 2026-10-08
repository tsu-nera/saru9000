# home

自宅サーバ vaio で動かすスマートホーム基盤（`compose.yaml`: Home Assistant・go2rtc・Matter Hub・VOICEVOX）と、
それを mouse から操作するスクリプト。

## 原則

- **機器の正本は HA**。entity ID・表示名・Area・状態は HA に問い合わせる。HA に載らない補足（型番・赤外線仕様・判断の経緯）は gitignore 済みの `private/devices.md`
- 操作は基本 HA 経由。メーカーの API を直接叩くのは HA を挟まない切り分けの時だけ
- スクリプトは mouse から実行し、出力は JSON。worktree から実行しても main checkout の `.env` を読む
- 接続先（HA の URL・ssh 先・コンテナ名）は `config.json`

## やりたいこと → コマンド

| やりたいこと | コマンド |
|---|---|
| Area 内の機器と状態を見る | `python3 home/ha.py states --area mein`（area_id は `ws config/area_registry/list`） |
| ドメインで絞って見る | `python3 home/ha.py states --domain light` |
| 1 entity の詳細 | `python3 home/ha.py state light.denkyu_hidari` |
| 点ける・消す（複数可） | `python3 home/ha.py call light.turn_on light.denkyu_hidari light.denkyu_migi` |
| 明るさなど service data 付き | `python3 home/ha.py call light.turn_on light.denkyu_chuo --data '{"brightness_pct": 30}'` |
| entity ID・表示名を変える | `python3 home/ha.py ws config/entity_registry/update '{"entity_id": "light.old", "new_entity_id": "light.new"}'` |
| Area に入れる（device ごと） | `python3 home/ha.py ws config/device_registry/update '{"device_id": "…", "area_id": "mein"}'` |
| Area に入れる（device の無い entity） | `python3 home/ha.py ws config/entity_registry/update '{"entity_id": "…", "area_id": "mein"}'` |
| integration の entry を探す | `python3 home/ha.py ws config_entries/get '{"domain": "switchbot_cloud"}'` |
| entry を無効化・有効化 | `python3 home/ha.py ws config_entries/disable '{"entry_id": "…", "disabled_by": "user"}'`（有効化は `null`） |
| 居室モニターを消す・点ける | `python3 home/ha.py call switch.turn_off switch.kyoshitsu_monitor`（`switch.turn_on` で点灯） |
| 部屋の様子を見る | `python3 home/camera.py on` → `python3 home/camera.py snap -o <scratchpad>/snap.jpg` → 画像を読む |
| カメラを止める | `python3 home/camera.py off` |
| SwitchBot を HA 抜きで確認 | `python3 home/switchbot.py devices` / `status <deviceId>` / `command <deviceId> turnOn` |
| 間接照明の赤外線を Remo から直接送る | `python3 home/ir/ohm_ocr05w.py on`（Remo ローカル API。建物 Wi-Fi 内からのみ） |

## 落とし穴

- **registry と config entry の操作は websocket にしか無い**（REST に無い、flow 一覧の GET も 405）。`ha.py ws` を使う。`ha.py` は HA コンテナ内の python3 に ssh 越しにスクリプトを渡して実行するので、mouse に依存ライブラリは要らない
- **日本語名から作られた entity ID は中国語読みになる**（`light.sumatodian_qiu_zuo` など）。integration を足したら `ws config/entity_registry/update` でローマ字に付け替える
- **赤外線機器（エアコン・間接照明）の state は最後に送ったコマンド**で、実機の状態ではない。取りこぼしもある。点いたかはカメラで確かめる
- integration の追加は REST の config flow: `POST /api/config/config_entries/flow`（`{"handler": "<domain>"}`）→ 返った `data_schema` の項目を `POST /api/config/config_entries/flow/<flow_id>` へ。`ha.rest()` で叩ける。秘密値は argv に出さず `ha.secret()` で読む
- SwitchBot は BLE 直結（vaio 内蔵 BT）だと接続が詰まるので Cloud integration を使う。BLE の entry は無効化して残してある
- 居室モニター（`switch.kyoshitsu_monitor`）は HA の `command_line`（vaio の git 外 `home/config/configuration.yaml`）。on/off は `/config/.ssh` の HA 専用鍵で vaio に ssh し、`authorized_keys` の `command=` で `home/monitor/dpms.sh` だけに制限。状態は ssh せず sysfs の `card1-HDMI-A-1/dpms` から読む
- niri の DPMS off は何か入力があると勝手に復帰する。HA の状態は sysfs を読むので追従する
- カメラの snap は照明が消えていると真っ黒。go2rtc を止めると HA の entity は `unavailable`

## 秘密値（repo 直下 `.env`、gitignore 済み）

| 変数 | 用途 |
|---|---|
| `HA_TOKEN` | HA の long-lived access token |
| `NATURE_REMO_API_KEY` | Nature Remo Cloud API（`Authorization: Bearer`、`https://api.nature.global/1/...`） |
| `SWITCHBOT_TOKEN` / `SWITCHBOT_SECRET` | SwitchBot Cloud API v1.1（HMAC 署名は `switchbot.py`） |
| `HAMH_HTTP_AUTH_PASSWORD` | Matter Hub の Web UI |

値を表示・ログ出力しない。環境変数に同名があればそちらが優先される。

## Nature Remo

HA の integration はカスタム（`NaNaLinks/homeassistant_nature_remo`、vaio の `home/config/custom_components/` に手置き、git 外）。直接叩く時:

- センサー値: `GET /1/devices` の `newest_events`（`te` 温度・`hu` 湿度・`il` 照度・`mo` 人感）。更新は数分〜十数分おき
- プリセット家電: `POST /1/appliances/{id}/aircon_settings` など。学習・生信号は `POST /1/signals/{id}/send`
- リモコンの無い機器は生信号（`{"freq":38,"data":[µs...],"format":"us"}`）を `POST /1/appliances` → `POST /1/appliances/{id}/signals` で登録すると Remo アプリと HA（`remote.*`）に出る
- appliance・signal の ID は `private/devices.md`
