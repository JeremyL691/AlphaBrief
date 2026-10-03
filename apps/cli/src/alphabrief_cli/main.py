"""AlphaBrief CLI entry point.

This is the top-level Typer application that wires the subcommand groups
together.
"""

from __future__ import annotations

import typer
from alphabrief_core import paths as _paths
from alphabrief_core.paths import PathConfigError

from alphabrief_cli.ai_commands import ai_app
from alphabrief_cli.audit_commands import audit_app
from alphabrief_cli.backtest_commands import backtest_app
from alphabrief_cli.broker_commands import broker_app
from alphabrief_cli.cycle_commands import cycle_app
from alphabrief_cli.data_commands import data_app
from alphabrief_cli.db_commands import db_app
from alphabrief_cli.doctor_commands import doctor_app
from alphabrief_cli.macro_commands import macro_app
from alphabrief_cli.model_commands import model_app
from alphabrief_cli.news_commands import news_app
from alphabrief_cli.report_commands import report_app
from alphabrief_cli.review_commands import review_app
from alphabrief_cli.risk_commands import risk_app
from alphabrief_cli.run_commands import run_app
from alphabrief_cli.scheduler_commands import scheduler_app
from alphabrief_cli.serve_commands import serve_app
from alphabrief_cli.service_commands import service_app
from alphabrief_cli.strategy_commands import strategy_app

app = typer.Typer(
    name="alphabrief",
    help="AlphaBrief local-first AI forex paper-trading workbench.",
    no_args_is_help=True,
    add_completion=False,
)

app.add_typer(data_app, name="data")
app.add_typer(cycle_app, name="cycle")
app.add_typer(news_app, name="news")
app.add_typer(macro_app, name="macro")
app.add_typer(model_app, name="model")
app.add_typer(backtest_app, name="backtest")
app.add_typer(risk_app, name="risk")
app.add_typer(report_app, name="report")
app.add_typer(doctor_app, name="doctor")
app.add_typer(run_app, name="run")
app.add_typer(audit_app, name="audit")
app.add_typer(review_app, name="review")
app.add_typer(strategy_app, name="strategy")
app.add_typer(broker_app, name="broker")
app.add_typer(scheduler_app, name="scheduler")
app.add_typer(serve_app, name="serve")
app.add_typer(ai_app, name="ai")
app.add_typer(db_app, name="db")
app.add_typer(service_app, name="service")


@app.callback()
def _validate_environment() -> None:
    """Fail with an actionable message when the environment is unusable.

    The data directory must be an absolute path (PROJECT_GUIDE 4.3). A
    relative value is a configuration error the operator must fix, so it
    is reported as a one-line message instead of a traceback.
    """
    import sys

    if any(argument in {"--help", "-h"} for argument in sys.argv[1:]):
        return
    try:
        _paths.data_dir()
    except PathConfigError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc


__all__ = ["app"]
