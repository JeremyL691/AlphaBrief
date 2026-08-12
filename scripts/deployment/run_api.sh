#!/bin/bash
# AlphaBrief API launchd wrapper (reference copy).
#
# Lives outside Desktop in production (~/.alphabrief/run_api.sh) to avoid
# macOS TCC permission issues. This copy is the versioned reference;
# copy it to ~/.alphabrief/ and adjust ALPHABRIEF_SRC to the deployed
# source checkout before wiring it into launchd.
#
# Notes:
#   * SSL_CERT_FILE points the python.org framework build at the system
#     CA bundle; without it urllib fails with CERTIFICATE_VERIFY_FAILED.
#   * ALPHABRIEF_DATA_DIR keeps the API database separate from the
#     scheduler's writer-locked DuckDB file (single-writer).
#   * ALPHABRIEF_AI_OBSERVATION_DIR makes the /api/v1/ai/* read-only
#     endpoints serve the scheduler's exported ai_cycle_*.json files;
#     the API process cannot open the scheduler DB while it is running.

set -uo pipefail

export HOME="${HOME:-/Users/jeremyliu}"
cd /tmp || exit 1
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
export SSL_CERT_FILE=/etc/ssl/cert.pem
export ALPHABRIEF_LIVE_TRADING_ENABLED=false
export ALPHABRIEF_DATA_DIR="${ALPHABRIEF_DATA_DIR:-$HOME/.alphabrief/api-data}"
export ALPHABRIEF_AI_OBSERVATION_DIR="${ALPHABRIEF_AI_OBSERVATION_DIR:-$HOME/.alphabrief/reports/paper_observation}"
# Real model provider for API-generated briefs/debates/evaluations.
# Fill in the real key in the deployed copy only.
export OPENAI_BASE_URL=https://opencode.ai/zen/go
export OPENAI_API_KEY=REPLACE_WITH_OPENAI_API_KEY
# The scheduler holds the writer lock on its own DB; the API serves
# scheduler status/heartbeats/alerts/freezes from a refreshed copy of
# this DB instead of the (empty) API database.
export ALPHABRIEF_SCHEDULER_DB_DIR="${ALPHABRIEF_SCHEDULER_DB_DIR:-$HOME/.alphabrief/data}"
export ALPHABRIEF_API_URL=http://127.0.0.1:8000

# Deployed source checkout (the venv itself lives outside Desktop).
ALPHABRIEF_SRC="${ALPHABRIEF_SRC:-$HOME/.alphabrief/alphabrief-src}"

# Mirror pyproject.toml [tool.pytest] pythonpath so launchd can import
# source-checkout packages while the venv itself lives outside Desktop.
export PYTHONPATH="${ALPHABRIEF_SRC}/apps/api/src:${ALPHABRIEF_SRC}/apps/cli/src:${ALPHABRIEF_SRC}/packages/alphabrief-backtest/src:${ALPHABRIEF_SRC}/packages/alphabrief-acceptance/src:${ALPHABRIEF_SRC}/packages/alphabrief-core/src:${ALPHABRIEF_SRC}/packages/alphabrief-data/src:${ALPHABRIEF_SRC}/packages/alphabrief-execution/src:${ALPHABRIEF_SRC}/packages/alphabrief-gym/src:${ALPHABRIEF_SRC}/packages/alphabrief-models/src:${ALPHABRIEF_SRC}/packages/alphabrief-news/src:${ALPHABRIEF_SRC}/packages/alphabrief-research/src:${ALPHABRIEF_SRC}/packages/alphabrief-review/src:${ALPHABRIEF_SRC}/packages/alphabrief-risk/src:${ALPHABRIEF_SRC}/packages/alphabrief-strategy/src:${ALPHABRIEF_SRC}/packages/alphabrief-trader/src:${ALPHABRIEF_SRC}/tests:${PYTHONPATH:-}"

exec "$HOME/.alphabrief/venv/bin/alphabrief" \
  serve serve --host 127.0.0.1 --port 8000
