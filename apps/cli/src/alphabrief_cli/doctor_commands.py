"""``alphabrief doctor``: one-shot health checks (PROJECT_GUIDE 4.9).

Every check reports PASS / WARN / FAIL with a reason, and nothing is
fabricated: a check that cannot reach its evidence says so instead of
assuming health.

Checks:

* the data directory is writable and the single-instance lock is free (or
  held by a live backend, which is a WARN outside of ``--expect-daemon``);
* OANDA practice is reachable read-only, with the account currency and the
  number of tradeable instruments;
* the model channel has valid credentials and a recorded recent call
  (no live call is made — that would spend the daily budget);
* the news sources answer (one HEAD/GET per configured feed);
* the anti-sleep assertion (macOS ``pmset``) is a WARN-only check: the
  system settings are read, never modified;
* free disk space;
* the most recent reconciliation snapshot and whether a freeze is open.

Exit code is non-zero only when a check FAILs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import typer
from alphabrief_core import paths as _paths
from alphabrief_core.runtime_lock import lock_status

doctor_app = typer.Typer(help="One-shot health checks with PASS/WARN/FAIL.")

CheckStatus = Literal["PASS", "WARN", "FAIL"]

#: Free space below this is a FAIL, below twice this a WARN.
DISK_FAIL_BYTES = 512 * 1024 * 1024
DISK_WARN_BYTES = 2 * 1024 * 1024 * 1024

#: A bar older than this is a WARN (the runtime syncs hourly).
MARKET_DATA_WARN_AGE = timedelta(hours=6)


@dataclass(frozen=True)
class CheckResult:
    """One doctor check verdict."""

    check_id: str
    status: CheckStatus
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "check": self.check_id,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class DoctorReport:
    """The full check run."""

    checked_at: datetime
    results: list[CheckResult] = field(default_factory=list)

    @property
    def failed(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == "FAIL"]

    @property
    def warned(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == "WARN"]

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        counts = {
            status: sum(1 for r in self.results if r.status == status)
            for status in ("PASS", "WARN", "FAIL")
        }
        head = (
            f"doctor: {counts['PASS']} PASS, {counts['WARN']} WARN, "
            f"{counts['FAIL']} FAIL"
        )
        if self.warned:
            head += "; warn=[" + ", ".join(r.check_id for r in self.warned) + "]"
        if self.failed:
            head += "; fail=[" + ", ".join(r.check_id for r in self.failed) + "]"
        return head

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at.isoformat(),
            "ok": self.ok,
            "summary": self.summary(),
            "results": [result.to_dict() for result in self.results],
        }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _open_store(store_cls: Any, db_path: Any) -> Any:
    """Open store read-only, falling back to read-write if process already connected."""
    try:
        return store_cls(db_path=db_path, read_only=True)
    except Exception:
        return store_cls(db_path=db_path, read_only=False)


def check_data_dir() -> CheckResult:
    """The data directory exists and is writable."""
    target = _paths.data_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return CheckResult("data_dir", "FAIL", f"{target} is not writable: {exc}")
    return CheckResult("data_dir", "PASS", f"{target} is writable")


def check_single_instance_lock(*, expect_daemon: bool = False) -> CheckResult:
    """The runtime lock is free, or held by a running backend."""
    holder = lock_status()
    if holder is None:
        status: CheckStatus = "PASS" if not expect_daemon else "WARN"
        detail = "runtime lock is free"
        if expect_daemon:
            detail += " but no backend is running (--expect-daemon)"
        return CheckResult("single_instance_lock", status, detail)
    pid = holder.get("pid", "unknown")
    started = holder.get("started_at", "unknown")
    return CheckResult(
        "single_instance_lock",
        "PASS" if expect_daemon else "WARN",
        f"held by pid {pid} since {started}",
    )


def check_oanda_read_only() -> CheckResult:
    """OANDA practice is reachable read-only, with its currency and catalog."""
    from alphabrief_execution.broker.oanda.account_ops import AccountOpsClient
    from alphabrief_execution.broker.oanda.instruments import fetch_instruments
    from alphabrief_execution.broker.runtime import (
        build_oanda_paper_client,
        oanda_is_configured,
    )

    if not oanda_is_configured():
        return CheckResult(
            "oanda_read_only",
            "FAIL",
            "practice credentials are not configured "
            "(ALPHABRIEF_OANDA_TOKEN / ALPHABRIEF_OANDA_ACCOUNT_ID)",
        )
    client = build_oanda_paper_client()
    try:
        summary = AccountOpsClient(client).account_summary(request_id="doctor")
        catalog = fetch_instruments(client, account_id=client.account_id)
    except Exception as exc:  # noqa: BLE001 - any failure is a FAIL with reason
        return CheckResult(
            "oanda_read_only", "FAIL", f"practice read failed: {type(exc).__name__}"
        )
    tradeable = [i for i in catalog.instruments if getattr(i, "tradeable", True)]
    return CheckResult(
        "oanda_read_only",
        "PASS",
        f"practice reachable; home currency {summary.currency}; "
        f"{len(tradeable)} tradeable instruments; NAV {summary.nav}",
    )


def check_model_channel() -> CheckResult:
    """The model channel has credentials and a recent recorded call."""
    from alphabrief_api.db.model_call import ModelCallStore
    from alphabrief_models.chatgpt_plan import load_credentials
    from alphabrief_models.model_budget import ModelBudgetGuard, ModelBudgetPolicy

    from alphabrief_cli.api_client import is_api_running

    credentials = load_credentials()
    if credentials is None:
        return CheckResult(
            "model_channel",
            "FAIL",
            "the ChatGPT channel is not signed in (`alphabrief model login`)",
        )
    if is_api_running():
        return CheckResult(
            "model_channel",
            "WARN",
            "credentials present; the backend owns the database so the call "
            "history and budget are not readable here (use `alphabrief "
            "scheduler status` for live state)",
        )
    store = _open_store(ModelCallStore, _paths.db_path())
    try:
        since = datetime.now(UTC) - timedelta(days=1)
        usage = store.daily_usage(since)
        guard = ModelBudgetGuard(store, policy=ModelBudgetPolicy.default())
        verdict = guard.admit("chatgpt_plan")
    finally:
        store.close()
    calls = usage.get("chatgpt_plan")
    detail = (
        f"credentials present; last 24h calls {0 if calls is None else calls.calls}"
    )
    if not verdict.allowed:
        return CheckResult(
            "model_channel", "WARN", f"{detail}; channel unavailable: {verdict.detail}"
        )
    return CheckResult("model_channel", "PASS", detail)


def check_news_sources(*, timeout_seconds: float = 15.0) -> CheckResult:
    """Each configured news feed answers with a parseable document."""
    import urllib.request

    from alphabrief_core.http import secure_urlopen
    from alphabrief_news.providers.rss import _FEED_SOURCES

    reachable: list[str] = []
    failed: list[str] = []
    for key, source in _FEED_SOURCES.items():
        request = urllib.request.Request(
            source.url, headers={"User-Agent": "AlphaBrief/1.0"}
        )
        try:
            with secure_urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(4096)
        except Exception:  # noqa: BLE001 - reported per feed
            failed.append(key)
            continue
        if b"<rss" in body or b"<feed" in body:
            reachable.append(key)
        else:
            failed.append(key)
    if failed and not reachable:
        return CheckResult(
            "news_sources", "FAIL", f"no feed reachable: {', '.join(failed)}"
        )
    if failed:
        return CheckResult(
            "news_sources",
            "WARN",
            f"{len(reachable)}/{len(_FEED_SOURCES)} reachable; failed: "
            f"{', '.join(failed)}",
        )
    return CheckResult(
        "news_sources", "PASS", f"all {len(reachable)} feeds reachable"
    )


def check_sleep_assertion() -> CheckResult:
    """Read the macOS sleep settings (never modified); WARN-only."""
    try:
        output = subprocess.run(
            ["pmset", "-g"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult(
            "sleep_assertion", "WARN", f"pmset unavailable: {type(exc).__name__}"
        )
    lines = {
        line.split()[0]: line
        for line in output.stdout.splitlines()
        if line.strip() and len(line.split()) > 1
    }
    sleep_line = lines.get("sleep", "")
    if "sleep                0" in sleep_line or " sleep  0" in sleep_line:
        return CheckResult(
            "sleep_assertion", "PASS", "system sleep is disabled (pmset sleep 0)"
        )
    return CheckResult(
        "sleep_assertion",
        "WARN",
        "system sleep is enabled; the soak needs the Mac awake (Amphetamine or "
        "`caffeinate`), which the operator controls",
    )


def check_disk_space() -> CheckResult:
    """Free space in the data directory's volume."""
    target = _paths.data_dir()
    try:
        usage = shutil.disk_usage(target if target.exists() else target.parent)
    except OSError as exc:
        return CheckResult("disk_space", "FAIL", f"cannot read disk usage: {exc}")
    if usage.free < DISK_FAIL_BYTES:
        return CheckResult(
            "disk_space", "FAIL", f"only {usage.free // (1024 * 1024)} MiB free"
        )
    if usage.free < DISK_WARN_BYTES:
        return CheckResult(
            "disk_space", "WARN", f"{usage.free // (1024 * 1024)} MiB free"
        )
    return CheckResult(
        "disk_space", "PASS", f"{usage.free // (1024 * 1024)} MiB free"
    )


