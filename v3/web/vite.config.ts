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
        "/api": {target, changeOrigin: true},
        "/health": {target, changeOrigin: true},
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: true,
    },
  };
});
