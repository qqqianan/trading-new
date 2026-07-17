import pytest

from ashare_lab.data import balance_sheet_cli
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.tushare_client import TushareQuery


def test_balance_sheet_backfill_skips_only_proven_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one complete and one pending historical lifecycle code.
    attempted: list[str] = []
    persisted: list[int] = []

    def completed(
        _registry: SchemaRegistry,
        _start: str,
        _end: str,
    ) -> frozenset[str]:
        return frozenset({"000001.SZ"})

    def persist(_registry: SchemaRegistry, results: tuple[None, ...]) -> None:
        persisted.append(len(results))

    monkeypatch.setattr(
        balance_sheet_cli,
        "load_balance_sheet_security_codes",
        lambda: ("000001.SZ", "600000.SH"),
    )
    monkeypatch.setattr(
        balance_sheet_cli,
        "load_completed_balance_sheet_codes",
        completed,
    )

    def execute(
        _registry: SchemaRegistry,
        queries: tuple[TushareQuery, ...],
    ) -> tuple[None, ...]:
        attempted.append(queries[0].params[0].value)
        return ()

    monkeypatch.setattr(balance_sheet_cli, "execute_queries", execute)
    monkeypatch.setattr(
        balance_sheet_cli,
        "persist_balance_sheet_results",
        persist,
    )

    # When: a one-security backfill resumes.
    balance_sheet_cli.backfill_balance_sheet("20200101", "20260716", max_securities=1)

    # Then: only the pending code crosses provider and PIT boundaries.
    assert attempted == ["600000.SH"]
    assert persisted == [0]
