import {defineConfig, loadEnv} from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.V3_API_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      proxy: {
        // Preserve the browser's loopback Host so the API can enforce exact
        // Origin (including the dev port) just as it does in packaged mode.
        "/api": {target, changeOrigin: false},
        "/health": {target, changeOrigin: false},
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: true,
    },
  };
});
