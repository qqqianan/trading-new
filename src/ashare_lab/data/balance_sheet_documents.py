"""Closed documents and field lineage for balance-sheet PIT versions."""

import hashlib
from typing import Final

from ashare_lab.data.balance_sheets import BalanceSheetVersion
from ashare_lab.data.bson_types import BsonDocument

_FIELDS: Final[tuple[str, ...]] = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "end_type",
    "total_share",
    "cap_rese",
    "undistr_porfit",
    "surplus_rese",
    "money_cap",
    "accounts_receiv",
    "inventories",
    "total_cur_assets",
    "fix_assets",
    "goodwill",
    "total_assets",
    "st_borr",
    "lt_borr",
    "total_cur_liab",
    "total_ncl",
    "total_liab",
    "total_hldr_eqy_exc_min_int",
    "total_hldr_eqy_inc_min_int",
    "total_liab_hldr_eqy",
    "update_flag",
)


def balance_sheet_document(event: BalanceSheetVersion) -> BsonDocument:
    """Serialize one event under the closed balance-sheet PIT contract."""
    return {
        "_id": event.event_id,
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "effective_at": event.effective_at,
        "available_at": event.available_at,
        "ingested_at": event.ingested_at,
        "source_endpoint": event.source_endpoint,
        "source_snapshot_id": event.source_snapshot_id,
        "source_row_sha256": event.source_row_sha256,
        "input_schema_manifest_id": event.input_schema_manifest_id,
        "schema_manifest_id": event.schema_manifest_id,
        "transform_name": event.transform_name,
        "transform_version": event.transform_version,
        "quality_status": event.quality_status,
        "quality_report_id": event.quality_report_id,
        "ts_code": event.ts_code,
        "ann_date": event.ann_date,
        "f_ann_date": event.f_ann_date,
        "end_date": event.end_date,
        "report_type": event.report_type,
        "comp_type": event.comp_type,
        "end_type": event.end_type,
        "total_share": event.total_share,
        "cap_rese": event.cap_rese,
        "undistr_porfit": event.undistr_porfit,
        "surplus_rese": event.surplus_rese,
        "money_cap": event.money_cap,
        "accounts_receiv": event.accounts_receiv,
        "inventories": event.inventories,
        "total_cur_assets": event.total_cur_assets,
        "fix_assets": event.fix_assets,
        "goodwill": event.goodwill,
        "total_assets": event.total_assets,
        "st_borr": event.st_borr,
        "lt_borr": event.lt_borr,
        "total_cur_liab": event.total_cur_liab,
        "total_ncl": event.total_ncl,
        "total_liab": event.total_liab,
        "total_hldr_eqy_exc_min_int": event.total_hldr_eqy_exc_min_int,
        "total_hldr_eqy_inc_min_int": event.total_hldr_eqy_inc_min_int,
        "total_liab_hldr_eqy": event.total_liab_hldr_eqy,
        "update_flag": event.update_flag,
    }


def balance_sheet_lineage(event: BalanceSheetVersion) -> BsonDocument:
    """Map every PIT field and publication clock to its immutable Raw row."""
    lineage_id = balance_sheet_lineage_id(event)
    raw = "raw_tushare_balancesheet.payload"
    return {
        "_id": lineage_id,
        "lineage_edge_id": lineage_id,
        "upstream_artifact_id": event.source_snapshot_id,
        "downstream_artifact_id": event.event_id,
        "transform_name": event.transform_name,
        "transform_version": event.transform_version,
        "code_commit": "workspace_unversioned",
        "input_schema_ids": [event.input_schema_manifest_id],
        "output_schema_id": event.schema_manifest_id,
        "parameters_sha256": hashlib.sha256(b"actual_announcement_clock").hexdigest(),
        "field_mappings": [
            *(f"pit_balance_sheets.{field}<-{raw}.{field}" for field in _FIELDS),
            f"pit_balance_sheets.effective_at<-{raw}.f_ann_date|ann_date",
        ],
        "executed_at": event.ingested_at,
    }


def balance_sheet_lineage_id(event: BalanceSheetVersion) -> str:
    """Return the stable lineage edge identity for one PIT event."""
    return f"lineage_{hashlib.sha256(f'{event.event_id}|lineage'.encode()).hexdigest()}"
