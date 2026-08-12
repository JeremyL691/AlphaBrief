#!/bin/bash
# AlphaBrief Scheduler launchd wrapper (reference copy).
#
# Lives outside Desktop in production (~/.alphabrief/run_scheduler.sh) to
# avoid macOS TCC permission issues. This copy is the versioned reference;
# copy it to ~/.alphabrief/ and adjust ALPHABRIEF_SRC to the deployed
# source checkout before wiring it into launchd.
#
# Secrets below are PLACEHOLDERS on purpose. Fill in the real values in
# the deployed copy only; never commit real credentials to this repo.
#
# The AI Trading Committee requires a valid OPENAI_API_KEY for the
# configured provider. A placeholder/redacted key silently produces
# zero-vote cycles (outcome=provider_error); the scheduler does not
# validate the key at startup.

set -uo pipefail

export HOME="${HOME:-/Users/jeremyliu}"
cd /tmp || exit 1
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
export SSL_CERT_FILE=/etc/ssl/cert.pem

# --- Broker credentials (fill in the deployed copy) ---
export ALPHABRIEF_OANDA_TOKEN=REPLACE_WITH_OANDA_TOKEN
export ALPHABRIEF_OANDA_ACCOUNT_ID=REPLACE_WITH_OANDA_ACCOUNT_ID

export ALPHABRIEF_LIVE_TRADING_ENABLED=false
export ALPHABRIEF_DATA_DIR="${ALPHABRIEF_DATA_DIR:-$HOME/.alphabrief/data}"
export ALPHABRIEF_AI_TRADING_ENABLED=true
export ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED=true
export ALPHABRIEF_AI_SCHEDULER_UNIVERSE=EUR_USD,GBP_USD,USD_JPY
export ALPHABRIEF_AI_MODEL_PROVIDER=openai
export ALPHABRIEF_AI_MODEL_NAME=deepseek-v4-flash
export ALPHABRIEF_AI_MODEL_TIMEOUT_SECONDS=30
export OPENAI_BASE_URL=https://opencode.ai/zen/go
# --- Real key goes in the deployed copy only ---
export OPENAI_API_KEY=REPLACE_WITH_OPENAI_API_KEY
export ALPHABRIEF_AI_MARKET_DATA_SOURCE=yahoo
export ALPHABRIEF_AI_MARKET_DATA_INTERVAL=1d
export ALPHABRIEF_AI_MARKET_DATA_LOOKBACK_DAYS=10
export ALPHABRIEF_AI_PRE_CYCLE_INGEST_ENABLED=true
export ALPHABRIEF_AI_NEWS_SOURCE=rss
export ALPHABRIEF_AI_NEWS_FEEDS=marketwatch-rss,reuters-rss,bloomberg-atom
export ALPHABRIEF_AI_NEWS_LOOKBACK_HOURS=24
export ALPHABRIEF_AI_NEWS_LIMIT=30

# Free API keys — sign up at the linked URLs, then uncomment:
# FRED: https://fred.stlouisfed.org/docs/api/api_key.html
# export FRED_API_KEY=your_fred_key_here
# Alpha Vantage: https://www.alphavantage.co/support/#api-key
# export ALPHAVANTAGE_API_KEY=your_alphavantage_key_here

# Deployed source checkout (the venv itself lives outside Desktop).
ALPHABRIEF_SRC="${ALPHABRIEF_SRC:-$HOME/.alphabrief/alphabrief-src}"

# Set pythonpath so the project packages are importable. The AI trading
# committee imports alphabrief_trader (+models/news/research/...) at
# scheduler import time, so every package path the project ships must
# be on PYTHONPATH. Mirror the full pyproject.toml [tool.pytest]
# pythonpath list.
export PYTHONPATH="${ALPHABRIEF_SRC}/packages/alphabrief-backtest/src:${ALPHABRIEF_SRC}/packages/alphabrief-acceptance/src:${ALPHABRIEF_SRC}/packages/alphabrief-core/src:${ALPHABRIEF_SRC}/packages/alphabrief-data/src:${ALPHABRIEF_SRC}/packages/alphabrief-execution/src:${ALPHABRIEF_SRC}/packages/alphabrief-gym/src:${ALPHABRIEF_SRC}/packages/alphabrief-models/src:${ALPHABRIEF_SRC}/packages/alphabrief-news/src:${ALPHABRIEF_SRC}/packages/alphabrief-research/src:${ALPHABRIEF_SRC}/packages/alphabrief-review/src:${ALPHABRIEF_SRC}/packages/alphabrief-risk/src:${ALPHABRIEF_SRC}/packages/alphabrief-strategy/src:${ALPHABRIEF_SRC}/packages/alphabrief-trader/src:${ALPHABRIEF_SRC}/apps/api/src:${ALPHABRIEF_SRC}/apps/cli/src:${PYTHONPATH:-}"

# Use the .alphabrief venv (outside Desktop, no TCC issues)
exec "$HOME/.alphabrief/venv/bin/alphabrief" \
  scheduler run --reconcile-interval 60
