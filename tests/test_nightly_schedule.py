import plistlib
from datetime import date
from pathlib import Path

import pytest

from ashare_lab.data.nightly_schedule import NightlyStage, build_nightly_plan

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    ("run_date", "weekly_stage"),
    [
        (date(2026, 7, 13), NightlyStage.INCOME),
        (date(2026, 7, 14), NightlyStage.BALANCE_SHEET),
        (date(2026, 7, 15), NightlyStage.CASHFLOW),
        (date(2026, 7, 16), NightlyStage.FINANCIAL_INDICATORS),
        (date(2026, 7, 17), NightlyStage.UNIVERSE),
        (date(2026, 7, 18), NightlyStage.REFERENCE_DATA),
    ],
)
def test_nightly_plan_runs_core_daily_then_one_weekly_stage(
    run_date: date,
    weekly_stage: NightlyStage,
) -> None:
    # Given: one Monday-through-Saturday Shanghai calendar date.
    # When: the deterministic maintenance plan is built.
    plan = build_nightly_plan(run_date)

    # Then: market dependencies run first and the weekly load is bounded.
    assert plan.stages == (
        NightlyStage.MARKET,
        NightlyStage.BENCHMARK_DAILY,
        NightlyStage.DIVIDENDS,
        weekly_stage,
    )


def test_sunday_nightly_plan_runs_only_freshness_critical_stages() -> None:
    # Given: a Sunday with no scheduled heavy weekly scan.
    # When: the plan is built.
    plan = build_nightly_plan(date(2026, 7, 19))

    # Then: daily idempotent freshness and announcement lookback still run.
    assert plan.stages == (
        NightlyStage.MARKET,
        NightlyStage.BENCHMARK_DAILY,
        NightlyStage.DIVIDENDS,
    )


def test_launch_agent_runs_governed_nightly_command_at_1830() -> None:
    # Given: the committed macOS LaunchAgent template.
    path = ROOT / "ops" / "launchd" / "com.ashare-lab.daily-data.plist"

    # When: its structured property list is parsed.
    document = plistlib.loads(path.read_bytes())

    # Then: automation invokes the comprehensive command from the project directory.
    assert document["ProgramArguments"][-1] == "nightly-maintenance"
    assert document["StartCalendarInterval"] == [
        {"Hour": 18, "Minute": 30},
        {"Hour": 21, "Minute": 30},
    ]
    assert document["WorkingDirectory"] == str(ROOT)