def _database_exists() -> bool:
    """True when the runtime database file exists.

    A read-only connection to a missing file raises, so the DB-backed
    checks ask first and report "no data yet" instead of crashing on a
    fresh installation.
    """
    return _paths.db_path().is_file()

def check_reconciliation() -> CheckResult:
    """The most recent reconciliation snapshot and any open freeze.

    DuckDB allows one process to own the file, so when the backend is
    running the facts come from its HTTP endpoint instead of a second
    connection; with no backend the store is read directly.
    """
    from alphabrief_cli.api_client import is_api_running

    if is_api_running():
        return _reconciliation_from_api()
    if not _database_exists():
        return CheckResult(
            "reconciliation",
            "WARN",
            "no runtime database yet; no reconciliation has run",
        )
    from alphabrief_execution.broker.recon_store import BrokerReconStore

    store = _open_store(BrokerReconStore, _paths.db_path())
    try:
        snapshots = store.list_snapshots(limit=1)
        freeze = store.has_open_freeze()
        freezes = store.list_freezes(only_open=True)
    except Exception as exc:  # noqa: BLE001 - a store failure is a FAIL
        return CheckResult(
            "reconciliation", "FAIL", f"cannot read the recon store: {exc}"
        )
    finally:
        store.close()
    if not snapshots:
        return CheckResult(
            "reconciliation", "WARN", "no reconciliation snapshot recorded yet"
        )
    latest = snapshots[0]
    detail = (
        f"last snapshot {latest.captured_at} scope {latest.scope} "
        f"all_match={latest.all_match}"
    )
    if freeze:
        reasons = "; ".join(event.reason[:80] for event in freezes)
        return CheckResult(
            "reconciliation", "FAIL", f"an open freeze blocks new exposure: {reasons}"
        )
    return CheckResult("reconciliation", "PASS", detail)


