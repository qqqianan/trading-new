"""Fail-closed point-in-time selection for canonical records."""

from datetime import datetime

from ashare_lab.data.canonical import CanonicalRecord


def select_available_records(
    records: tuple[CanonicalRecord, ...],
    decision_time: datetime,
) -> tuple[CanonicalRecord, ...]:
    """Expose only accepted records available by the requested decision time."""
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        msg = "decision_time must be timezone-aware"
        raise ValueError(msg)
    return tuple(
        record
        for record in records
        if record.quality_status == "ACCEPTED" and record.available_at <= decision_time
    )
