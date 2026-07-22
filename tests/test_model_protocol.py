import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from ashare_lab.research.experiments.protocol_identity import (
    ModelProtocolRequest,
    create_rank_aligned_protocol,
)
from ashare_lab.research.experiments.protocol_models import (
    DevelopmentPromotionGates,
    FinalHoldoutPolicy,
    ModelExperimentProtocol,
)
from ashare_lab.research.experiments.protocol_store import (
    ModelProtocolDescriptor,
    ModelProtocolStore,
    ModelProtocolStoreError,
)

ROOT = Path(__file__).parents[1]


def protocol_request() -> ModelProtocolRequest:
    return ModelProtocolRequest(
        dataset_snapshot_id="ds_abc123",
        schema_manifest_id="schema_" + "a" * 64,
        lineage_manifest_id="lineage_" + "b" * 64,
        parent_model_id="ridge_model_" + "c" * 64,
        parent_diagnostic_report_id="model_diagnostic_" + "d" * 64,
        registered_at=datetime(2026, 7, 20, 19, tzinfo=ZoneInfo("Asia/Shanghai")),
        registered_by="research_owner",
        code_commit="e" * 40,
        rulebook_version="1.1.0",
        feature_names=("factor_a", "factor_b"),
        label_name="relative_open_return_20d_csi500",
        cost_rule_version="china_a_cost_v1",
        risk_rule_version="portfolio_risk_v1",
        holdout_spec_id="holdout_spec_" + "f" * 64,
    )


def test_rank_aligned_protocol_freezes_post_hoc_scope_and_promotion_gates() -> None:
    # Given: exact parent evidence and an explicit owner registration time.
    request = protocol_request()

    # When: the next experiment is preregistered before trainer implementation.
    protocol = create_rank_aligned_protocol(request)

    # Then: ranking, baseline, risk, industry, and single-use holdout gates are immutable.
    assert protocol.candidate_model_family == "ridge_rank"
    assert protocol.evidence_classification == "POST_HOC_DERIVED_NEW_EXPERIMENT"
    assert protocol.promotion_gates.minimum_fold_rank_ic == 0.0
    assert protocol.promotion_gates.require_baseline_sharpe_outperformance is True
    assert protocol.promotion_gates.forbid_risk_halt is True
    assert protocol.promotion_gates.require_complete_industry_pit is True
    assert protocol.final_holdout.maximum_accesses == 1
    assert protocol.final_holdout.requires_manual_authorization is True
    assert protocol.status == "PREREGISTERED_NOT_IMPLEMENTED"


def test_model_protocol_store_is_append_only_and_content_addressed(tmp_path: Path) -> None:
    # Given: one preregistered protocol and an empty append-only store.
    protocol = create_rank_aligned_protocol(protocol_request())
    store = ModelProtocolStore(tmp_path)

    # When: identical registration is written twice.
    descriptors = (store.write(protocol), store.write(protocol))

    # Then: one stable protocol identity and one directory are reused.
    assert descriptors[0] == descriptors[1]
    assert store.read(descriptors[0]) == protocol
    assert len(tuple((tmp_path / "model_protocols").iterdir())) == 1


def test_model_protocol_store_rejects_relabelled_identity(tmp_path: Path) -> None:
    # Given: valid protocol content carrying a caller-substituted protocol ID.
    protocol = create_rank_aligned_protocol(protocol_request()).model_copy(
        update={"protocol_id": "model_protocol_" + "0" * 64}
    )

    # When / Then: identity is recomputed before any bytes are published.
    with pytest.raises(ModelProtocolStoreError, match="identity differs"):
        ModelProtocolStore(tmp_path).write(protocol)


def test_model_protocol_store_rejects_cross_boundary_descriptor(tmp_path: Path) -> None:
    # Given: a valid protocol descriptor relabeled to another path.
    store = ModelProtocolStore(tmp_path)
    descriptor = store.write(create_rank_aligned_protocol(protocol_request()))
    crossed = ModelProtocolDescriptor(
        protocol_id=descriptor.protocol_id,
        manifest_path=tmp_path / "other.json",
        data_sha256=descriptor.data_sha256,
    )

    # When / Then: protocol evidence cannot cross its append-only directory.
    with pytest.raises(ModelProtocolStoreError, match="boundary"):
        store.read(crossed)


def test_model_protocol_rejects_overlapping_holdout_and_duplicate_features() -> None:
    # Given: valid protocol data relabeled with overlapping dates and duplicate features.
    protocol = create_rank_aligned_protocol(protocol_request())
    payload = protocol.model_dump(mode="json")
    payload["feature_names"] = ["factor_a", "factor_a"]
    payload["final_holdout"]["holdout_start"] = date(2024, 12, 31)

    # When / Then: both illegal evaluation states are rejected at the trust boundary.
    with pytest.raises(ValidationError, match="final holdout must start after development"):
        ModelExperimentProtocol.model_validate(payload)


def test_model_protocol_rejects_naive_registration_time() -> None:
    # Given: valid preregistration inputs except an ambiguous local timestamp.
    registered_at = protocol_request().registered_at
    request = protocol_request().model_copy(
        update={"registered_at": registered_at.replace(tzinfo=None)}
    )

    # When / Then: direct service callers cannot bypass the timezone contract.
    with pytest.raises(ValidationError, match="registration time must be timezone-aware"):
        create_rank_aligned_protocol(request)


def test_model_protocol_schema_documents_every_field() -> None:
    # Given: the committed machine schema for preregistered model experiments.
    document = json.loads(
        (ROOT / "schemas" / "model_experiment_protocol_v1.json").read_text(encoding="utf-8")
    )

    # When: required fields are compared with every Pydantic trust boundary.
    required = (
        set(document["required"]),
        set(document["$defs"]["DevelopmentPromotionGates"]["required"]),
        set(document["$defs"]["FinalHoldoutPolicy"]["required"]),
    )

    # Then: no preregistration or gate field remains undocumented.
    assert required == (
        set(ModelExperimentProtocol.model_fields),
        set(DevelopmentPromotionGates.model_fields),
        set(FinalHoldoutPolicy.model_fields),
    )
