"""Strict recursive BSON value types shared by MongoDB adapters."""

from datetime import datetime

type BsonScalar = str | int | float | bool | datetime | None
type BsonValue = BsonScalar | list[BsonValue] | dict[str, BsonValue]
type BsonDocument = dict[str, BsonValue]
