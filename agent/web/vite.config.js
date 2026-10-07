import { defineConfig } from "vite";

export default defineConfig({
  build: {
    // The stage uses top-level await.
    target: "esnext",
  },
  server: {
    proxy: {
      "/ws": { target: "http://127.0.0.1:8765", ws: true },
    },
  },
  test: { environment: "node" },
});
