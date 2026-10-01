"""Tests for the shadow evaluation (PROJECT_GUIDE 5.11)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_trader.shadow import (
    SHADOW_BENCHMARKS,
    SMALL_SAMPLE_CAVEAT,
    ShadowDecision,
    ShadowError,
    ShadowScore,
    build_shadow_decisions,
    committee_side,
    directional_return_pct,
    momentum_side,
    random_side,
    summarize,
)
from alphabrief_trader.shadow_store import ShadowStore

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class TestDeterministicBenchmarks:
    def test_momentum_follows_the_twenty_day_return(self) -> None:
        rising = [Decimal(index) for index in range(1, 23)]
        falling = list(reversed(rising))

        assert momentum_side(rising) == "long"
        assert momentum_side(falling) == "short"
        assert momentum_side([Decimal("5")] * 21) == "flat"

    def test_momentum_needs_a_full_window(self) -> None:
        with pytest.raises(ShadowError, match="needs 21 closes"):
            momentum_side([Decimal("1")] * 20)

    def test_random_is_seeded_by_the_cycle_hash(self) -> None:
        first = random_side("cyc_1", "EUR_USD")

        assert first == random_side("cyc_1", "EUR_USD")
        assert first in {"long", "short"}
        # Different rounds are allowed to differ, and the whole point is
        # that the sequence is reproducible, not arbitrary.
        assert {random_side(f"cyc_{index}", "EUR_USD") for index in range(20)} <= {
            "long",
            "short",
        }

    def test_committee_side_reads_the_plan(self) -> None:
        assert (
            committee_side(side="buy", target_position_pct=Decimal("0.1"))
            == "long"
        )
        assert (
            committee_side(side="sell", target_position_pct=Decimal("0.1"))
            == "short"
        )
        assert committee_side(side="buy", target_position_pct=Decimal("0")) == "flat"
        assert committee_side(side=None, target_position_pct=None) == "flat"

    def test_five_decisions_are_recorded_per_symbol(self) -> None:
        decisions = build_shadow_decisions(
            cycle_id="cyc_1",
            symbol="EUR_USD",
            decided_at=NOW,
            entry_mid=Decimal("1.1000"),
            committee="long",
            committee_detail="confidence 0.7",
            momentum="short",
            momentum_detail="20d return negative",
        )

        assert tuple(d.benchmark for d in decisions) == SHADOW_BENCHMARKS
        by_name = {d.benchmark: d for d in decisions}
        assert by_name["committee"].side == "long"
        assert by_name["momentum"].side == "short"
        assert by_name["no_trade"].side == "flat"
        assert by_name["single_call"].source == "skipped"
        assert "not attempted" in by_name["single_call"].detail
        assert by_name["random"].side in {"long", "short"}

    def test_unknown_benchmark_is_refused(self) -> None:
        with pytest.raises(ShadowError, match="unknown shadow benchmark"):
            ShadowDecision(
                cycle_id="cyc_1",
                symbol="EUR_USD",
                benchmark="vibes",
                side="long",
                source="x",
                detail="y",
                decided_at=NOW,
            )


class TestScoring:
    def test_long_return_is_net_of_the_exit_spread(self) -> None:
        # +1% move minus a 0.02% spread = +0.98%.
        value = directional_return_pct(
            side="long",
            entry_mid=Decimal("1.0000"),
            exit_mid=Decimal("1.0100"),
            spread_at_exit=Decimal("0.0002"),
        )

        assert value == pytest.approx(Decimal("0.98"), abs=Decimal("0.001"))

    def test_short_return_inverts_the_move(self) -> None:
        value = directional_return_pct(
            side="short",
            entry_mid=Decimal("1.0000"),
            exit_mid=Decimal("0.9900"),
            spread_at_exit=Decimal("0.0001"),
        )

        assert value > 0

    def test_flat_scores_exactly_zero(self) -> None:
        assert (
            directional_return_pct(
                side="flat",
                entry_mid=Decimal("1.0000"),
                exit_mid=Decimal("1.2000"),
                spread_at_exit=Decimal("0.0002"),
            )
            == 0
        )

    def test_a_wide_spread_can_turn_a_right_call_negative(self) -> None:
        value = directional_return_pct(
            side="long",
            entry_mid=Decimal("1.0000"),
            exit_mid=Decimal("1.0001"),
            spread_at_exit=Decimal("0.0100"),
        )

        assert value < 0

    def test_bad_prices_are_refused(self) -> None:
        with pytest.raises(ShadowError, match="prices must be positive"):
            directional_return_pct(
                side="long",
                entry_mid=Decimal("0"),
                exit_mid=Decimal("1"),
                spread_at_exit=Decimal("0"),
            )


class TestStatistics:
    def test_stats_are_deterministic_and_bracketed(self) -> None:
        returns = [Decimal("1.0"), Decimal("-0.5"), Decimal("0.25")]

        first = summarize(returns, benchmark="committee", horizon_hours=4)
        second = summarize(returns, benchmark="committee", horizon_hours=4)

        assert first == second
        assert first.samples == 3
        assert first.mean_return_pct == Decimal("0.25")
        assert first.win_rate == Decimal("0.6666666666666666666666666667")
        assert first.ci_low_pct <= first.mean_return_pct <= first.ci_high_pct
        assert first.caveat == SMALL_SAMPLE_CAVEAT

    def test_empty_sample_is_zero_with_the_caveat(self) -> None:
        stats = summarize([], benchmark="momentum", horizon_hours=24)

        assert stats.samples == 0
        assert stats.mean_return_pct == 0
        assert stats.caveat == SMALL_SAMPLE_CAVEAT

    def test_bootstrap_sample_count_must_be_positive(self) -> None:
        with pytest.raises(ShadowError, match="bootstrap_samples"):
            summarize(
                [Decimal("1")],
                benchmark="random",
                horizon_hours=4,
                bootstrap_samples=0,
            )


class TestShadowStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> Iterator[ShadowStore]:
        s = ShadowStore(db_path=tmp_path / "shadow.duckdb")
        try:
            yield s
        finally:
            s.close()

    def _decisions(self) -> list[ShadowDecision]:
        return list(
            build_shadow_decisions(
                cycle_id="cyc_1",
                symbol="EUR_USD",
                decided_at=NOW,
                entry_mid=Decimal("1.1000"),
                committee="long",
                committee_detail="confidence 0.7",
                momentum="long",
                momentum_detail="20d return positive",
            )
        )

    def test_saving_is_idempotent(self, store: ShadowStore) -> None:
        assert store.save_decisions(self._decisions()) == 5
        assert store.save_decisions(self._decisions()) == 0
        assert len(store.list_decisions(cycle_id="cyc_1")) == 5

    def test_due_for_scoring_respects_the_horizons(self, store: ShadowStore) -> None:
        store.save_decisions(self._decisions())

        assert store.due_for_scoring(now=NOW + timedelta(hours=1)) == []
        due_4h = store.due_for_scoring(now=NOW + timedelta(hours=5))
        assert len(due_4h) == 5
        assert all(row["horizon_hours"] == 4 for row in due_4h)
        assert len(store.due_for_scoring(now=NOW + timedelta(hours=25))) == 10

    def test_scores_are_kept_once_and_aggregated(self, store: ShadowStore) -> None:
        store.save_decisions(self._decisions())
        score = ShadowScore(
            cycle_id="cyc_1",
            symbol="EUR_USD",
            benchmark="committee",
            horizon_hours=4,
            return_pct=Decimal("0.5"),
            exit_mid=Decimal("1.1055"),
            spread_at_exit=Decimal("0.0002"),
            scored_at=NOW + timedelta(hours=4),
        )

        assert store.save_score(score) is True
        assert store.save_score(score) is False

        stats = store.stats(horizon_hours=4)
        committee = next(s for s in stats if s.benchmark == "committee")
        assert committee.samples == 1
        assert committee.mean_return_pct == Decimal("0.5")
        # Benchmarks without a score still appear, at zero samples.
        assert len(stats) == len(SHADOW_BENCHMARKS)
        board = store.scoreboard()
        assert set(board) == {"4h", "24h"}
        assert board["4h"][0]["caveat"] == SMALL_SAMPLE_CAVEAT
