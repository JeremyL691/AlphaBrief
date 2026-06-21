"""Alpaca Paper broker adapter package.

Concrete adapter that talks to ``https://paper-api.alpaca.markets``
over urllib (no SDK). The base URL is loaded from
``config/alpaca_paper.yaml``; credentials come from environment
variables only.
"""

from alphabrief_execution.broker.alpaca.adapter import AlpacaPaperAdapter
from alphabrief_execution.broker.alpaca.client import (
    AlpacaHttpClient,
    AlpacaHttpResponse,
    run_async,
)
from alphabrief_execution.broker.alpaca.config import (
    DEFAULT_BASE_URL,
    ENV_KEY,
    ENV_SECRET,
    AlpacaPaperConfig,
    load_alpaca_paper_config,
    read_alpaca_credentials,
)

__all__ = [
    "AlpacaHttpClient",
    "AlpacaHttpResponse",
    "AlpacaPaperAdapter",
    "AlpacaPaperConfig",
    "DEFAULT_BASE_URL",
    "ENV_KEY",
    "ENV_SECRET",
    "load_alpaca_paper_config",
    "read_alpaca_credentials",
    "run_async",
]
