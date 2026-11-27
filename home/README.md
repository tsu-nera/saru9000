# home

自宅サーバ vaio で動かすスマートホーム基盤（`compose.yaml`: Home Assistant・go2rtc・Matter Hub・VOICEVOX・phone）と、それを iiyama・mouse・vaio のどれからでも操作するスクリプト。機器の正本は HA で、操作のしかたは AGENTS.md。

接続先（HA の URL・ssh 先・コンテナ名）は `config.json`。HA の設定のうち git で管理するのは `packages/`（コンテナの `/config/packages` に重ねる）で、それ以外は vaio の git 外 `home/config/`。

## 秘密値（repo 直下 `.env`、gitignore 済み）

| 変数 | 用途 |
|---|---|
| `HA_TOKEN` | HA の long-lived access token |
| `NATURE_REMO_API_KEY` | Nature Remo Cloud API |
| `SWITCHBOT_TOKEN` / `SWITCHBOT_SECRET` | SwitchBot Cloud API v1.1 |
| `HAMH_HTTP_AUTH_PASSWORD` | Matter Hub の Web UI |
| `TPLINK_PASSWORD` | TP-Link ID の cloud password。Tapo Control の C220 認証 |
| `TAPO_CAMERA_USERNAME` / `TAPO_CAMERA_PASSWORD` | Tapo アプリで作ったカメラアカウント。ONVIF・Tapo Control の RTSP |
| `KANSEN_URL` / `KANSEN_WARD` | 市の感染症週報 PDF の URL の雛形（`{year}`＝令和の年2桁・`{week}`＝週2桁）と区の名前（表の行の見出し）。`home/kansen.py` |

環境変数に同名があればそちらが優先される。iiyama・mouse・vaio に同じ `.env` を置き、変えたら手でコピーする: `scp .env vaio:repo/saru9000/.env && ssh vaio chmod 600 repo/saru9000/.env`（mouse も同様）

`compose.yaml` が読む変数は `home/.env`（repo 直下の `.env` とは別）に置く。`HAMH_HTTP_AUTH_PASSWORD` などに加えて `PHONE_SIP_TARGET`（電話の発信先の SIP URI）・`PHONE_SIP_USER` / `PHONE_SIP_PASS`（発信用の sip.linphone.org アカウントのユーザー名とパスワード）がある。

## 光目覚まし

スマホの時計アプリのアラームの少し前から、電球が暖色・暗めから白・最大へ明るくなる（`packages/wake_light.yaml`）。

- 使う日: アラームを設定し、sleep mode を on にする（`python3 home/ha.py call switch.turn_on switch.adaptive_lighting_ceiling_sleep_mode`）
- 前提: アラームを鳴らすスマホの Companion app で「設定 → Companion App → センサーの管理 → Next alarm」を有効にする

## 設置・入れ直し（vaio）

git の外に手で置いているもの。

- **Nature Remo**: カスタム integration `NaNaLinks/homeassistant_nature_remo` を `home/config/custom_components/` に置く
- **Adaptive Lighting**: `basnijholt/adaptive-lighting` の release から `custom_components/adaptive_lighting` を置き、`configuration.yaml` に `homeassistant: packages: !include_dir_named packages` を足して HA を再起動。UI で作った entry が残っていると同じ `name` の YAML より UI 側が勝つので、消してから YAML に移す
- **起床の判定（`shell_command.bed_check`）の鍵**: `docker exec homeassistant ssh-keygen -t ed25519 -N '' -C ha-bed-check -f /config/.ssh/ha_bed_check` で作り、公開鍵を vaio の `~/.ssh/authorized_keys` に `command="/home/tsu-nera/repo/saru9000/home/bed_check.sh",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding` を付けて足す。`shell_command` を初めて足した時は HA の再起動
- **Tapo Control（C220 の privacy mode）**: `gh release download <タグ> -R JurajNyiri/HomeAssistant-Tapo-Control --archive tar.gz` の `custom_components/tapo_control` を `home/config/custom_components/` に `sudo cp` し HA を再起動。config flow で IP・カメラアカウント・cloud password（`TPLINK_PASSWORD`）を入れ、other options は全部オフ。ONVIF と重なるので `switch.tapo_c220_privacy` 以外の entity は無効にする。HACS は使わない
- **Advanced Camera Card（C220 の映像と首振り）**: `gh release download <タグ> -R dermotduffy/advanced-camera-card -p advanced-camera-card.zip` の `dist/` を `home/config/www/advanced-camera-card/` に `sudo cp` し、`python3 home/ha.py ws lovelace/resources/create '{"res_type":"module","url":"/local/advanced-camera-card/advanced-camera-card.js?v=<タグ>"}'`。矢印は `ptz.actions_*` に `onvif.ptz` を割り当てる（未設定だと矢印は出るが動かない）
- **地図カード**: `gh release download <タグ> -R nathan-gs/ha-map-card` の `map-card.js` を `home/config/www/` に `sudo cp` し、`python3 home/ha.py ws lovelace/resources/create '{"res_type":"module","url":"/local/map-card.js?v=<タグ>"}'`。`www/` を初めて作った時は HA の再起動が要る
- **電話（phone）**: 受ける側はスマホに Linphone（Play Store）を入れ、sip.linphone.org のアカウントでログインする。発信用に別の sip.linphone.org の無料アカウントを作る（受ける側と同じアカウントは使わない）。`home/.env` に `PHONE_SIP_TARGET=sip:<受ける側のアカウント>@sip.linphone.org`・`PHONE_SIP_USER=<発信用のアカウント>`・`PHONE_SIP_PASS=<そのパスワード>` を書き、`docker compose up -d --build phone`（`server.py`・`linphonerc` を変えた時も同じ）。`docker logs phone` に `registered, identity=` が出ればログインできている。`phone.yaml` を初めて入れた時は rest_command なので HA の再起動
- **騒音・画面時間 sensor**（systemd user service）:

```bash
ln -sf ~/repo/saru9000/home/noise.service ~/.config/systemd/user/noise.service
ln -sf ~/repo/saru9000/home/screen_time.service ~/.config/systemd/user/screen_time.service
systemctl --user daemon-reload
systemctl --user enable --now noise screen_time
journalctl --user -u noise -f      # HA に届かなかった分は "post failed"
```

`noise.py` / `screen_time.py` を変えたら vaio で pull して `systemctl --user restart noise`（または `screen_time`）。

### バックアップと復元

- HA の自動バックアップ（設定の正本は HA の「設定 > システム > バックアップ」）。暗号化の鍵は `~/repo/agent-private/infra/ha-backup.md`
- 入るもの: `home/config`（DB・`.storage`・`secrets.yaml` など）と、`compose.yaml` の ro マウント経由の `home/matter-server`・`home/matter-hub`
- 入らないもの: `home/go2rtc`（`go2rtc.yaml` は git にある）、git 管理の `home/packages`・`home/dashboards`（git から戻る）。それ以外の volume は `/etc/localtime` と `/run/dbus` で、データではない。repo 直下と `home/` の `.env`（トークン類）も入らないので、復元後に再発行して書き直す
- 復元手順（未検証）:
  1. `compose.yaml` の `matter-server-data`・`matter-hub-data` の2つの ro マウントを一時的に外して HA を起動する
  2. オンボーディング画面で「バックアップから復元」を選び、鍵を入れる
  3. 復元された `home/config/matter-server-data`・`home/config/matter-hub-data` を `home/matter-server`・`home/matter-hub` へ移す
  4. マウントを戻して `docker compose up -d`
