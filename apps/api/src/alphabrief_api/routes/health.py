"""Health check route for the AlphaBrief API."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict


class HealthStatus(BaseModel):
    """Health check response body."""

    model_config = ConfigDict(frozen=True)

    status: str
    version: str


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthStatus)
def get_health() -> HealthStatus:
    """Return the AlphaBrief API health status."""

    return HealthStatus(status="healthy", version="0.0.0")


__all__ = ["HealthStatus", "router"]
