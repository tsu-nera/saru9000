import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

export default defineConfig({
  build: {
    // The dance page uses top-level await.
    target: "esnext",
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL("index.html", import.meta.url)),
        dance: fileURLToPath(new URL("dance.html", import.meta.url)),
      },
    },
  },
  server: {
    proxy: {
      "/ws": { target: "http://127.0.0.1:8765", ws: true },
    },
  },
  test: { environment: "node" },
});
