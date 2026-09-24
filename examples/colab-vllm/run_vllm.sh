#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_vllm.sh — start vLLM in the background with TWO servers:
#
#   1. a chat LLM   (default: Qwen/Qwen2.5-1.5B-Instruct)   on :8001
#   2. an embedding model (default: BAAI/bge-m3)             on :8002
#
# Dependency install (uv, torch stack, vLLM) is documented in the notebook's
# markdown and must be run from a terminal BEFORE this script — it is not
# handled here.
#
#   bash run_vllm.sh          # start both servers, wait until healthy
#   bash run_vllm.sh stop     # kill both servers
#
# Logs: $VLLM_LOG_DIR (default /tmp/minics-vllm-logs)
# ---------------------------------------------------------------------------
set -euo pipefail

LLM_MODEL="${LLM_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"
EMBED_MODEL="${EMBED_MODEL:-BAAI/bge-m3}"
LLM_PORT="${LLM_PORT:-8001}"
EMBED_PORT="${EMBED_PORT:-8002}"
LLM_GPU_FRAC="${LLM_GPU_FRAC:-0.45}"     # T4-friendly split; tune to your GPU
EMBED_GPU_FRAC="${EMBED_GPU_FRAC:-0.30}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"  # 16K context: room for grounding + long replies
LOG_DIR="${VLLM_LOG_DIR:-/tmp/minics-vllm-logs}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-900}"  # first start downloads the weights

mkdir -p "$LOG_DIR"

log()  { echo "[vllm-launcher] $*"; }
fail() { echo "[vllm-launcher] ERROR: $*" >&2; exit 1; }

stop_all() {
  log "stopping any running vLLM servers..."
  pkill -f "vllm serve" 2>/dev/null || true
  pkill -f "from vllm"   2>/dev/null || true
  sleep 3
}

wait_healthy() {
  local port="$1" name="$2" waited=0
  until curl -sf "http://127.0.0.1:${port}/health" > /dev/null 2>&1; do
    sleep 5
    waited=$((waited + 5))
    if ! pgrep -f "vllm serve" > /dev/null; then
      echo "---- last log lines (${name}) ----" >&2
      tail -n 40 "${LOG_DIR}/${name}.log" >&2 || true
      fail "${name} process died — see ${LOG_DIR}/${name}.log"
    fi
    if [ "$waited" -ge "$HEALTH_TIMEOUT" ]; then
      fail "${name} not healthy after ${HEALTH_TIMEOUT}s — see ${LOG_DIR}/${name}.log"
    fi
  done
  log "${name} is healthy on :${port} (waited ${waited}s)"
}

if [ "${1:-}" = "stop" ]; then
  stop_all
  log "stopped."
  exit 0
fi

command -v curl > /dev/null || fail "curl is required"
command -v vllm > /dev/null || fail "vLLM is not installed — run the dependency install commands from the notebook's markdown section (terminal)"

# Preflight: torch / torchaudio / torchvision must be built for the same
# CUDA version, or `vllm serve` dies on import.
PY="$(command -v python3 || command -v python)"
if ! "$PY" -c "import torch, torchaudio, torchvision" > /dev/null 2>&1; then
  fail "torch/torchaudio/torchvision CUDA mismatch (or missing). Fix with:
    uv pip uninstall --system torch torchvision torchaudio
    uv pip install --system torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130
    uv pip install --system vllm
  (see the notebook's install section), then re-run this script."
fi
log "preflight OK: the torch stack imports cleanly"

stop_all

log "starting chat LLM:  ${LLM_MODEL}  on :${LLM_PORT} (gpu ${LLM_GPU_FRAC})"
nohup vllm serve "${LLM_MODEL}" \
  --port "${LLM_PORT}" \
  --gpu-memory-utilization "${LLM_GPU_FRAC}" \
  --max-model-len "${MAX_MODEL_LEN}" \
  > "${LOG_DIR}/llm.log" 2>&1 &

# Note: no --task/--runner flag needed - vLLM auto-detects bge-m3 as a
# pooling (embedding) model from its architecture.
log "starting embedder:  ${EMBED_MODEL}  on :${EMBED_PORT} (gpu ${EMBED_GPU_FRAC})"
nohup vllm serve "${EMBED_MODEL}" \
  --port "${EMBED_PORT}" \
  --gpu-memory-utilization "${EMBED_GPU_FRAC}" \
  --max-model-len 8192 \
  > "${LOG_DIR}/embed.log" 2>&1 &

wait_healthy "${LLM_PORT}"   "llm"
wait_healthy "${EMBED_PORT}" "embed"

log "both servers are up:"
log "  chat LLM    -> http://127.0.0.1:${LLM_PORT}/v1   (${LLM_MODEL})"
log "  embeddings  -> http://127.0.0.1:${EMBED_PORT}/v1 (${EMBED_MODEL})"
log "logs in ${LOG_DIR}"
