# PocketProWS frontend: Vite dev server, same as the native flow, so the
# /api proxy and the backend identity pairing behave identically.
# Container port is fixed at 3003; start.sh --docker publishes it on the
# resolved host port (3003, bumped +1 past foreign holders).
FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 3003

# vite.config.js pins the dev server to 127.0.0.1 for the native flow;
# inside the container it must bind 0.0.0.0 or the published port cannot
# reach it. The CLI flags override the config's host/port.
CMD ["./node_modules/.bin/vite", "--host", "0.0.0.0", "--port", "3003", "--strictPort"]
