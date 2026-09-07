"""Rate-limited client for exact official CAPCO archive attachments."""

import httpx2

from ashare_lab.data.capco_membership_models import CapcoPdfDocument
from ashare_lab.data.sync_service import RequestPacer


class CapcoArchiveClient:
    """Own every CAPCO attachment request used by membership source audits."""

    def __init__(self, http: httpx2.Client, pacer: RequestPacer) -> None:
        """Bind one owned HTTP client and mandatory provider pacer."""
        self._http = http
        self._pacer = pacer

    def fetch_pdf(self, url: str) -> CapcoPdfDocument:
        """Download the exact parent-bound official attachment."""
        self._pacer.wait()
        response = self._http.get(url)
        response.raise_for_status()
        return CapcoPdfDocument(url=str(response.url), content=response.content)
