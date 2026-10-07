# agent/web

Browser stage for saru-core: renders あにまさ式 Miku (Babylon.js + babylon-mmd), plays the
speech core sends, and moves the mouth to match. `dance.html` is the standalone VMD dance
viewer (kept until the dance is folded into the stage).

## Assets

Put these under `public/` (not committed: the model is Copyright CRYPTON with unverified
redistribution terms, and the motion is not for commercial use):

- `Miku.pmd` and its textures
- `mikumiku.vmd` (dance page only)

## Develop

```sh
npm install
npm run dev     # http://localhost:5173/  (dance viewer: /dance.html)
```

Start saru-core first; the dev server proxies `/ws` to `http://127.0.0.1:8765`.
Click the overlay once (browser autoplay policy), then type into the input box and press Enter.

## Build

```sh
npm run build   # dist/index.html (stage) + dist/dance.html
```

saru-core serves `dist/` at `http://<host>:8765/`.

## Test

```sh
npm test
```

## Query parameters

- `?autoplay=1`: skip the click-to-start overlay (needs `--autoplay-policy=no-user-gesture-required`)
- `?nophysics=1`: disable physics
- `?model=/Other.pmd`: model path
