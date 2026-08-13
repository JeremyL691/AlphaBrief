"""AlphaBrief CLI entry point.

This is the top-level Typer application that wires the subcommand groups
together. Each subcommand group is intentionally a stub for now; the
underlying logic will be filled in by the owning package in a later round.
"""

from __future__ import annotations

import typer

from alphabrief_cli.acceptance_commands import acceptance_app
from alphabrief_cli.ai_commands import ai_app
from alphabrief_cli.audit_commands import audit_app
from alphabrief_cli.backtest_commands import backtest_app
from alphabrief_cli.bootstrap_commands import bootstrap_app
from alphabrief_cli.brief_commands import brief_app
from alphabrief_cli.broker_commands import broker_app
from alphabrief_cli.data_commands import data_app
from alphabrief_cli.macro_commands import macro_app
from alphabrief_cli.model_commands import model_app
from alphabrief_cli.news_commands import news_app
from alphabrief_cli.observation_commands import observation_app
from alphabrief_cli.operations_commands import operations_app
from alphabrief_cli.paper_commands import paper_app
from alphabrief_cli.research_commands import research_app
from alphabrief_cli.review_commands import review_app
from alphabrief_cli.risk_commands import risk_app
from alphabrief_cli.scheduler_commands import scheduler_app
from alphabrief_cli.serve_commands import serve_app
from alphabrief_cli.strategy_commands import strategy_app

app = typer.Typer(
    name="alphabrief",
    help="AlphaBrief local-first AI quant research and paper-trading workbench.",
    no_args_is_help=True,
    add_completion=False,
)

app.add_typer(data_app, name="data")
app.add_typer(news_app, name="news")
app.add_typer(operations_app, name="operations")
app.add_typer(observation_app, name="observation")
app.add_typer(macro_app, name="macro")
app.add_typer(backtest_app, name="backtest")
app.add_typer(brief_app, name="brief")
app.add_typer(model_app, name="model")
app.add_typer(paper_app, name="paper")
app.add_typer(research_app, name="research")
app.add_typer(risk_app, name="risk")
app.add_typer(audit_app, name="audit")
app.add_typer(review_app, name="review")
app.add_typer(strategy_app, name="strategy")
app.add_typer(bootstrap_app, name="bootstrap")
app.add_typer(broker_app, name="broker")
app.add_typer(scheduler_app, name="scheduler")
app.add_typer(serve_app, name="serve")
app.add_typer(acceptance_app, name="acceptance")
app.add_typer(ai_app, name="ai")


__all__ = ["app"]
