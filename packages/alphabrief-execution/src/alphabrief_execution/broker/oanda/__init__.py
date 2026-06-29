"""OANDA Paper broker adapter package.

Concrete adapter that talks to ``https://api-fxpractice.oanda.com``
over urllib (no SDK). The base URL is loaded from
``config/oanda_paper.yaml``; credentials come from environment variables
only.
"""

from alphabrief_execution.broker.oanda.adapter import OandaPaperAdapter
from alphabrief_execution.broker.oanda.client import (
    OandaHttpClient,
    OandaHttpResponse,
    run_async,
)
from alphabrief_execution.broker.oanda.config import (
    DEFAULT_BASE_URL,
    ENV_ACCOUNT_ID,
    ENV_TOKEN,
    OandaPaperConfig,
    load_oanda_paper_config,
    read_oanda_credentials,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "ENV_ACCOUNT_ID",
    "ENV_TOKEN",
    "OandaHttpClient",
    "OandaHttpResponse",
    "OandaPaperAdapter",
    "OandaPaperConfig",
    "load_oanda_paper_config",
    "read_oanda_credentials",
    "run_async",
]
