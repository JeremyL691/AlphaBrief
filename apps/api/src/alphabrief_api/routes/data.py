"""Data directory status route for the AlphaBrief API."""

from __future__ import annotations

from pathlib import Path

from alphabrief_core.config import AppSettings, load_settings
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict


class DataStatus(BaseModel):
    """Data directory status response body."""

    model_config = ConfigDict(frozen=True)

    data_dir: str
    data_dir_exists: bool
    data_dir_has_files: bool
    files_summary: str


router = APIRouter(prefix="/api/data", tags=["data"])


def _summarize_data_files(data_dir: Path) -> tuple[bool, str]:
    """Summarize CSV and Parquet files under the configured data directory."""

    files = [path for path in data_dir.iterdir() if path.is_file()]
    csv_count = sum(1 for path in files if path.suffix.lower() == ".csv")
    parquet_count = sum(1 for path in files if path.suffix.lower() == ".parquet")
    if not files:
        return False, "no files found"
    return True, f"{len(files)} files found; csv={csv_count}; parquet={parquet_count}"


def _data_status_from_settings(settings: AppSettings) -> DataStatus:
    """Build a data status response from application settings."""

    data_dir = settings.data_dir
    data_dir_exists = data_dir.exists() and data_dir.is_dir()
    data_dir_has_files = False
    files_summary = "data directory does not exist"
    if data_dir_exists:
        data_dir_has_files, files_summary = _summarize_data_files(data_dir)

    return DataStatus(
        data_dir=str(data_dir),
        data_dir_exists=data_dir_exists,
        data_dir_has_files=data_dir_has_files,
        files_summary=files_summary,
    )


@router.get("/status", response_model=DataStatus)
def get_data_status() -> DataStatus:
    """Return read-only status for the configured data directory."""

    return _data_status_from_settings(load_settings())


__all__ = ["DataStatus", "router"]
