---
name: minics-server
description: Run MiniCS headless — `minics serve` (browser-only Flask server), the Docker/GHCR server image, Compose, ports/volumes and reverse-proxy notes. Use when deploying MiniCS as a server, in Docker, or accessing it remotely.
---

# MiniCS server

## Browser server (no desktop shell)

```bash
minics serve --port 8800
minics serve --host 0.0.0.0 --port 8765 --no-browser
```

`minics serve` auto-creates and migrates the store on first run — no separate
init step. `minics app` instead launches the PyWebView desktop shell.

## Docker (GHCR image)

A prebuilt server image is published on GHCR for every release:

```bash
docker pull ghcr.io/jasonjimnz/minics:latest      # or a version tag, e.g. :0.4.0
docker run -d -p 8765:8765 -v minics-data:/data ghcr.io/jasonjimnz/minics:latest
```

- The whole store lives in the `/data` volume and auto-creates on first start.
- Open `http://localhost:8765` and finish setup in the UI.
- Build locally instead: `docker compose up -d --build`.

## Endpoints worth knowing

```bash
curl http://127.0.0.1:8765/api/health
curl http://127.0.0.1:8765/api/overview
```

Full REST reference: `docs/api.md` (HTTP API page of the documentation).

## Reverse proxy notes

- The UI consumes **Server-Sent Events** (`/api/events`) — disable buffering
  for the SSE route (nginx: `proxy_buffering off;`).
- The server binds to loopback by default; only expose it on a trusted network.
- The LLM/embedding endpoints MiniCS talks to are configured in the store's
  config (`~/.minics/config.json` inside the container), not via env vars.
