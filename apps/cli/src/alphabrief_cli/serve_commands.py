"""CLI subcommands for the API server."""

from __future__ import annotations

import typer

serve_app = typer.Typer(help="Start the AlphaBrief API server.")


@serve_app.command("serve")
def serve_cmd(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Host interface for the AlphaBrief API server.",
    ),
    port: int = typer.Option(
        8000,
        "--port",
        help="Port for the AlphaBrief API server.",
    ),
) -> None:
    """Start the AlphaBrief FastAPI server."""

    import uvicorn
    from alphabrief_api.main import app

    uvicorn.run(app, host=host, port=port)


__all__ = ["serve_app"]
