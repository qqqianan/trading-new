"""Rate-limited official Shanghai Stock Exchange archive client."""

from typing import Final
from urllib.parse import urljoin

import httpx2

from ashare_lab.data.sse_challenge import solve_sse_cookie
from ashare_lab.data.sse_models import (
    SseBulletinEnvelope,
    SseBulletinLookup,
    SsePdfDocument,
)
from ashare_lab.data.sync_service import RequestPacer

_QUERY_URL: Final = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
_BASE_URL: Final = "https://www.sse.com.cn/"
_HEADERS: Final = (
    ("User-Agent", "Mozilla/5.0"),
    ("Referer", "https://www.sse.com.cn/"),
)


class SseArchiveClient:
    """Own every SSE request used by historical-industry source audits."""

    def __init__(self, http: httpx2.Client, pacer: RequestPacer) -> None:
        """Bind one owned HTTP client and mandatory provider pacer."""
        self._http = http
        self._pacer = pacer

    def search_prospectuses(self, code: str) -> SseBulletinLookup:
        """Query the official company bulletin index for prospectuses."""
        self._pacer.wait()
        response = self._http.get(
            _QUERY_URL,
            params={
                "isPagination": "true",
                "productId": code,
                "keyWord": "招股说明书",
                "securityType": "0101,120100,020100,020200,120200",
                "pageHelp.pageSize": "25",
                "pageHelp.pageNo": "1",
                "pageHelp.beginPage": "1",
                "pageHelp.endPage": "5",
            },
            headers=_HEADERS,
        )
        response.raise_for_status()
        envelope = SseBulletinEnvelope.model_validate_json(response.content)
        return SseBulletinLookup(payload=response.content, hits=envelope.result)

    def fetch_pdf(self, attachment_url: str) -> SsePdfDocument:
        """Download one official PDF, retrying one recognized cookie challenge."""
        url = urljoin(_BASE_URL, attachment_url.strip())
        self._pacer.wait()
        response = self._http.get(url, headers=_HEADERS)
        response.raise_for_status()
        cookie = solve_sse_cookie(response.content)
        if cookie is None:
            return SsePdfDocument(url=str(response.url), content=response.content)
        self._pacer.wait()
        retried = self._http.get(
            response.url,
            headers=(*_HEADERS, ("Cookie", cookie)),
        )
        retried.raise_for_status()
        return SsePdfDocument(url=str(retried.url), content=retried.content)
