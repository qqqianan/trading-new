import pytest

from ashare_lab.data import financial_cli
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.tushare_client import TushareQuery


def test_income_backfill_skips_only_codes_with_complete_pit_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: two lifecycle codes where the first already has complete range evidence.
    attempted: list[str] = []
    persisted: list[int] = []
    monkeypatch.setattr(
        financial_cli,
        "load_income_security_codes",
        lambda: ("000001.SZ", "600000.SH"),
        raising=False,
    )
    monkeypatch.setattr(
        financial_cli,
        "load_completed_income_codes",
        lambda _registry, _start, _end: frozenset({"000001.SZ"}),
        raising=False,
    )

    def record(
        _registry: SchemaRegistry,
        queries: tuple[TushareQuery, ...],
    ) -> tuple[None, ...]:
        attempted.append(queries[0].params[0].value)
        return ()

    monkeypatch.setattr(financial_cli, "execute_queries", record)
    monkeypatch.setattr(
        financial_cli,
        "persist_income_results",
        lambda _registry, results: persisted.append(len(results)),
    )

    # When: a bounded standard income backfill resumes.
    financial_cli.backfill_income("20200101", "20260716", max_securities=1)

    # Then: only the next incomplete security crosses provider and PIT boundaries.
    assert attempted == ["600000.SH"]
    assert persisted == [0]
