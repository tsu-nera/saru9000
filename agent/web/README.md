# agent/web

Browser stage for core: renders あにまさ式 Miku (Babylon.js + babylon-mmd), speaks what core sends with lip sync,
changes expressions and dances (「ミクミクにして」「テルユアワールド」, or 「踊って」 to choose).

## Assets

Put these under `public/` (not committed: the model is Copyright CRYPTON with unverified
redistribution terms, and the motion is not for commercial use):

- `Miku.pmd` and its textures
- `idle.vmd`: stage idle motion (optional; loops if present, the stage works without it).
  Only its bone tracks are used, so mouth and blink stay under the stage's control
- A VMD and its music per dance, named after core's motion name (`agent/core/config.json` "dances").
  Music is `.mp3` or `.wav` (`.m4a` is served without an audio content type and is not found).
  Where each comes from is in issue #25; never commit them
  - `mikumiku.vmd` / `mikumiku.mp3`: みくみくにしてあげる♪
  - `tellyourworld.vmd` / `tellyourworld.mp3`: Tell Your World, made with `tools/vmd_retarget.py` (below)

## Making a dance

A VMD made for a model with semi-standard bones (上半身2・腕捩・手捩) leaves those moves out on
あにまさ式 Miku. `tools/vmd_retarget.py` folds them into the bones above, merges a separate lip VMD
(え is spread over あ and い), and can cut the motion at a frame:

```sh
python3 tools/vmd_retarget.py public/Miku.pmd body.vmd public/<name>.vmd --lip lip.vmd [--end <frame>]
```

Cut the music at the same point with ffmpeg (`adelay` to line it up with the motion, `atrim` and
`afade` to end it), as `.mp3`. Check the result on the stage with sound: the offset is easy to
get wrong by half a second.

## Develop

```sh
npm install
npm run dev     # http://localhost:5173/
```

Start core first; the dev server proxies `/ws` to `http://127.0.0.1:8765`.
Click the overlay once (browser autoplay policy), then type into the input box and press Enter.
The `L` key shows or hides the log screen behind Miku (core's log, the conversation, Claude's tool calls); it is not saved.
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

`public/stage.json` holds the defaults (camera position, `screen.enabled` for the log screen). To change them on one machine only, put just the keys you want to change in `public/stage.local.json` (gitignored), run `npm run build` and reload the page. URL parameters override both files.

## Query parameters

- `?autoplay=1`: skip the click-to-start overlay (needs `--autoplay-policy=no-user-gesture-required`)
- `?nophysics=1`: disable physics
- `?distance=` / `?height=` / `?elevation=`: override the camera settings for one page load
- `?screen=0|1`: hide or show the log screen for one page load
- `?model=/Other.pmd`: model path
