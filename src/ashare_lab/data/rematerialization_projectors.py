"""Concrete canonical-to-PIT projectors used only by Raw rematerialization."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ashare_lab.data.financial_indicators import build_financial_indicator_version
from ashare_lab.data.industry_memberships import (
    build_industry_membership,
    validate_industry_membership_batch,
)
from ashare_lab.data.rematerialization import ProjectionResult
from ashare_lab.data.schema_registry import SchemaContractError
from ashare_lab.data.universe_builder import build_lifecycle_events, build_name_status_event

if TYPE_CHECKING:
    from ashare_lab.data.canonical import CanonicalBatch
    from ashare_lab.data.financial_indicator_store import IndicatorWriteResult
    from ashare_lab.data.financial_indicators import FinancialIndicatorVersion
    from ashare_lab.data.industry_memberships import IndustryMembership
    from ashare_lab.data.industry_store import IndustryWriteResult
    from ashare_lab.data.snapshots import SnapshotBatch
    from ashare_lab.data.universe import SecurityEvent
    from ashare_lab.data.universe_store import UniverseEventWriteResult


class UniverseEventSink(Protocol):
    """Append-only boundary for deterministic security events."""

    def write(self, events: tuple[SecurityEvent, ...]) -> UniverseEventWriteResult:
        """Persist one immutable event group."""
        ...


class FinancialIndicatorSink(Protocol):
    """Append-only boundary for publication-timed indicator versions."""

    def write_batch(
        self,
        canonical: CanonicalBatch,
        events: tuple[FinancialIndicatorVersion, ...],
    ) -> IndicatorWriteResult:
        """Persist events and batch completion evidence."""
        ...


class IndustryMembershipSink(Protocol):
    """Append-only boundary for observed industry intervals."""

    def write_batch(
        self,
        canonical: CanonicalBatch,
        events: tuple[IndustryMembership, ...],
    ) -> IndustryWriteResult:
        """Persist intervals and batch completion evidence."""
        ...


class CanonicalOnlyProjector:
    """Keep replay at canonical when no event projection is required."""

    @staticmethod
    def project(batch: SnapshotBatch, canonical: CanonicalBatch) -> ProjectionResult:
        """Return an explicit zero-event result."""
        del batch, canonical
        return ProjectionResult(0, 0)


class UniverseProjector:
    """Replay stock master and name history into stable PIT events."""

    def __init__(self, store: UniverseEventSink) -> None:
        """Bind the owned universe event store."""
        self._store = store

    def project(self, batch: SnapshotBatch, canonical: CanonicalBatch) -> ProjectionResult:
        """Rebuild only the event variant registered for the Raw endpoint."""
        events: list[SecurityEvent] = []
        match batch.snapshot.endpoint:
            case "stock_basic":
                for record in canonical.records:
                    events.extend(build_lifecycle_events(record))
            case "namechange":
                events.extend(build_name_status_event(record) for record in canonical.records)
            case unsupported:
                detail = f"unsupported universe replay endpoint: {unsupported}"
                raise SchemaContractError(detail)
        written = self._store.write(tuple(events))
        return ProjectionResult(written.event_count, written.inserted_count)


class FinancialIndicatorProjector:
    """Replay quarantined indicator rows into publication-timed versions."""

    def __init__(self, store: FinancialIndicatorSink) -> None:
        """Bind the owned financial indicator store."""
        self._store = store

    def project(self, batch: SnapshotBatch, canonical: CanonicalBatch) -> ProjectionResult:
        """Rebuild indicator events and empty-batch completion evidence."""
        if batch.snapshot.endpoint != "fina_indicator":
            detail = f"unsupported financial indicator replay endpoint: {batch.snapshot.endpoint}"
            raise SchemaContractError(detail)
        events = tuple(build_financial_indicator_version(record) for record in canonical.records)
        written = self._store.write_batch(canonical, events)
        return ProjectionResult(written.event_count, written.inserted_count)


class IndustryProjector:
    """Replay observed industry member snapshots without historical backfill."""

    def __init__(self, store: IndustryMembershipSink) -> None:
        """Bind the owned industry membership store."""
        self._store = store

    def project(self, batch: SnapshotBatch, canonical: CanonicalBatch) -> ProjectionResult:
        """Rebuild exact observed-at membership intervals."""
        if batch.snapshot.endpoint != "index_member":
            detail = f"unsupported industry replay endpoint: {batch.snapshot.endpoint}"
            raise SchemaContractError(detail)
        validate_industry_membership_batch(canonical)
        events = tuple(build_industry_membership(record) for record in canonical.records)
        written = self._store.write_batch(canonical, events)
        return ProjectionResult(written.event_count, written.inserted_count)
