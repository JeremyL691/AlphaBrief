"""Project status route for the AlphaBrief API."""

from __future__ import annotations

from alphabrief_core.config import AppSettings, load_settings
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

_PACKAGES_LOADED = [
    "alphabrief_core",
    "alphabrief_data",
    "alphabrief_strategy",
    "alphabrief_backtest",
    "alphabrief_models",
    "alphabrief_risk",
    "alphabrief_execution",
    "alphabrief_gym",
    "alphabrief_review",
    "alphabrief_acceptance",
]


class ProjectStatus(BaseModel):
    """Project status response body."""

    model_config = ConfigDict(frozen=True)

    version: str
    environment: str
    live_trading_enabled: bool
    data_dir: str
    reports_dir: str
    packages_loaded: list[str]


router = APIRouter(prefix="/api", tags=["status"])


def _project_status_from_settings(settings: AppSettings) -> ProjectStatus:
    """Build a project status response from application settings."""

    return ProjectStatus(
        version="0.0.0",
        environment=settings.env,
        live_trading_enabled=settings.live_trading_enabled,
        data_dir=str(settings.data_dir),
        reports_dir=str(settings.reports_dir),
        packages_loaded=list(_PACKAGES_LOADED),
    )


@router.get("/status", response_model=ProjectStatus)
def get_project_status() -> ProjectStatus:
    """Return read-only AlphaBrief project status."""

    return _project_status_from_settings(load_settings())


__all__ = ["ProjectStatus", "router"]
