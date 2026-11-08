import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Ports come from start-dev.sh (POCKETPROWS_BE_PORT / POCKETPROWS_FE_PORT),
// which bumps +1 while the default is taken. Defaults keep the old behaviour.
const bePort = Number(process.env.POCKETPROWS_BE_PORT || 5003);
const fePort = Number(process.env.POCKETPROWS_FE_PORT || 3003);

export default defineConfig({
  plugins: [react()],
  // host is pinned to 127.0.0.1: vite's default "localhost" can resolve to
  // ::1, which would leave 127.0.0.1 unbound and break the health check
  // and the printed URL. The backend also binds 127.0.0.1.
  server: { host: "127.0.0.1", port: fePort, strictPort: true, proxy: { "/api": `http://127.0.0.1:${bePort}` } },
  test: { environment: "jsdom" },
});
