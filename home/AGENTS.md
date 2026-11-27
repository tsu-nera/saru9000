# home

家の機器の確認・操作のしかたと、コードや HA からは分からない落とし穴。設置・入れ直しの手順は README.md。

## 原則

- 機器の正本は HA。entity ID・表示名・Area・状態は HA に問い合わせる。HA に載らない補足（型番・赤外線仕様・ID）は `~/repo/agent-private/home/`（台帳 `README.md`、機器ごとは `devices/`）
- 操作は HA 経由。メーカーの API を直接叩くのは HA を挟まない切り分けの時だけ
- スクリプトは iiyama・mouse・vaio のどれでも同じように動き、出力は JSON。worktree から実行しても main checkout の `.env` を読む。vaio 上では ssh を挟まず手元で実行する
- 秘密値（`.env`、vaio の git 外 `home/config/secrets.yaml`）は表示・ログ出力しない

## やりたいこと → コマンド

| やりたいこと | コマンド |
|---|---|
| Area・ドメインで絞って状態を見る | `python3 home/ha.py states --area mein` / `--domain light`（area_id は `ws config/area_registry/list`） |
| 1 entity の詳細 | `python3 home/ha.py state light.xxx` |
| service を呼ぶ（複数 entity 可） | `python3 home/ha.py call light.turn_on light.xxx light.yyy --data '{"brightness_pct": 30}'` |
| いつ何が変わったか | `python3 home/ha.py history script.xxx light.xxx --minutes 30`（script は `on` が実行中） |
| 冷暖房の判定のしきい値・設定温度を変える | `python3 home/ha.py call input_number.set_value input_number.aircon_xxx --data '{"value": …}'`（`aircon_heat_*` / `aircon_cool_*`）。判定結果は `python3 home/ha.py state sensor.aircon_recommended_mode`、判定で点けてよいかは `input_boolean.aircon_auto` |
| entity ID・表示名・Area を変える | `python3 home/ha.py ws config/entity_registry/update '{"entity_id": "…", "new_entity_id": "…"}'`（Area は device ごとなら `config/device_registry/update`） |
| integration の entry を探す・無効化 | `python3 home/ha.py ws config_entries/get '{"domain": "…"}'` / `config_entries/disable` |
| カメラの privacy mode（映像を止める） | `python3 home/ha.py call switch.turn_on switch.tapo_c220_privacy` / `turn_off` |
| 部屋の様子を見る（C270） | `python3 home/camera.py on` → `snap -o <scratchpad>/snap.jpg` → 画像を読む → `off` |
| Tapo の静止画 | `python3 home/camera.py tapo snap -o <scratchpad>/tapo.jpg [--lights]` |
| Tapo の首振り | `python3 home/camera.py tapo move left 2`（left/right/up/down、回数、`--speed`） |
| Tapo で部屋を見回す | `python3 home/camera.py tapo sweep -o <scratchpad>/sweep --lights` → `sheet.jpg` を読む |
| Google Home に見せている機器・読み直させる | `python3 home/matter_hub.py devices` / `kick` |
| 声で Google に頼んで結果を見る | `python3 home/voice.py say "OK Google、、、〇〇をオンにして" --expect <entity_id>` |
| 家の音をヘッドホンで聞く（iiyama 専用） | `python3 home/voice.py listen --seconds 40 -o <scratchpad>/home.wav` |
| 録った wav を文字起こし | `python3 home/voice.py transcribe <scratchpad>/home.wav` |
| Google Home アプリを見る・押す | `python3 home/waydroid.py start` → `shot -o <scratchpad>/home.png` → `tap X Y` |
| スマホ・PC に通知を出す | `python3 home/ha.py call notify.mobile_app_<device> --data '{"title": "…", "message": "…"}'`（宛先は `ws get_services '{}'` の `notify`。HA で device を改名しても service 名は登録時のまま） |
| スマホに電話して読み上げる | `python3 home/ha.py call script.phone_call --data '{"text": "…"}'`（結果は answered / no_answer / declined / failed / busy。repeat は既定 3） |
| Nest Mini に読み上げさせる | `python3 home/ha.py call tts.speak tts.xxx --data '{"media_player_entity_id": "media_player.xxx", "message": "…", "language": "ja"}'` |
| スマホ経由の電池残量（TICKR・イヤホン（機種ごと）・WiMAX）の最後の値をスマホに聞く | `set -a; . ./.env; set +a; curl -s "$TASKER_HTTP_URL$TASKER_HTTP_PATH"`（Xiaomi の Tasker が返す。機器ごとに `level` と `at`（epoch 秒）） |
| Tasker のスクリプトを直す | `home/tasker/*.bsh` を直して `adb push home/tasker/<f>.bsh /sdcard/Download/saru9000/`。Tasker 側は `return source("/sdcard/Download/saru9000/<f>.bsh");` の1行なので触らない。結果は同じ場所の `battery.log` |
| SwitchBot・Remo を HA 抜きで確認 | `python3 home/switchbot.py devices` / `python3 home/ir/<機器>.py on`（Remo ローカル API。建物 Wi-Fi 内からのみ） |
| ゴミの日の予定を見る・直す | Google カレンダーの「ゴミ」を直す（HA には `calendar.gomi` として届く。繰り返し予定・年末年始は sensor 側で 1月1〜3日を落とす） |
| 就寝時刻を変える（既定 22:30 は dailybuild の bed_time と同じ。初回に一度入れる） | `python3 home/ha.py call input_datetime.set_datetime input_datetime.oyasumi_time --data '{"time": "22:30:00"}'` |
| スマートおやすみの段階の履歴 | `python3 home/ha.py history input_select.oyasumi_stage --minutes 1440` |
| スマートおやすみを止める・戻す | `python3 home/ha.py call input_boolean.turn_off input_boolean.smart_oyasumi` / `turn_on` |
| 起床時刻を変える（既定 05:45 は dailybuild の rise_time と同じ。初回に一度入れる） | `python3 home/ha.py call input_datetime.set_datetime input_datetime.ohayo_time --data '{"time": "05:45:00"}'` |
| スマホのアラームを今すぐ書く | `python3 home/ha.py call script.set_phone_alarm` |
| スマートおはようの段階・アラーム・電話の履歴 | `python3 home/ha.py history input_select.ohayo_stage event.sleep_as_android_alarm_clock script.phone_call --minutes 1440`（電話の結果は `ws trace/list` の `{"domain": "script", "item_id": "phone_call"}`） |
| 起床の判定（カメラで寝袋が片付いているか）を今すぐ試す | HA の道具は `script.check_awake`（automation からは `response_variable` で `result` を受ける）。画像も見るなら vaio で `python3 home/bed_check.py --keep <scratchpad>/bed.jpg`（privacy を切って撮り、戻す。結果は `input_select.ohayo_bed` に書く）。HA からの実行のログは vaio の `~/.local/state/saru9000/bed_check.log` |
| 夜のアプリ停止（YouTube・Claude）を今すぐ止める・戻す | `python3 home/ha.py call switch.turn_on switch.app_block` / `turn_off`（すぐ戻す。止めてから `HOURS` 後には Tasker が自分で戻す）。止まっているかと解除時刻は `python3 home/ha.py state switch.app_block` / `input_datetime.app_block_until`（Tasker が結果を返した時だけ変わる）。止める長さは `home/tasker/app_block.bsh` の `HOURS` |
| 風邪の流行（市の週報）を今すぐ取り直す | `python3 home/kansen.py`（`--dry-run` で送らない）。普段は vaio の routine `home/routines/kansen.md` が6時間ごとに回し、読めない時だけ Discord の DM が来る。`home/routines` は vaio の `~/.config/routine/dirs` に登録済み |
| core・声で頼める文（HA の sentence trigger）を足す | `home/packages/voice_commands.yaml` |
| `home/packages/*.yaml` の変更を反映 | merge → vaio の main で pull → `automation.reload` / `template.reload` / `script.reload`。`rest_command` を初めて足した時・`www/` を初めて作った時、`adaptive_lighting.yaml` を変えた時は毎回 HA の再起動（config entry の reload では読み直さない）。`home/dashboards/*.yaml` は pull 後にブラウザの再読み込みだけでよい |

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

