"""Stable content identity for exact ordered fold-training rows."""

import hashlib
from io import BytesIO

import polars as pl


def training_frame_sha256(frame: pl.DataFrame) -> str:
    """Hash exact ordered training rows without a pandas conversion."""
    with BytesIO() as buffer:
        frame.write_ipc(buffer, compression="uncompressed")
        return hashlib.sha256(buffer.getvalue()).hexdigest()
