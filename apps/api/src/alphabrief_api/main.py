"""FastAPI application entry point for AlphaBrief."""

from __future__ import annotations

from fastapi import FastAPI

from alphabrief_api.routes.backtest import router as backtest_router
from alphabrief_api.routes.brief import router as brief_router
from alphabrief_api.routes.dashboard import router as dashboard_router
from alphabrief_api.routes.data import router as data_router
from alphabrief_api.routes.health import router as health_router
from alphabrief_api.routes.paper import router as paper_router
from alphabrief_api.routes.research import router as research_router
from alphabrief_api.routes.review import router as review_router
from alphabrief_api.routes.risk import router as risk_router
from alphabrief_api.routes.status import router as status_router


def create_app() -> FastAPI:
    """Create the AlphaBrief FastAPI application."""

    api_app = FastAPI(
        title="AlphaBrief API",
        description=(
            "Read-only API surface for AlphaBrief project health, "
            "configuration status, and local data status."
        ),
        version="0.0.0",
    )
    api_app.include_router(health_router)
    api_app.include_router(status_router)
    api_app.include_router(data_router)
    api_app.include_router(backtest_router)
    api_app.include_router(brief_router)
    api_app.include_router(paper_router)
    api_app.include_router(research_router)
    api_app.include_router(risk_router)
    api_app.include_router(review_router)
    api_app.include_router(dashboard_router)
    return api_app


app = create_app()

__all__ = ["app", "create_app"]