- script・automation は `home/packages` に書く。UI で試したら packages に移し、git 外の `home/config/scripts.yaml` / `automations.yaml` から消す（同じ key が両方にあると重複になる）
- registry と config entry の操作は websocket にしか無い（REST に無い）。`ha.py ws` を使う。vaio 上で動かすにはユーザーが docker グループに要る
- integration の追加は REST の config flow: `POST /api/config/config_entries/flow`（`{"handler": "<domain>"}`）→ 返った `data_schema` の項目を `POST /api/config/config_entries/flow/<flow_id>` へ。OAuth の integration はブラウザでの承認が要る。承認後に my.home-assistant.io の 404 や HA の 500 が出ても entry はできていることがあるので、まず `config_entries/get` を見る
- Area は mein・genkan（玄関・キッチン）・mochimono（持ち物）・network。device に入れれば entity は受け継ぐ。device の無い entity（`home/packages` の template sensor など。YAML には書けない）は、物・場所に結び付くものだけ `ws config/entity_registry/update` で入れる。家全体・抽象的なもの（天気・カレンダー・Claude 使用率）と automation・script・input_* は入れない。core は area 指定を拒むので agent の操作には効かず、効くのは声の「電気つけて/消して」（`area_id: mein`）
- 日本語名から作られた entity ID は中国語読みになる（`light.sumatodian_qiu_zuo` など）。integration を足したら `ws config/entity_registry/update` でローマ字に付け替える
- entity registry の `labels` は置き換え。`config/entity_registry/update` で label を足す時は、付いている label（`script.tadaima` / `script.ittekimasu` の `matter` など）も含めて渡す。core が動かしてよい script は label `core` で決まり、付け外しは core の再起動で反映される
- trigger-based template の直下の `variables:` は actions より前に評価される。`rest_command` の `response_variable` を使う計算は actions の中の `- variables:` ステップに書く
- `home/config/packages`（root 所有の空ディレクトリ）は `home/packages` をコンテナに重ねるマウント先。消すと HA から packages が丸ごと見えなくなり、再起動で Adaptive Lighting の switch が削除される。消したら `sudo mkdir -p home/config/packages` して `docker compose up -d --force-recreate homeassistant`
- `home/config/matter-server-data`・`matter-hub-data` は ro マウント先（HA のバックアップに Matter の登録情報を入れるため）。HA からは書けず、復元時はマウントを外してから（手順は README）
- 声や script で機器が動かないのに trace が `finished` なら、まず `config_entries/get` で `setup_retry` を見る。`unavailable` の entity への service 呼び出しはエラーにならず空振りする。クラウド系が揃って `Could not contact DNS servers` なら HA コンテナの `/etc/resolv.conf` に nameserver が無い（起動時のホストの中身を写して追従しない）。`docker restart homeassistant` で直る
- REST（`POST /api/states`）で作った entity（騒音・画面時間）は HA を再起動すると次の送信まで消え、registry に載らない（Area に入れられない）

