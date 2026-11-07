import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { port: 3003, proxy: { "/api": "http://127.0.0.1:5003" } },
  test: { environment: "jsdom" },
});
