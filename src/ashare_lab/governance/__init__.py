"""Stable facade for quantitative research governance gates."""

from ashare_lab.research.data_quality import DataQualityGuard
from ashare_lab.research.model_governance import ModelTrainingGuard

__all__ = ["DataQualityGuard", "ModelTrainingGuard"]