### 機器

- PC への通知（go-hass-agent）は、その PC が起きて HA に繋がっている間しか届かない。sleep 中は 500（`not connected to local push notifications`）で失敗し、後から届かない。スマホは端末の Tailscale が切れていても届く
- 赤外線機器の state は最後に送ったコマンドで、実機の状態ではない。取りこぼしもある。点いたかはカメラで確かめる
- Nature Remo の `climate.aircon` には turn_on も turn_off も無い。止めるのは `climate.set_hvac_mode` の `hvac_mode: "off"`（`turn_off` はエラーで script ごと止まる）。止まっている時に温度・風量を送るとモードが無くて失敗するので、`script.aircon_power_on` を先に通す
- Nature Remo Cloud API を直接叩くなら: センサー値は `GET /1/devices` の `newest_events`（`te` `hu` `il` `mo`、更新は数分〜十数分おき）。リモコンの無い機器は生信号（`{"freq":38,"data":[µs...],"format":"us"}`）を `POST /1/appliances` → `POST /1/appliances/{id}/signals` で登録すると Remo アプリと HA（`remote.*`）に出る。appliance・signal の ID は `private/devices.md`
- Tapo の新しいファームウェア（暗号方式 TPAP）は HA の TP-Link integration が「Unsupported device」で拒否する。Matter 対応品は Matter で取り込む（`matter-server` → HA の Matter integration）。機器は vaio の `iot24`（ap0）に繋ぎ、firewalld の zone `iot` で mdns を開けてある
- C220 の Tapo Control は、ローカル認証がファームウェアで SPAKE2+ に変わったため cloud password（`TPLINK_PASSWORD`）が要る。カメラアカウントだけでは通らない。PTZ・映像は ONVIF の entity を使い、Tapo Control は privacy の switch だけ使う
- SwitchBot は BLE 直結（vaio 内蔵 BT）だと接続が詰まるので Cloud integration を使う
- 手動や Google Home で電球の明るさ・色を変えると、次に消すまでその電球は Adaptive Lighting に追従しない（`manual_control` 属性に入る）
- モニターの on/off は HA の `command_line`（vaio の git 外 `home/config/configuration.yaml`、root 所有。編集後 `command_line.reload`）。HA 専用鍵で vaio に ssh し、`authorized_keys` の `command=` で `home/monitor/dpms.sh` だけに制限している。niri の DPMS off は入力で勝手に復帰するが、state は sysfs を読むので追従する。niri が止まっているとコンソールを `setterm` の blank で消す（sudo -n が要る）
- Tapo は vaio の IoT 用 AP にしか繋がっていないので、RTSP は vaio からしか届かない（`camera.py` は ssh で vaio の ffmpeg を使う）
- 照明が Adaptive Lighting で暗い時間帯（明るさ 2/255 程度）は、黒・紺の物が潰れて判定できない。`--lights` で撮影中だけ 100% にする
- カメラの snap は照明が消えていると真っ黒。go2rtc を止めると HA の entity は `unavailable`

