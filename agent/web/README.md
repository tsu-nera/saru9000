# agent/web

Browser stage for core: renders あにまさ式 Miku (Babylon.js + babylon-mmd), speaks what core sends with lip sync,
changes expressions and dances (「ミクミクにして」「テルユアワールド」, or 「踊って」 to choose).

## Assets

Put these under `public/` (not committed: the model is Copyright CRYPTON with unverified
redistribution terms, and the motion is not for commercial use):

- `Miku.pmd` and its textures
- `idle.vmd`: stage idle motion (optional; loops if present, the stage works without it).
  Only its bone tracks are used, so mouth and blink stay under the stage's control
- `cyberstage/`: the stage set, glb version of [サイバーステージ](https://booth.pm/ja/items/3964661) by プリメロ工房
  (`CyberStage_AB.glb`, `CyberStage_C_Screen.glb`, `CyberStage_D.glb`). Redistribution is forbidden, so never commit it.
  Optional: without it the stage logs one warning and runs as usual
- A VMD and its music per dance, named after core's motion name (`agent/core/config.json` "dances").
  Music is `.mp3` or `.wav` (`.m4a` is served without an audio content type and is not found).
  Where each comes from is in issue #25; never commit them
  - `mikumiku.vmd` / `mikumiku.mp3`: みくみくにしてあげる♪
  - `tellyourworld.vmd` / `tellyourworld.mp3`: Tell Your World, made with `tools/vmd_retarget.py` (below)
  - `tellyourworld_full.vmd` / `tellyourworld_full.mp3`: the same, uncut (「テルユアワールド完全版」)

## Making a dance

A VMD made for a model with semi-standard bones (上半身2・腕捩・手捩) leaves those moves out on
あにまさ式 Miku. `tools/vmd_retarget.py` folds them into the bones above, merges a separate lip VMD
(え is spread over あ and い), and can cut the motion at a start and an end frame:

```sh
python3 tools/vmd_retarget.py public/Miku.pmd body.vmd public/<name>.vmd --lip lip.vmd [--start <frame>] [--end <frame>]
```

Cut the music at the same points with ffmpeg (`adelay` or `atrim=start=` to line it up with the motion, `atrim` and
`afade` to end it), as `.mp3`. Check the result on the stage with sound: the offset is easy to
get wrong by half a second.

## Develop

```sh
npm install
npm run dev     # http://localhost:5173/
```

Start core first; the dev server proxies `/ws` to `http://127.0.0.1:8765`.
Click the overlay once (browser autoplay policy), then type into the input box and press Enter.
The `mode:` label in the HUD switches how core answers what it hears (wake word only / everything); it is not saved.

## Build

```sh
npm run build   # dist/index.html (stage)
```

core serves `dist/` at `http://<host>:8765/`.

## Test

```sh
npm test
```

## Settings

`public/stage.json` holds the defaults (camera position). To change them on one machine only, put just the keys you want to change in `public/stage.local.json` (gitignored), run `npm run build` and reload the page. URL parameters override both files.

## Keys

- `L`: show or hide the log screen behind the avatar (not saved; a reload goes back to `screen.enabled` / `?screen=`)
- `V`: show or hide the stage set (not saved; a reload goes back to `venue.enabled` / `?venue=`). A dance shows it and its end puts back the state from before the dance

## Query parameters

- `?autoplay=1`: skip the click-to-start overlay (needs `--autoplay-policy=no-user-gesture-required`)
- `?nophysics=1`: disable physics
- `?distance=` / `?height=` / `?elevation=`: override the camera settings for one page load
- `?screen=0` / `?screen=1`: hide / show the log screen behind the avatar (default: `screen.enabled` in `stage.json`)
- `?venue=0` / `?venue=1`: hide / show the stage set (default: `venue.enabled` in `stage.json`)
- `?model=/Other.pmd`: model path
