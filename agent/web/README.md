# agent/web

Browser stage for core: renders あにまさ式 Miku (Babylon.js + babylon-mmd), speaks what core sends with lip sync,
changes expressions and dances on 「ミクミクにして」.

## Assets

Put these under `public/` (not committed: the model is Copyright CRYPTON with unverified
redistribution terms, and the motion is not for commercial use):

- `Miku.pmd` and its textures
- `idle.vmd`: stage idle motion (optional; loops if present, the stage works without it).
  Only its bone tracks are used, so mouth and blink stay under the stage's control
- `mikumiku.vmd`: the dance (あずのMMD倉庫 `mikumiku.zip`, renamed; see issue #25)
- `mikumiku.mp3` (or `.wav` / `.m4a`, first found wins): the music for the dance. Buy it
  (ika's single, 1:39); never commit it

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

## Query parameters

- `?autoplay=1`: skip the click-to-start overlay (needs `--autoplay-policy=no-user-gesture-required`)
- `?nophysics=1`: disable physics
- `?distance=` / `?height=` / `?elevation=`: override the camera settings for one page load
- `?model=/Other.pmd`: model path
