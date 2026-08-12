import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const basePath = process.env.VITE_APP_BASE_PATH || "/";
const normalizedBasePath = basePath === "/" ? "/" : `/${basePath.replace(/^\/+|\/+$/g, "")}/`;
const apiProxyPath = normalizedBasePath === "/" ? "/api" : `${normalizedBasePath.slice(0, -1)}/api`;

export default defineConfig({
  base: basePath,
  plugins: [react()],
  server: {
    proxy: {
      [apiProxyPath]: {
        target: "http://127.0.0.1:8000",
        rewrite: path => normalizedBasePath === "/" ? path : path.replace(new RegExp(`^${normalizedBasePath.slice(0, -1)}`), ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    server: {
      deps: { inline: ["animal-island-ui"] },
    },
  },
});
