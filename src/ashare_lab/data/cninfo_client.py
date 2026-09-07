"""Rate-limited CNInfo client for official listing-document audits."""

from datetime import date, timedelta
from typing import Final
from urllib.parse import urljoin

import httpx2
from pydantic import TypeAdapter

from ashare_lab.data.cninfo_models import (
    CninfoAnnouncementLookup,
    CninfoPdfDocument,
    CninfoSecurityHit,
    CninfoSecurityLookup,
)
from ashare_lab.data.sync_service import RequestPacer

_SECURITY_URL: Final = "https://www.cninfo.com.cn/new/information/topSearch/query"
_ANNOUNCEMENT_URL: Final = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
_PDF_BASE_URL: Final = "https://static.cninfo.com.cn/"
_HEADERS: Final = (
    ("User-Agent", "Mozilla/5.0"),
    ("Referer", "https://www.cninfo.com.cn/"),
    ("X-Requested-With", "XMLHttpRequest"),
)
_SECURITY_ADAPTER: Final = TypeAdapter(tuple[CninfoSecurityHit, ...])


class CninfoArchiveClient:
    """Own every CNInfo request used by the industry bridge."""

    def __init__(self, http: httpx2.Client, pacer: RequestPacer) -> None:
        """Bind an owned HTTP client and mandatory request pacer."""
        self._http = http
        self._pacer = pacer

    def lookup_security(self, code: str) -> CninfoSecurityLookup:
        """Resolve the provider organization identity for one six-digit code."""
        self._pacer.wait()
        response = self._http.post(
            _SECURITY_URL,
            params={"keyWord": code, "maxNum": "10"},
            headers=_HEADERS,
        )
        response.raise_for_status()
        hits = _SECURITY_ADAPTER.validate_json(response.content)
        return CninfoSecurityLookup(payload=response.content, hits=hits)

    def search_listing_announcements(
        self,
        code: str,
        org_id: str,
        listing_date: date,
    ) -> CninfoAnnouncementLookup:
        """Query a bounded pre-listing window for listing announcements."""
        start_date = listing_date - timedelta(days=60)
        self._pacer.wait()
        response = self._http.post(
            _ANNOUNCEMENT_URL,
            data={
                "pageNum": "1",
                "pageSize": "50",
                "stock": f"{code},{org_id}",
                "searchkey": "上市公告书",
                "seDate": f"{start_date.isoformat()}~{listing_date.isoformat()}",
                "tabName": "fulltext",
            },
            headers=_HEADERS,
        )
        response.raise_for_status()
        return CninfoAnnouncementLookup(payload=response.content)

    def search_prospectuses(
        self,
        code: str,
        org_id: str,
        listing_date: date,
    ) -> CninfoAnnouncementLookup:
        """Query a bounded pre-listing window for full registered prospectuses."""
        start_date = listing_date - timedelta(days=730)
        self._pacer.wait()
        response = self._http.post(
            _ANNOUNCEMENT_URL,
            data={
                "pageNum": "1",
                "pageSize": "50",
                "stock": f"{code},{org_id}",
                "searchkey": "招股说明书",
                "seDate": f"{start_date.isoformat()}~{listing_date.isoformat()}",
                "tabName": "fulltext",
            },
            headers=_HEADERS,
        )
        response.raise_for_status()
        return CninfoAnnouncementLookup(payload=response.content)

    def fetch_pdf(self, adjunct_url: str) -> CninfoPdfDocument:
        """Download one selected official PDF through the same rate limit."""
        url = self.resolve_pdf_url(adjunct_url)
        self._pacer.wait()
        response = self._http.get(url, headers=_HEADERS)
        response.raise_for_status()
        return CninfoPdfDocument(url=url, content=response.content)

    def resolve_pdf_url(self, adjunct_url: str) -> str:
        """Resolve one provider attachment path under the owned official origin."""
        return urljoin(_PDF_BASE_URL, adjunct_url.strip())
