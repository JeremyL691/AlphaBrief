"""Plain-text viewers for AlphaBrief review snapshots."""

from alphabrief_review.schemas import ReviewCenterSnapshot


def render_strategy_list(snapshot: ReviewCenterSnapshot) -> str:
    lines = ["Strategies"]
    lines.extend(
        f"- {item.strategy_id} {item.version}: {item.name} [{item.status}]"
        for item in snapshot.strategies
    )
    return "\n".join(lines)


def render_backtest_report_view(snapshot: ReviewCenterSnapshot) -> str:
    lines = ["Backtest Reports"]
    lines.extend(
        (
            f"- {item.report_id}: {item.strategy_id} on {item.symbol}, "
            f"return={item.total_return}, drawdown={item.max_drawdown}, "
            f"trades={item.trade_count}"
        )
        for item in snapshot.backtests
    )
    return "\n".join(lines)


def render_research_report(snapshot: ReviewCenterSnapshot) -> str:
    lines = ["Daily AlphaBriefs"]
    lines.extend(
        (
            f"- {item.trading_day} {item.brief_id}: {item.headline} "
            f"| {item.executive_summary}"
        )
        for item in snapshot.daily_briefs
    )
    return "\n".join(lines)


def render_model_call_history(snapshot: ReviewCenterSnapshot) -> str:
    lines = ["Model Calls"]
    lines.extend(
        (
            f"- {item.call_id}: {item.provider}/{item.model} "
            f"{item.task_type} {item.status}"
        )
        for item in snapshot.model_calls
    )
    return "\n".join(lines)


def render_paper_portfolio(snapshot: ReviewCenterSnapshot) -> str:
    portfolio = snapshot.paper_portfolio
    positions = ", ".join(
        f"{symbol}={quantity}"
        for symbol, quantity in sorted(portfolio.open_positions.items())
    )
    if positions == "":
        positions = "none"
    return (
        "Paper Portfolio\n"
        f"- cash={portfolio.cash}\n"
        f"- total_value={portfolio.total_value}\n"
        f"- realized_pnl={portfolio.realized_pnl}\n"
        f"- positions={positions}"
    )


def render_order_audit_log(snapshot: ReviewCenterSnapshot) -> str:
    lines = ["Order Audit Log"]
    lines.extend(
        (
            f"- {item.created_at.isoformat()} {item.event_type}: "
            f"risk={item.risk_decision_id or 'none'} order={item.order_id or 'none'} "
            f"{item.message}"
        )
        for item in snapshot.order_audit_log
    )
    return "\n".join(lines)


def render_risk_dashboard(snapshot: ReviewCenterSnapshot) -> str:
    risk = snapshot.risk_dashboard
    tags = ", ".join(risk.latest_risk_tags) if risk.latest_risk_tags else "none"
    return (
        "Risk Dashboard\n"
        f"- total_decisions={risk.total_decisions}\n"
        f"- approved={risk.approved_decisions}\n"
        f"- rejected={risk.rejected_decisions}\n"
        f"- kill_switch_active={risk.kill_switch_active}\n"
        f"- latest_tags={tags}"
    )


def render_review_journal(snapshot: ReviewCenterSnapshot) -> str:
    lines = ["Review Journal"]
    lines.extend(
        (
            f"- {item.period} {item.period_start}..{item.period_end}: "
            f"{item.title} | {item.summary}"
        )
        for item in snapshot.review_journal
    )
    return "\n".join(lines)
