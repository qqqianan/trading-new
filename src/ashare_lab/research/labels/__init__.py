"""Governed physically isolated future labels."""

from ashare_lab.research.labels.calculator import (
    calculate_relative_open_return,
    resolve_label_window,
)
from ashare_lab.research.labels.catalog import medium_horizon_label
from ashare_lab.research.labels.definition import LabelDefinition, LabelPrice
from ashare_lab.research.labels.models import (
    BenchmarkOpenObservation,
    LabelTradeObservation,
    RelativeReturnLabelRow,
)

__all__ = [
    "BenchmarkOpenObservation",
    "LabelDefinition",
    "LabelPrice",
    "LabelTradeObservation",
    "RelativeReturnLabelRow",
    "calculate_relative_open_return",
    "medium_horizon_label",
    "resolve_label_window",
]
