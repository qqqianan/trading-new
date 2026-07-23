import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest
from pydantic import ValidationError

from ashare_lab.research.splits.final_holdout import (
    DevelopmentDatasetReader,
    FinalHoldoutAccessLedger,
    FinalHoldoutAccessRequest,
    FinalHoldoutError,
    FinalHoldoutGate,
    FinalHoldoutPromotionEvidence,
    FinalHoldoutSpec,
    FrozenResearchProtocol,
    HoldoutAccessRecord,
)

ROOT = Path(__file__).parents[1]


def _spec() -> FinalHoldoutSpec:
    return FinalHoldoutSpec(
        dataset_snapshot_id="ds_862d155145b89879b679",
        development_end=date(2024, 12, 31),
        holdout_start=date(2025, 1, 1),
        protocol_version="1.0.0",
    )


def _frame() -> pl.DataFrame:
    timezone = ZoneInfo("Asia/Shanghai")
    return pl.DataFrame(
        {
            "decision_time": [
                datetime(2024, 12, 27, 18, tzinfo=timezone),
                datetime(2025, 1, 3, 18, tzinfo=timezone),
            ],
            "symbol": ["000001.SZ", "000001.SZ"],
            "value": [1.0, 2.0],
        }
    )


def _protocol(spec: FinalHoldoutSpec) -> FrozenResearchProtocol:
    return FrozenResearchProtocol(
        holdout_spec_id=spec.spec_id,
        dataset_snapshot_id=spec.dataset_snapshot_id,
        split_protocol_id="medium_horizon_504_126_63_p20_e5_v1",
        preprocessing_version="1.0.0",
        code_commit="a" * 40,
        frozen_at=datetime(2026, 7, 19, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        frozen_by="research_owner",
    )


def _promotion(spec: FinalHoldoutSpec) -> FinalHoldoutPromotionEvidence:
    return FinalHoldoutPromotionEvidence(
        model_protocol_id="model_protocol_" + "b" * 64,
        promotion_evaluation_id="model_promotion_" + "c" * 64,
        model_id="ridge_model_" + "d" * 64,
        dataset_snapshot_id=spec.dataset_snapshot_id,
        holdout_spec_id=spec.spec_id,
        all_development_gates_passed=True,
        final_test_runs=0,
    )


def test_default_development_reader_physically_excludes_holdout() -> None:
    # Given: a source frame contains development and sealed observations.
    reader = DevelopmentDatasetReader(_spec())

    # When: the default research read surface is used.
    development = reader.read(_frame())

    # Then: no final-holdout row crosses the boundary.
    assert development.height == 1
    assert development["value"].to_list() == [1.0]


def test_development_reader_rejects_explicit_holdout_request() -> None:
    # Given: the default development-only reader.
    reader = DevelopmentDatasetReader(_spec())

    # When / Then: asking it for a sealed date fails without a bypass flag.
    with pytest.raises(FinalHoldoutError, match="sealed"):
        reader.read_through(_frame(), date(2025, 1, 3))


def test_formal_holdout_opening_appends_once_and_second_open_fails(tmp_path: Path) -> None:
    # Given: one frozen protocol and an empty append-only access ledger.
    spec = _spec()
    protocol = _protocol(spec)
    ledger = FinalHoldoutAccessLedger(tmp_path)
    request = FinalHoldoutAccessRequest(
        protocol_id=protocol.protocol_id,
        model_protocol_id="model_protocol_" + "b" * 64,
        promotion_evaluation_id="model_promotion_" + "c" * 64,
        model_id="ridge_model_" + "d" * 64,
        dataset_snapshot_id=spec.dataset_snapshot_id,
        authorized_at=datetime(2026, 7, 19, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        authorized_by="research_owner",
        purpose="single_final_evaluation",
    )
    gate = FinalHoldoutGate(spec, protocol, ledger, _promotion(spec))

    # When: the frozen final holdout is formally opened once.
    holdout = gate.open_once(_frame(), request)

    # Then: one sealed row is returned and exactly one immutable access is recorded.
    assert holdout.height == 1
    assert ledger.count(spec.spec_id) == 1
    with pytest.raises(FinalHoldoutError, match="already opened"):
        gate.open_once(_frame(), request)
    assert ledger.count(spec.spec_id) == 1


def test_holdout_opening_rejects_authorization_for_another_protocol(tmp_path: Path) -> None:
    # Given: an authorization that is not bound to the frozen protocol.
    spec = _spec()
    protocol = _protocol(spec)
    request = FinalHoldoutAccessRequest(
        protocol_id="protocol_" + "b" * 64,
        model_protocol_id="model_protocol_" + "b" * 64,
        promotion_evaluation_id="model_promotion_" + "c" * 64,
        model_id="ridge_model_" + "d" * 64,
        dataset_snapshot_id=spec.dataset_snapshot_id,
        authorized_at=datetime(2026, 7, 19, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        authorized_by="research_owner",
        purpose="single_final_evaluation",
    )

    # When / Then: no ledger record or holdout data is exposed.
    ledger = FinalHoldoutAccessLedger(tmp_path)
    with pytest.raises(FinalHoldoutError, match="authorization"):
        FinalHoldoutGate(spec, protocol, ledger, _promotion(spec)).open_once(_frame(), request)
    assert ledger.count(spec.spec_id) == 0


def test_holdout_spec_rejects_overlapping_date_partitions() -> None:
    # Given: a boundary that places the final holdout inside development.
    # When / Then: the manifest trust boundary rejects the illegal partition.
    with pytest.raises(ValidationError, match="holdout_start"):
        FinalHoldoutSpec(
            dataset_snapshot_id="ds_862d155145b89879b679",
            development_end=date(2024, 12, 31),
            holdout_start=date(2024, 12, 31),
            protocol_version="1.0.0",
        )


def test_holdout_opening_rejects_authorization_before_protocol_freeze(tmp_path: Path) -> None:
    # Given: an opening request timestamped before its referenced protocol was frozen.
    spec = _spec()
    protocol = _protocol(spec)
    request = FinalHoldoutAccessRequest(
        protocol_id=protocol.protocol_id,
        model_protocol_id="model_protocol_" + "b" * 64,
        promotion_evaluation_id="model_promotion_" + "c" * 64,
        model_id="ridge_model_" + "d" * 64,
        dataset_snapshot_id=spec.dataset_snapshot_id,
        authorized_at=datetime(2026, 7, 19, 8, tzinfo=ZoneInfo("Asia/Shanghai")),
        authorized_by="research_owner",
        purpose="single_final_evaluation",
    )

    # When / Then: pre-freeze authorization cannot consume or expose the holdout.
    ledger = FinalHoldoutAccessLedger(tmp_path)
    with pytest.raises(FinalHoldoutError, match="after protocol freeze"):
        FinalHoldoutGate(spec, protocol, ledger, _promotion(spec)).open_once(_frame(), request)
    assert ledger.count(spec.spec_id) == 0


def test_development_reader_accepts_explicit_development_end() -> None:
    # Given: the default reader and a request ending inside development.
    reader = DevelopmentDatasetReader(_spec())

    # When: an explicit development-only end date is requested.
    development = reader.read_through(_frame(), date(2024, 12, 31))

    # Then: only the development observation is returned.
    assert development.height == 1


def test_holdout_ledger_rejects_malformed_existing_record(tmp_path: Path) -> None:
    # Given: an existing access ledger record that cannot pass its schema boundary.
    spec = _spec()
    directory = tmp_path / "final_holdout_access" / spec.spec_id
    directory.mkdir(parents=True)
    (directory / "000001.json").write_text("{}", encoding="utf-8")

    # When / Then: audit counting fails closed instead of treating it as unused.
    with pytest.raises(FinalHoldoutError, match="ledger is invalid"):
        FinalHoldoutAccessLedger(tmp_path).count(spec.spec_id)


def test_final_holdout_access_schema_documents_every_persisted_field() -> None:
    # Given: the committed machine schema for promotion-bound holdout access.
    document = json.loads(
        (ROOT / "schemas" / "final_holdout_access_v1.json").read_text(encoding="utf-8")
    )

    # When: required fields are compared with all three trust boundaries.
    definitions = document["$defs"]
    required = (
        set(definitions["FinalHoldoutAccessRequest"]["required"]),
        set(definitions["FinalHoldoutPromotionEvidence"]["required"]),
        set(definitions["HoldoutAccessRecord"]["required"]),
    )

    # Then: authorization, all-pass evidence, and append-only audit fields are documented.
    assert required == (
        set(FinalHoldoutAccessRequest.model_fields),
        set(FinalHoldoutPromotionEvidence.model_fields),
        set(HoldoutAccessRecord.model_fields),
    )
