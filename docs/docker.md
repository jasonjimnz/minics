# Running MiniCS Lite in Docker

MiniCS Lite ships as a **server container**: the same Flask app the desktop
shell wraps, served on HTTP with the entire store (config, SQLite, Chroma,
graph, documents) kept in a single mounted volume. Use it to run the studio on
a home server, a VPS, or alongside your model servers.

---

## 1. What the image does

| Aspect | Behaviour |
| --- | --- |
| Base | `python:3.13-slim`, package installed from `src/` with `pip install .` |
| Entrypoint | `minics serve --host 0.0.0.0 --no-browser` (no GUI needed) |
| Store | `/data` — set via the `MINICS_HOME` environment variable, declared as a `VOLUME` |
| User | Non-root `minics` user (uid 1000) |
| Health | `HEALTHCHECK` polls `GET /healthz` every 30 s |
| First run | The store (folder structure + SQLite migrations) is **auto-created** on startup, then the setup wizard is available in the UI |

There is **no authentication** — the server is meant for a trusted network
(localhost, LAN, VPN). Do not expose it directly to the internet.

## 2. Build and run

```bash
docker build -t minics-lite .
docker run -d --name minics-lite \
  -p 8765:8765 \
  -v minics-data:/data \
  minics-lite
```

Then open `http://localhost:8765`. On first start:

1. the container creates `/data` (the full `~/.minics` layout) automatically,
2. the UI opens on the setup screen — configure your LLM + embedding
   endpoints in **Settings**, hit *Test connection*, *Finish setup*,
3. import documents and start authoring; everything persists in the volume.

### Bind mounts instead of named volumes

```bash
docker run -d -p 8765:8765 \
  -v /srv/minics:/data \
  minics-lite
```

With a bind mount the container runs as uid 1000, so make the host directory
writable for it: `chown -R 1000:1000 /srv/minics` (or run with
`--user "$(id -u):$(id -g)"` on a directory you own).

## 3. Docker Compose (recommended)

A ready-made [`docker-compose.yml`](https://github.com/jasonjimnz/minichat_studio/blob/main/docker-compose.yml) ships in the repo:

```yaml
services:
  minics:
    build: .
    image: minics-lite
    container_name: minics-lite
    ports:
      - "8765:8765"
    volumes:
      - minics-data:/data
    restart: unless-stopped

volumes:
  minics-data:
```

```bash
docker compose up -d --build
docker compose logs -f          # follow startup / job activity
docker compose down             # stops; the minics-data volume persists
```

## 4. Configuration inside the container

All the usual mechanisms work (see [configuration.md](configuration.md)):

- **UI** — the Settings screen writes `config.json` inside the volume.
- **CLI in the container** —

  ```bash
  # interactive wizard
  docker compose exec minics minics setup

  # or non-interactive, e.g. pointing at an Ollama host gateway
  docker compose exec minics minics setup \
    --base-url http://host.docker.internal:11434/v1 \
    --model llama3.1-instruct \
    --embedding-model nomic-embed-text

  docker compose exec minics minics models
  ```

- **Mounted config** — pre-create `/data/config.json` on the host and mount
  the folder; it is read on startup.

When pointing MiniCS at services on the *host machine* from inside the
container, use `http://host.docker.internal:PORT/v1` (Docker Desktop) or the
host's LAN address; on Linux add
`--add-host=host.docker.internal:host-gateway` to the run command.

## 5. Useful operations

```bash
docker compose exec minics minics info        # show resolved paths
docker compose exec minics minics reindex     # rebuild vector index + graph
docker compose exec minics minics export my-collection -o /tmp/out.jsonl --format jsonl
docker compose cp minics-lite:/tmp/out.jsonl ./out.jsonl
```

Backups are a copy of the volume: stop the container (for a consistent SQLite
snapshot) and copy `minics-data`.

## 6. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `GET /` unreachable | Container still starting (first pip-less start is fast, but health has a 15 s grace) — check `docker logs minics-lite`. |
| Endpoint connection test fails | The model server is not reachable from inside the container — use `host.docker.internal` / LAN addresses, not `localhost`. |
| Permission denied on bind mount | The container runs as uid 1000 — `chown -R 1000:1000` the mounted directory. |
| Graph features unavailable | LadybugDB failed to open its database file — check that the volume is writable; the rest of the app keeps working (retrieval degrades to vectors-only). |
| Reset everything | `docker compose down -v` deletes the store volume. |

## 7. How the pieces fit

The image reuses the exact same code paths as the desktop app: `minics serve`
→ `run_server()` → `create_app(ctx)` on an `AppContext` whose home is
`/data`. First-run initialisation is the CLI contract — every command that
needs the store (including `serve`) creates the folder structure and applies
SQLite migrations before doing anything else (see
[backend.md](backend.md), the CLI section).
