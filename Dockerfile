# MiniCS Lite (Mini ChatML Studio Lite) — server container.
#
# Build:  docker build -t minics-lite .
# Run:    docker run -d -p 8765:8765 -v minics-data:/data minics-lite
#
# The store lives in /data (set via MINICS_HOME), so mount a volume there to
# keep datasets, documents, the vector index and the graph across restarts.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TOKENIZERS_PARALLELISM=false \
    MINICS_HOME=/data

WORKDIR /app

# Install the package (deps resolve for linux wheels on PyPI).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Non-root runtime; /data is the mounted store.
RUN useradd --create-home --uid 1000 minics \
    && mkdir -p /data \
    && chown -R minics:minics /data /app
USER minics

EXPOSE 8765
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=4)" || exit 1

# First run auto-creates /data and the config; finish setup in the UI
# (Settings) or via `docker compose exec minics minics setup ...`.
CMD ["minics", "serve", "--host", "0.0.0.0", "--no-browser"]
