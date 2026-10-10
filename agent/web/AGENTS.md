# agent/web

Setup, assets, dev server, build and URL parameters are in README.md. This file holds only what the code does not tell.

- Test: `npm test`
- Never commit anything under `public/` except `stage.json`: the model, motion and music are third-party (see README.md)
- Close a headless browser (Playwright etc.) as soon as you have checked the stage. Without a GPU, WebGL is drawn by SwiftShader on the CPU and the render loop keeps about 10 cores busy on mouse
- FPS measured in headless Chrome is not the real figure (software WebGL)
- three.js dropped its MMD loaders in r172 and has no maintained successor; babylon-mmd is the one in use
