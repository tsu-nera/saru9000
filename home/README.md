# home

自宅サーバ vaio で動かすスマートホーム基盤（`compose.yaml`: Home Assistant・go2rtc・Matter Hub・VOICEVOX）と、それを mouse・vaio のどちらからでも操作するスクリプト。機器の正本は HA で、操作のしかたは AGENTS.md。

接続先（HA の URL・ssh 先・コンテナ名）は `config.json`。HA の設定のうち git で管理するのは `packages/`（コンテナの `/config/packages` に重ねる）で、それ以外は vaio の git 外 `home/config/`。

## 秘密値（repo 直下 `.env`、gitignore 済み）

| 変数 | 用途 |
|---|---|
| `HA_TOKEN` | HA の long-lived access token |
| `NATURE_REMO_API_KEY` | Nature Remo Cloud API |
| `SWITCHBOT_TOKEN` / `SWITCHBOT_SECRET` | SwitchBot Cloud API v1.1 |
| `HAMH_HTTP_AUTH_PASSWORD` | Matter Hub の Web UI |

環境変数に同名があればそちらが優先される。mouse と vaio の両方に同じ `.env` を置き、変えたら手でコピーする: `scp .env vaio:repo/saru9000/.env && ssh vaio chmod 600 repo/saru9000/.env`

## 光目覚まし

スマホの時計アプリのアラームの少し前から、電球が暖色・暗めから白・最大へ明るくなる（`packages/wake_light.yaml`）。

- 使う日: アラームを設定し、sleep mode を on にする（`python3 home/ha.py call switch.turn_on switch.adaptive_lighting_ceiling_sleep_mode`）
- 前提: アラームを鳴らすスマホの Companion app で「設定 → Companion App → センサーの管理 → Next alarm」を有効にする

## 設置・入れ直し（vaio）

git の外に手で置いているもの。

- **Nature Remo**: カスタム integration `NaNaLinks/homeassistant_nature_remo` を `home/config/custom_components/` に置く
- **Adaptive Lighting**: `basnijholt/adaptive-lighting` の release から `custom_components/adaptive_lighting` を置き、`configuration.yaml` に `homeassistant: packages: !include_dir_named packages` を足して HA を再起動。UI で作った entry が残っていると同じ `name` の YAML より UI 側が勝つので、消してから YAML に移す
- **地図カード**: `gh release download <タグ> -R nathan-gs/ha-map-card` の `map-card.js` を `home/config/www/` に `sudo cp` し、`python3 home/ha.py ws lovelace/resources/create '{"res_type":"module","url":"/local/map-card.js?v=<タグ>"}'`。`www/` を初めて作った時は HA の再起動が要る
- **騒音・画面時間 sensor**（systemd user service）:

```bash
ln -sf ~/repo/saru9000/home/noise.service ~/.config/systemd/user/noise.service
ln -sf ~/repo/saru9000/home/screen_time.service ~/.config/systemd/user/screen_time.service
systemctl --user daemon-reload
systemctl --user enable --now noise screen_time
journalctl --user -u noise -f      # HA に届かなかった分は "post failed"
```

`noise.py` / `screen_time.py` を変えたら vaio で pull して `systemctl --user restart noise`（または `screen_time`）。
