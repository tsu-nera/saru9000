# agent/web

Browser stage for saru-core: renders あにまさ式 Miku (Babylon.js + babylon-mmd), plays the
speech core sends, moves the mouth to match, changes the face on `speak.expression` /
`expression` (fading over ~0.2 s), and blinks at random intervals except while the face closes
the eyes, and dances to the music when core sends `motion {name: "dance"}`.

## Assets

Put these under `public/` (not committed: the model is Copyright CRYPTON with unverified
redistribution terms, and the motion is not for commercial use):

- `Miku.pmd` and its textures
- `idle.vmd`: stage idle motion (optional; loops if present, the stage works without it).
  Only its bone tracks are used, so mouth and blink stay under the stage's control
- `mikumiku.vmd`: the dance (あずのMMD倉庫 `mikumiku.zip`, renamed; see issue #25)
- `mikumiku.mp3` (or `.wav` / `.m4a`, first found wins): the music for the dance. Buy it
  (ika's single, 1:39); never commit it

## Dance

`motion {name: "dance"}` plays `mikumiku.vmd` with its morph tracks, so during the dance the
mouth, blinking and face are the VMD's (speech lip sync, blinking and expressions are ignored).
The music is synced by babylon-mmd's `StreamAudioPlayer` (`MmdRuntime.setAudioPlayer`: the
animation follows the audio clock). When it ends the stage goes back to the idle motion and sends
`motion_ended`. If the VMD or the music is missing it logs one line and sends `motion_ended` at
once, so core never hangs.

## Develop

```sh
npm install
npm run dev     # http://localhost:5173/
```

Start saru-core first; the dev server proxies `/ws` to `http://127.0.0.1:8765`.
Click the overlay once (browser autoplay policy), then type into the input box and press Enter.

## Build

```sh
npm run build   # dist/index.html (stage)
```

saru-core serves `dist/` at `http://<host>:8765/`.

## Test

```sh
npm test
```

## Query parameters

- `?autoplay=1`: skip the click-to-start overlay (needs `--autoplay-policy=no-user-gesture-required`)
- `?nophysics=1`: disable physics
- `?distance=` / `?height=`: camera distance and look-at height (defaults 28 and 10; the model is ~20 tall)
- `?model=/Other.pmd`: model path
