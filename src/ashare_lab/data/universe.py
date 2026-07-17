"""Point-in-time security lifecycle and name-status events."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique


@unique
class SecurityEventType(StrEnum):
    """Closed event variants that can change historical universe state."""

    LISTED = "LISTED"
    FIRST_TRADED = "FIRST_TRADED"
    DELISTED = "DELISTED"
    NAME_STATUS = "NAME_STATUS"


@dataclass(frozen=True, slots=True)
class SecurityEvent:
    """One immutable state transition with effective and knowledge times."""

    event_id: str
    ts_code: str
    event_type: SecurityEventType
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    name: str | None
    is_st: bool | None
    source_endpoint: str
    source_snapshot_id: str
    source_row_sha256: str
    input_schema_manifest_id: str
    schema_manifest_id: str
    transform_name: str
    transform_version: str
    quality_status: str
    quality_report_id: str


@dataclass(frozen=True, slots=True)
class SecurityState:
    """Historical state exposed at one decision time without future outcomes."""

    ts_code: str
    listed: bool
    listed_at: datetime | None
    name: str | None
    is_st: bool | None
    status_known: bool
    last_event_at: datetime
    latest_available_at: datetime


@dataclass(frozen=True, slots=True)
class _FoldedState:
    listed: bool
    listed_at: datetime | None
    name: str | None
    is_st: bool | None
    last_event_at: datetime
    latest_available_at: datetime


def select_security_states(
    events: tuple[SecurityEvent, ...],
    decision_time: datetime,
) -> tuple[SecurityState, ...]:
    """Fold only accepted and point-in-time available events into listed states."""
    return tuple(state for state in replay_security_states(events, decision_time) if state.listed)


def replay_security_states(
    events: tuple[SecurityEvent, ...],
    decision_time: datetime,
) -> tuple[SecurityState, ...]:
    """Replay all ever-observed lifecycle states without survivorship filtering."""
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        msg = "decision_time must be timezone-aware"
        raise ValueError(msg)
    visible = tuple(
        event
        for event in events
        if event.quality_status == "ACCEPTED"
        and event.available_at <= decision_time
        and event.effective_at <= decision_time
    )
    folded: dict[str, _FoldedState] = {}
    for event in sorted(visible, key=_event_order):
        previous = folded.get(
            event.ts_code,
            _FoldedState(
                listed=False,
                listed_at=None,
                name=None,
                is_st=None,
                last_event_at=event.effective_at,
                latest_available_at=event.available_at,
            ),
        )
        match event.event_type:
            case SecurityEventType.LISTED | SecurityEventType.FIRST_TRADED:
                state = _FoldedState(
                    listed=True,
                    listed_at=(previous.listed_at if previous.listed else event.effective_at),
                    name=previous.name,
                    is_st=previous.is_st,
                    last_event_at=event.effective_at,
                    latest_available_at=max(
                        previous.latest_available_at,
                        event.available_at,
                    ),
                )
            case SecurityEventType.DELISTED:
                state = _FoldedState(
                    listed=False,
                    listed_at=previous.listed_at,
                    name=previous.name,
                    is_st=previous.is_st,
                    last_event_at=event.effective_at,
                    latest_available_at=max(
                        previous.latest_available_at,
                        event.available_at,
                    ),
                )
            case SecurityEventType.NAME_STATUS:
                state = _FoldedState(
                    previous.listed,
                    previous.listed_at,
                    event.name,
                    event.is_st,
                    event.effective_at,
                    max(previous.latest_available_at, event.available_at),
                )
        folded[event.ts_code] = state
    return tuple(
        SecurityState(
            ts_code=ts_code,
            listed=state.listed,
            listed_at=state.listed_at,
            name=state.name,
            is_st=state.is_st,
            status_known=state.name is not None and state.is_st is not None,
            last_event_at=state.last_event_at,
            latest_available_at=state.latest_available_at,
        )
        for ts_code, state in sorted(folded.items())
    )


def _event_order(event: SecurityEvent) -> tuple[datetime, int, datetime, str]:
    match event.event_type:
        case SecurityEventType.LISTED | SecurityEventType.FIRST_TRADED:
            priority = 0
        case SecurityEventType.NAME_STATUS:
            priority = 1
        case SecurityEventType.DELISTED:
            priority = 2
    return event.effective_at, priority, event.available_at, event.event_id