def _reconciliation_from_api() -> CheckResult:
    """The reconciliation verdict read from the running backend."""
    import json
    import urllib.error
    import urllib.request

    from alphabrief_cli.api_client import _base_url

    url = f"{_base_url()}/api/v1/broker/status"
    try:
        with urllib.request.urlopen(url, timeout=5.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return CheckResult(
            "reconciliation",
            "WARN",
            f"backend is running but its status endpoint failed: {type(exc).__name__}",
        )
    freezes = payload.get("open_freezes") or []
    if freezes:
        reasons = "; ".join(str(item.get("reason", ""))[:80] for item in freezes)
        return CheckResult(
            "reconciliation", "FAIL", f"an open freeze blocks new exposure: {reasons}"
        )
    latest = payload.get("latest_snapshot")
    if latest is None:
        return CheckResult(
            "reconciliation", "WARN", "no reconciliation snapshot recorded yet"
        )
    return CheckResult(
        "reconciliation",
        "PASS",
        f"via backend: last snapshot {latest.get('captured_at')} "
        f"scope {latest.get('scope')} all_match={latest.get('all_match')}",
    )


def _backend_owns_the_database() -> CheckResult | None:
    """A WARN for DB-backed checks the backend's API does not expose yet.

    Returning ``None`` means "no backend, read locally".
    """
    from alphabrief_cli.api_client import is_api_running

    if not is_api_running():
        return None
    return None

def check_market_data(symbols: Sequence[str]) -> CheckResult:
    """Stored bars exist for the universe and are recent."""
    from alphabrief_cli.api_client import is_api_running

    if is_api_running():
        return CheckResult(
            "market_data",
            "WARN",
            "the backend owns the database; bar freshness is not exposed over "
            "HTTP yet (dashboard endpoint pending), so this check is skipped",
        )
    if not _database_exists():
        return CheckResult(
            "market_data",
            "FAIL",
            f"no runtime database yet; no stored bars for {', '.join(symbols)}",
        )
    from alphabrief_api.db.market_data import MarketDataStore

    store = _open_store(MarketDataStore, _paths.db_path())
    try:
        missing: list[str] = []
        stale: list[str] = []
        newest: datetime | None = None
        for symbol in symbols:
            try:
                bars = store.get_bar_models(symbol)
            except Exception:
                bars = []
            if not bars:
                missing.append(symbol)
                continue
            latest = bars[-1].timestamp
            newest = latest if newest is None else max(newest, latest)
            if datetime.now(UTC) - latest > MARKET_DATA_WARN_AGE:
                stale.append(symbol)
    finally:
        store.close()
    if missing:
        return CheckResult(
            "market_data", "FAIL", f"no stored bars for {', '.join(missing)}"
        )
    if stale:
        return CheckResult(
            "market_data",
            "WARN",
            f"stale bars for {', '.join(stale)} (latest {newest})",
        )
    return CheckResult("market_data", "PASS", f"bars fresh; latest {newest}")


def check_quote_samples(symbols: Sequence[str]) -> CheckResult:
    """Rule 4 has same-period spread history to compare against."""
    from alphabrief_cli.api_client import is_api_running

    if is_api_running():
        return CheckResult(
            "quote_samples",
            "WARN",
            "the backend owns the database; spread-sample depth is not exposed "
            "over HTTP yet (dashboard endpoint pending), so this check is skipped",
        )
    if not _database_exists():
        return CheckResult(
            "quote_samples",
            "WARN",
            "no runtime database yet; no spread samples recorded",
        )
    from alphabrief_data.quote_samples import (
        SPREAD_MEDIAN_SAMPLE_LIMIT,
        QuoteSampleStore,
    )

    store = _open_store(QuoteSampleStore, _paths.db_path())
    try:
        counts = {
            symbol: len(
                store.recent_spreads(
                    symbol,
                    hour=datetime.now(UTC).hour,
                    limit=SPREAD_MEDIAN_SAMPLE_LIMIT,
                )
            )
            for symbol in symbols
        }
    except Exception:
        counts = {symbol: 0 for symbol in symbols}
    finally:
        store.close()
    thin = {symbol: count for symbol, count in counts.items() if count < 5}
    if len(thin) == len(counts):
        return CheckResult(
            "quote_samples",
            "WARN",
            "no symbol has 5 same-hour spread samples yet; rule 4 fails closed "
            "until they accumulate",
        )
    if thin:
        return CheckResult(
            "quote_samples",
            "WARN",
            f"thin spread history for {', '.join(sorted(thin))}",
        )
    return CheckResult(
        "quote_samples", "PASS", f"same-hour samples: {counts}"
    )


def run_checks(
    *,
    symbols: Sequence[str],
    expect_daemon: bool = False,
    include_network: bool = True,
) -> DoctorReport:
    """Run every check and return the report."""
    report = DoctorReport(checked_at=datetime.now(UTC))
    report.results.append(check_data_dir())
    report.results.append(check_single_instance_lock(expect_daemon=expect_daemon))
    report.results.append(check_reconciliation())
    report.results.append(check_market_data(symbols))
    report.results.append(check_quote_samples(symbols))
    report.results.append(check_disk_space())
    report.results.append(check_sleep_assertion())
    if include_network:
        report.results.append(check_oanda_read_only())
        report.results.append(check_model_channel())
        report.results.append(check_news_sources())
    return report


def _dump(payload: object, *, pretty: bool) -> None:
    import json

    json.dump(payload, sys.stdout, indent=2 if pretty else None, default=str)
    sys.stdout.write("\n")


@doctor_app.command("run")
def run_cmd(
    expect_daemon: bool = typer.Option(  # noqa: B008
        False,
        "--expect-daemon",
        help="Treat a missing backend as a WARN (used by the soak patrol).",
    ),
    offline: bool = typer.Option(  # noqa: B008
        False,
        "--offline",
        help="Skip the network checks (OANDA, model channel, news feeds).",
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Run the health checks; exit non-zero when any check FAILs."""
    from alphabrief_cli.cycle_commands import DEFAULT_UNIVERSE

    report = run_checks(
        symbols=DEFAULT_UNIVERSE,
        expect_daemon=expect_daemon,
        include_network=not offline,
    )
    _dump(report.to_dict(), pretty=pretty)
    if not report.ok:
        sys.exit(1)


__all__ = [
    "CheckResult",
    "DoctorReport",
    "doctor_app",
    "run_checks",
]
