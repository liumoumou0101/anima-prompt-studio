import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  build: {
    outDir: "../src/anima_prompt_studio/web_gallery/dist",
    emptyOutDir: true,
  },
});
