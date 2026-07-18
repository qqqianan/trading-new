"""Minimal Mongo read capabilities for PIT financial factors."""

from collections.abc import Iterable
from typing import Protocol

from ashare_lab.data.bson_types import BsonDocument


class FinancialCollection(Protocol):
    """Read capability required from the PIT financial collection."""

    def find(
        self,
        query: BsonDocument,
        projection: BsonDocument | None = None,
    ) -> Iterable[BsonDocument]:
        """Return accepted documents matching one bounded query."""
        ...


class FinancialDatabase(Protocol):
    """Named database capability used by the financial reader."""

    name: str

    def __getitem__(self, name: str) -> FinancialCollection:
        """Return one governed collection."""
        ...


class FinancialReaderError(Exception):
    """The reader boundary or cutoff violates the governed contract."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record the rejected database or cutoff detail."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable reader rule and detail."""
        return f"financial_factor_reader: {self.detail}"
