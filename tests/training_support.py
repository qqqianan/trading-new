import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from ashare_lab.research.datasets.spec import DatasetSpec, FeatureRef, LabelRef
from ashare_lab.research.datasets.spec_store import DatasetSpecStore
from ashare_lab.research.experiments.manifest import ExperimentManifest, ModelFamily
from ashare_lab.research.model_evidence import (
    ContentDocumentDescriptor,
    DevelopmentTrainingEvidence,
    TrainingDataKind,
    TrainingFieldLineage,
    TrainingLineageDocument,
    TrainingSchemaDocument,
)
from ashare_lab.research.model_governance import ModelPurpose
from ashare_lab.research.preprocessing import FoldPreprocessor
from ashare_lab.research.preprocessing.store import FoldPreprocessorStore
from ashare_lab.research.preprocessing.training_identity import training_frame_sha256
from ashare_lab.research.splits.walk_forward import WalkForwardFold

FEATURES = ("factor_a", "factor_b")
LABEL = "relative_return_20d"


def training_frame(*, test_label_shift: float = 0.0) -> pl.DataFrame:
    timezone = ZoneInfo("Asia/Shanghai")
    start = date(2023, 1, 2)
    dates = tuple(start + timedelta(days=index) for index in range(12))
    rows: list[dict[str, str | float | datetime]] = []
    for date_index, trading_date in enumerate(dates):
        for symbol_index in range(4):
            factor_a = float(symbol_index - 1.5)
            factor_b = float((symbol_index % 2) * 2 - 1)
            label = 0.7 * factor_a - 0.2 * factor_b
            if date_index >= 10:
                label += test_label_shift * (1 if symbol_index % 2 == 0 else -1)
            rows.append(
                {
                    "decision_time": datetime(
                        trading_date.year,
                        trading_date.month,
                        trading_date.day,
                        18,
                        tzinfo=timezone,
                    ),
                    "symbol": f"00000{symbol_index + 1}.SZ",
                    "factor_a": factor_a + date_index * 0.01,
                    "factor_b": factor_b,
                    "log_total_mv": float(10 + symbol_index),
                    LABEL: label,
                }
            )
    return pl.DataFrame(rows)


def folds() -> tuple[WalkForwardFold, ...]:
    dates = tuple(date(2023, 1, 2) + timedelta(days=index) for index in range(12))
    return (
        WalkForwardFold(0, dates[:6], dates[6:8], dates[8:10]),
        WalkForwardFold(1, dates[:8], dates[8:10], dates[10:12]),
    )


def build_training_evidence(
    root: Path,
    frame: pl.DataFrame,
    *,
    purpose: ModelPurpose = ModelPurpose.RESEARCH_ONLY,
    data_kind: TrainingDataKind = TrainingDataKind.SYNTHETIC_QA,
) -> tuple[DevelopmentTrainingEvidence, ExperimentManifest]:
    input_schema_id = "schema_" + "a" * 64
    lineage_id = "lineage_" + "b" * 64
    spec = DatasetSpec(
        rulebook_version="1.1.0",
        coverage_report_id="coverage_abc123",
        input_manifest_id="inputs_abc123",
        source_snapshot_ids=("snapshot_abc123",),
        schema_manifest_id=input_schema_id,
        input_schema_manifest_ids=(input_schema_id,),
        lineage_manifest_id=lineage_id,
        feature_artifact_ids=("feature_a", "feature_b"),
        feature_lineage_edge_ids=("edge_a", "edge_b"),
        label_artifact_id="label_a",
        label_lineage_edge_ids=("edge_label",),
        universe_version="universe_v1",
        features=(
            FeatureRef(name="factor_a", version="1.0.0"),
            FeatureRef(name="factor_b", version="1.0.0"),
        ),
        label=LabelRef(name=LABEL, version="1.0.0"),
        start_date=date(2023, 1, 2),
        end_date=date(2023, 1, 13),
    )
    dataset_descriptor = DatasetSpecStore(root).write(spec)
    schema = TrainingSchemaDocument(
        dataset_snapshot_id=spec.snapshot_id,
        feature_names=FEATURES,
        size_feature_name="log_total_mv",
        label_name=LABEL,
    )
    lineage = TrainingLineageDocument(
        lineage_manifest_id=lineage_id,
        dataset_snapshot_id=spec.snapshot_id,
        fields=tuple(
            TrainingFieldLineage(
                field_name=name,
                source_artifact_ids=("artifact_" + name,),
                raw_snapshot_ids=("snapshot_abc123",),
            )
            for name in (*FEATURES, "log_total_mv", LABEL)
        ),
    )
    schema_descriptor = _write_document(root / "training_schema.json", schema.model_dump_json())
    training_schema_id = f"schema_{schema_descriptor.data_sha256}"
    lineage_descriptor = _write_document(root / "training_lineage.json", lineage.model_dump_json())
    preprocessor_store = FoldPreprocessorStore(root)
    preprocessor_descriptors = []
    for fold in folds():
        train = frame.filter(pl.col("decision_time").dt.date().is_in(fold.train))
        artifact = FoldPreprocessor(FEATURES, "log_total_mv").fit(
            train,
            f"fold_{fold.fold_index:03d}",
            spec.snapshot_id,
        )
        preprocessor_descriptors.append(preprocessor_store.write(artifact))
    experiment = ExperimentManifest(
        training_run_id="run_ridge_001",
        dataset_snapshot_id=spec.snapshot_id,
        schema_manifest_id=training_schema_id,
        lineage_manifest_id=lineage_id,
        rulebook_version="1.1.0",
        git_commit="a" * 40,
        model_family=ModelFamily.RIDGE,
        feature_names=FEATURES,
        size_feature_name="log_total_mv",
        label_name=LABEL,
        split_protocol="purged_walk_forward_v1",
        random_seed=7,
        final_test_runs=0,
        ridge_alphas=(0.1, 1.0, 10.0, 100.0),
        preprocessor_artifact_ids=tuple(item.artifact_id for item in preprocessor_descriptors),
        trial_batch_id="trial_batch_" + "c" * 64,
        portfolio_rule_version="top30_risk_v1",
        cost_rule_version="china_a_cost_v1",
    )
    evidence = DevelopmentTrainingEvidence(
        purpose=purpose,
        data_kind=data_kind,
        artifact_root=root,
        dataset_descriptor=dataset_descriptor,
        schema_descriptor=schema_descriptor,
        lineage_descriptor=lineage_descriptor,
        preprocessor_descriptors=tuple(preprocessor_descriptors),
        development_data_sha256=training_frame_sha256(frame),
        holdout_ledger_root=root,
        holdout_spec_id="holdout_spec_" + "d" * 64,
    )
    return evidence, experiment


def _write_document(path: Path, content: str) -> ContentDocumentDescriptor:
    payload = f"{content}\n".encode()
    path.write_bytes(payload)
    return ContentDocumentDescriptor(path=path, data_sha256=hashlib.sha256(payload).hexdigest())
