from datetime import date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ashare_lab.research.experiments.promotion import evaluate_model_promotion
from ashare_lab.research.experiments.promotion_store import PromotionEvaluationStore
from ashare_lab.research.experiments.protocol_identity import create_rank_aligned_protocol
from ashare_lab.research.experiments.protocol_store import ModelProtocolStore
from ashare_lab.research.splits.final_holdout import (
    FinalHoldoutAccessLedger,
    FinalHoldoutAccessRequest,
    FinalHoldoutSpec,
    FrozenResearchProtocol,
    HoldoutAccessRecord,
)
from ashare_lab.research.splits.walk_forward import DEVELOPMENT_END
from ashare_lab.services.model_final_holdout import (
    ModelFinalHoldoutError,
    open_model_final_holdout,
)

from .test_model_promotion import DIAGNOSTIC_ID, passing_diagnostic
from .test_model_protocol import protocol_request


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


def _persisted_chain(
    tmp_path: Path,
    industry_status: Literal["AVAILABLE", "UNAVAILABLE"],
) -> tuple[FinalHoldoutAccessRequest, FinalHoldoutSpec]:
    artifact_root = tmp_path / "data" / "artifacts"
    spec = FinalHoldoutSpec(
        dataset_snapshot_id="ds_abc123",
        development_end=DEVELOPMENT_END,
        holdout_start=date(2025, 1, 1),
        protocol_version="1.0.0",
    )
    request_payload = protocol_request().model_copy(update={"holdout_spec_id": spec.spec_id})
    protocol = create_rank_aligned_protocol(request_payload)
    ModelProtocolStore(artifact_root).write(protocol)
    diagnostic = passing_diagnostic().model_copy(
        update={"industry_neutralization": industry_status}
    )
    evaluation = evaluate_model_promotion(protocol, DIAGNOSTIC_ID, diagnostic)
    descriptor = PromotionEvaluationStore(artifact_root).write(evaluation)
    frozen = FrozenResearchProtocol(
        holdout_spec_id=spec.spec_id,
        dataset_snapshot_id=spec.dataset_snapshot_id,
        split_protocol_id=protocol.split_protocol,
        preprocessing_version=protocol.preprocessing_version,
        code_commit=protocol.code_commit,
        frozen_at=protocol.registered_at,
        frozen_by=protocol.registered_by,
    )
    return (
        FinalHoldoutAccessRequest(
            protocol_id=frozen.protocol_id,
            model_protocol_id=protocol.protocol_id,
            promotion_evaluation_id=descriptor.evaluation_id,
            model_id=evaluation.model_id,
            dataset_snapshot_id=spec.dataset_snapshot_id,
            authorized_at=datetime(2026, 7, 20, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
            authorized_by="research_owner",
            purpose="single_final_evaluation",
        ),
        spec,
    )


def test_model_final_holdout_rejects_persisted_blocked_promotion(
    tmp_path: Path,
) -> None:
    # Given: immutable promotion evidence with one failed PIT industry gate.
    access, spec = _persisted_chain(tmp_path, "UNAVAILABLE")

    # When / Then: blocked development evidence cannot create a ledger record or expose data.
    with pytest.raises(ModelFinalHoldoutError, match="development gates"):
        open_model_final_holdout(tmp_path, _frame(), access)
    assert FinalHoldoutAccessLedger(tmp_path / "data" / "governance").count(spec.spec_id) == 0


def test_model_final_holdout_opens_once_only_after_persisted_all_pass_promotion(
    tmp_path: Path,
) -> None:
    # Given: exact all-pass promotion evidence and a later explicit manual authorization.
    access, spec = _persisted_chain(tmp_path, "AVAILABLE")

    # When: the sole composition root opens the final partition.
    holdout = open_model_final_holdout(tmp_path, _frame(), access)

    # Then: only sealed rows are exposed and the exact promotion is recorded once.
    ledger = FinalHoldoutAccessLedger(tmp_path / "data" / "governance")
    record_path = (
        tmp_path / "data" / "governance" / "final_holdout_access" / spec.spec_id / "000001.json"
    )
    record = HoldoutAccessRecord.model_validate_json(record_path.read_bytes())
    assert holdout["value"].to_list() == [2.0]
    assert ledger.count(spec.spec_id) == 1
    assert record.promotion_evaluation_id == access.promotion_evaluation_id
    assert record.model_protocol_id == access.model_protocol_id
    assert record.model_id == access.model_id