### スマホ（Xiaomi）の Tasker

- 設定値（HA の URL・webhook ID・WiMAX のパスワード・TICKR のアドレス）はスマホの `/sdcard/Download/saru9000/config.properties` にだけ置く。repo には書かない
- Tasker のプロファイル・タスクの書き出し（XML）は agent-private の `home/tasker/`（HTTP のパスを含むので public に置かない）。画面で変えたら「データ → バックアップ」で書き出し直す
- adb で `/sdcard/Android/data/net.dinglisch.android.taskerm/` を先に作ると Tasker から読めなくなる（EACCES）。置き場は `/sdcard/Download/saru9000/`（「すべてのファイルへのアクセス」を許可済み）
- Tasker の画面で編集した後は上部の「保存して適用」で保存する。保存前に強制停止すると消える
- Tasker を adb で画面操作する時の落とし穴: 開くと前回の編集画面から再開することがある（開いたら必ず dump で画面を確かめる）。アクションはドラッグで並べ替えられず、長押しの選択が残ったまま切り取ると複数消える（並べ替えは足して古い方を消す。消しすぎたらタスク編集の「キャンセル」で保存前に戻る）。「アクションを切り替える」は入力を全部消す。一覧の長押し（削除のメニュー）は `input swipe` では効かず `input motionevent DOWN`→`sleep 1.6`→`UP` で出る。選択中のタブをもう一度押すとインポートのメニューが開く
- Tasker の実行ログはオフ。`.bsh` が途中で落ちても何も残らないので、`log()` を挟んで `battery.log` で見る。`common.bsh` を `source` しても `android.content.Context` などは各ファイルで import する
- WiMAX は5回ログインに失敗するとロックされるので、`router.bsh` は1回失敗すると `wimax-login-failed` を置いて止まる。パスワードを確かめてから消す
- HTTP サーバー（ポート 1821）は、パスが違うと本文なしの 503 を返す
- イヤホンのケースの残量は、`EarbudsBattery` の「シェルで実行」（Shizuku を使用）で読む。Shizuku は再起動後、ロック解除の後に自分でワイヤレスデバッグから立ち上がる（Wi-Fi が要る。設定画面の「起動時にスタート」は「要root」と出るがこの機種では root なしで動いた）。立ち上がらなかった時は `boot.bsh`（プロファイル「画面ロック解除」）が再起動1回につき1度通知を出すので、通知から Shizuku の「開始」を押す。止まっている間はケースの値だけ止まる
- 夜のアプリ停止は、HA が「消灯」で Tasker の HTTP サーバー（1821、`rest_command.app_block`）に POST し、`TaskerMCP.AppBlockHttp`（`app_block.bsh`）が止めて、戻す時刻に自分宛ての expire を AlarmManager で予約する。HTTP は vaio の Tailscale IP からしか受けない（スマホの `config.properties` の `app_block_allow_ip`）。スマホの Tailscale が落ちていて HTTP が届かない時だけ、`script.app_block_send` が Companion App 経由の broadcast（`saru9000.APP_BLOCK`）に切り替えて Tasker の返事を待つ。再起動で予約が消えた時は、止めている間だけロック解除（`boot.bsh`）の expire で戻る
- Tasker の「シェルで実行」の「Shizuku を使用」は、`shizuku_server` が生きていても Tasker 用の User Service に繋がらず「Can't bind Shizuku User Service」で固まることがある（11-22 朝、`EarbudsBattery` も同じ経路）。Java コードから Shizuku の `newProcess` を呼ぶと通るので、新しく書くなら `app_block.bsh` の `shell()` を使う。こちらは MCP で作れる
- TaskerMCP は safe mode で、作れるのは `TaskerMCP.` で始まる task だけ（profile は作れない）。Shizuku を使うアクションは MCP では Use Shizuku をオフで作り、adb の画面操作でオンにする。profile も adb の画面操作で作る
- `--dialogMessage` は help に載らないが効く。使用中に suspend するとホームへ戻るだけでダイアログは出ない

