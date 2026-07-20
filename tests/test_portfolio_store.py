import json
from pathlib import Path

import pytest

from ashare_lab.portfolio.research_models import (
    PortfolioTargetBatch,
    PortfolioTargetPositionRow,
    PortfolioTargetRecord,
)
from ashare_lab.portfolio.research_store import (
    PortfolioTargetDescriptor,
    PortfolioTargetStore,
    PortfolioTargetStoreError,
)
from tests.test_portfolio_runtime import _single_factor_batch

ROOT = Path(__file__).parents[1]


def test_portfolio_target_batch_is_content_addressed(tmp_path: Path) -> None:
    # Given: the same immutable target batch used for two publications.
    batch = _single_factor_batch()
    store = PortfolioTargetStore(tmp_path)

    # When: identical governed targets are written twice.
    descriptors = (store.write(batch), store.write(batch))

    # Then: one verified artifact identity is reused.
    assert descriptors[0] == descriptors[1]
    assert store.read(descriptors[0]) == batch


def test_portfolio_target_schema_documents_all_fields() -> None:
    # Given: the committed machine contract for pre-risk portfolio targets.
    document = json.loads(
        (ROOT / "schemas" / "portfolio_target_batch_v1.json").read_text(encoding="utf-8")
    )

    # When: root and nested required fields are compared with trust boundaries.
    required = (
        set(document["required"]),
        set(document["$defs"]["PortfolioTargetRecord"]["required"]),
        set(document["$defs"]["PortfolioTargetPositionRow"]["required"]),
    )

    # Then: no target field can remain undocumented.
    assert required == (
        set(PortfolioTargetBatch.model_fields),
        set(PortfolioTargetRecord.model_fields),
        set(PortfolioTargetPositionRow.model_fields),
    )


def test_portfolio_target_store_rejects_cross_boundary_descriptor(tmp_path: Path) -> None:
    # Given: a valid descriptor relabeled to an arbitrary path.
    store = PortfolioTargetStore(tmp_path)
    descriptor = store.write(_single_factor_batch())
    crossed = PortfolioTargetDescriptor(
        artifact_id=descriptor.artifact_id,
        artifact_path=tmp_path / "other.json",
        data_sha256=descriptor.data_sha256,
    )

    # When / Then: target bytes cannot be read outside the fixed directory.
    with pytest.raises(PortfolioTargetStoreError, match="boundary"):
        store.read(crossed)


def test_portfolio_target_store_rejects_tampered_bytes(tmp_path: Path) -> None:
    # Given: a persisted target batch altered after publication.
    store = PortfolioTargetStore(tmp_path)
    descriptor = store.write(_single_factor_batch())
    descriptor.artifact_path.write_text("{}\n", encoding="utf-8")

    # When / Then: invalid content cannot retain the original identity.
    with pytest.raises(PortfolioTargetStoreError, match="missing or invalid"):
        store.read(descriptor)
