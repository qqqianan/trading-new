"""Deterministic queries for the committed SW2021 industry taxonomy."""

from typing import Final

from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.snapshots import SnapshotBatch
from ashare_lab.data.tushare_client import QueryParam, TushareQuery

INDUSTRY_SOURCE: Final = "SW2021"


def level_one_industry_codes(batch: SnapshotBatch) -> tuple[str, ...]:
    """Extract exact L1 codes from one governed taxonomy snapshot."""
    codes: set[str] = set()
    for row in batch.rows:
        payload = dict(row.payload)
        if payload.get("src") != INDUSTRY_SOURCE:
            detail = "industry taxonomy response contains an unexpected source"
            raise SchemaContractError(detail)
        if payload.get("level") != "L1":
            continue
        code = payload.get("index_code")
        if not isinstance(code, str) or code == "":
            detail = "level-one industry row is missing index_code"
            raise SchemaContractError(detail)
        codes.add(code)
    if not codes:
        detail = "industry taxonomy response contains no level-one codes"
        raise SchemaContractError(detail)
    return tuple(sorted(codes))


def industry_master_query(registry: SchemaRegistry) -> TushareQuery:
    """Build the bounded industry taxonomy query."""
    schema = registry.endpoint("index_classify")
    return TushareQuery(
        "index_classify",
        (QueryParam("src", INDUSTRY_SOURCE),),
        schema.field_names,
    )


def industry_member_queries(
    registry: SchemaRegistry,
    level_one_codes: tuple[str, ...],
) -> tuple[TushareQuery, ...]:
    """Build one exact membership request per accepted level-one industry."""
    fields = registry.endpoint("index_member").field_names
    return tuple(
        TushareQuery(
            "index_member",
            (QueryParam("index_code", code),),
            fields,
        )
        for code in sorted(set(level_one_codes))
    )