### スマホ（Xiaomi）の Sleep as Android

- DISMISS_ALARM に対応しない。アラームを消すのは `ALARM_STATE_CHANGE` のブロードキャスト（`alarm_label` 指定で `alarm_enabled:false`）
- `command_activity` は Companion App の「他のアプリの上に表示」と MIUIOP(10021)（adb で付与）が要る
- SET_ALARM は SKIP_UI でも Sleep as Android の画面が前面に出る
- アプリの webhook URL は vaio の Tailscale IP にする。HA が表示する LAN の URL は使えない（LAN の 8123 は Google の機器にしか開けていない）

### 電話（Linphone）

- マナーモード（着信音ミュート）だと鳴らない
- 同じ sip.linphone.org アカウントでログインした全端末（xiaomi・BV5200）が鳴り、どれかが出れば他は止まる
- baresip の設定の落とし穴は `home/phone/baresip/config` のコメント

### Google

- 機器を増やすと、Google Home には載るが Offline のまま（声では「〇〇は現在利用できません」）。Google が機器を登録した後に `docker restart matter-hub` すると、Google が購読し直して online になる。`matter_hub.py kick` だけでは直らないことがある。script は Google からコンセント型の機器に見え、ON で実行・すぐ OFF に戻る
- Google 側の機器名をルーティンの開始フレーズと同じにすると、そのフレーズで「うまく理解できませんでした」になる。Google は HA 側の改名に追従しないので、名前を変えるなら entity ID ごと変えて別の機器として登録させる
- Cast（Nest Mini 等）で鳴らすと、スピーカーが HA の `/api/tts_proxy/*.mp3` を取りに来る。vaio の firewalld（建物 Wi-Fi 側）は 8123 を Google の機器の IP にだけ開けてある（建物 Wi-Fi は共有なので全開放しない）。IP が DHCP で変わると「Failed to cast media ... Reachable from the cast device」で無音になる
- Google スピーカーの返事は vaio のマイクではかなり小さく録れる。`voice.py` は `dynaudnorm` で持ち上げてから文字起こしする

### センサー・地図

- 騒音 sensor の値は dBFS（マイク入力の上限を 0 とした相対値）で dB SPL ではない。マイクの音量・ゲインは会話エージェントと共有なので触らない
- 画面時間が 0 分のままなら、まず `sensor.iiyama_active_app` が `none` で止まっていないか見る（go-hass-agent 側が niri の前面ウィンドウを取れていない）
- 騒音・画面時間・外気などの表示用 sensor を dailybuild の取得対象に足さない（dailybuild は元の sensor を読む。経路が2本になる）
- 大気質: WAQI（`sensor.waqi_*`）は指数、Google は濃度で、同じ PM2.5 でも直接比べられない。`google_aqi_jp` は数値でなくレベル文字列
- ダッシュボード「家」は `home/dashboards/home.yaml` が正本。変えたら merge → vaio で pull、ブラウザの再読み込みで反映
- エネルギー・照明・空調などの組み込みパネルは既定でサイドバーに出ない。出すのは `ha.py ws frontend/update_panel '{"url_path": "energy", "show_in_sidebar": true}'`
- ダッシュボードの `url_path` はハイフン必須で、作った後は変えられない
- 地図カードの JS（`/local/map-card.js`）を更新したら、resource の URL のクエリのバージョンを変える（変えないとブラウザのキャッシュが残る）
- 花粉のタイルの URL（キー入り）は vaio の git 外 `home/config/secrets.yaml` の `pollen_tile_url`
- 花粉のタイルは Google Pollen API の `TREE_UPI`（スギ・ヒノキを含む）。植物単位のタイルは 400 で使えない
- 浸水深のタイル（国土地理院「重ねるハザードマップ」）は出典表示「国土地理院（重ねるハザードマップ）」を残す。想定区域の外は 404 で透明になる
- 表示条件付きのカード（花粉・防災の地図）を確かめる時は、しきい値を一時的に変えて `template.reload` し、確認後に戻す
- entity に `latitude` / `longitude` attribute を付けると左メニューの「マップ」に載り、遠い地点まで含めようとして縮小される。地震などの遠い地点の座標は attribute に入れない
