"""Strict Tushare HTTP boundary without dataframe dependencies."""

from dataclasses import dataclass
from typing import TypedDict

import httpx2
from pydantic import BaseModel, ConfigDict

Scalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class QueryParam:
    """One deterministic Tushare request parameter."""

    name: str
    value: str


@dataclass(frozen=True, slots=True)
class TushareQuery:
    """Endpoint, parameters, and explicit provider field projection."""

    endpoint: str
    params: tuple[QueryParam, ...]
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TushareRow:
    """One provider row retaining provider column order."""

    values: tuple[Scalar, ...]


@dataclass(frozen=True, slots=True)
class TushareTable:
    """Parsed provider response before normalization."""

    fields: tuple[str, ...]
    rows: tuple[TushareRow, ...]


class _WireRequest(TypedDict):
    api_name: str
    token: str
    params: dict[str, str]
    fields: str


class _WireData(BaseModel):
    model_config = ConfigDict(frozen=True)

    fields: tuple[str, ...]
    items: tuple[tuple[Scalar, ...], ...]


class _WireResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str | None = None
    code: int
    msg: str | None
    data: _WireData | None


class TushareApiError(Exception):
    """Tushare rejected a request or returned no structured data."""

    __slots__ = ("code", "detail")

    def __init__(self, code: int, detail: str) -> None:
        """Create a provider error without retaining request credentials."""
        super().__init__()
        self.code = code
        self.detail = detail

    def __str__(self) -> str:
        """Return the provider code and non-secret error detail."""
        return f"Tushare error {self.code}: {self.detail}"


class TushareClient:
    """Fetch explicit Tushare tables through an owned HTTP client."""

    _URL = "http://api.tushare.pro"

    def __init__(self, token: str, http_client: httpx2.Client) -> None:
        """Bind a secret token to an explicitly owned HTTP client."""
        self._token = token
        self._http_client = http_client

    def fetch(self, query: TushareQuery) -> TushareTable:
        """Execute one query and parse its typed tabular response."""
        payload: _WireRequest = {
            "api_name": query.endpoint,
            "token": self._token,
            "params": {item.name: item.value for item in query.params},
            "fields": ",".join(query.fields),
        }
        response = self._http_client.post(self._URL, json=payload)
        response.raise_for_status()
        wire = _WireResponse.model_validate_json(response.content)
        if wire.code != 0 or wire.data is None:
            raise TushareApiError(wire.code, wire.msg or "provider returned no data")
        return TushareTable(
            fields=wire.data.fields,
            rows=tuple(TushareRow(values=item) for item in wire.data.items),
        )

    @staticmethod
    def table_for_test(
        fields: tuple[str, ...],
        rows: tuple[tuple[Scalar, ...], ...],
    ) -> TushareTable:
        """Construct a provider-shaped table without a network request."""
        return TushareTable(fields=fields, rows=tuple(TushareRow(values=row) for row in rows))
