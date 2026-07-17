"""Typed Mongo persistence failures."""


class RawPersistenceError(Exception):
    """A Raw snapshot failed strict MongoDB validation during append."""

    __slots__ = ("snapshot_id",)

    def __init__(self, snapshot_id: str) -> None:
        """Bind the failure to its non-secret immutable snapshot identity."""
        super().__init__()
        self.snapshot_id = snapshot_id

    def __str__(self) -> str:
        """Return a concise failure without dumping provider payloads."""
        return f"Raw snapshot failed MongoDB validation: {self.snapshot_id}"
