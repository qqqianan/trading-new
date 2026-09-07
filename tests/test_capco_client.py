import httpx2

from ashare_lab.data.capco_client import CapcoArchiveClient
from ashare_lab.data.sync_service import RequestPacer


def test_capco_attachment_download_uses_exact_url_and_request_pacer() -> None:
    # Given: one registered official attachment and a wire-level request recorder.
    requests: list[httpx2.Request] = []
    waits: list[float] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, content=b"%PDF-capco")

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = CapcoArchiveClient(http, RequestPacer(0.5, sleeper=waits.append))

        # When: the exact parent-bound URL is fetched.
        document = provider.fetch_pdf("https://sp.capco.org.cn:82/2023h1.pdf")

    # Then: bytes and effective URL are retained after one paced request.
    assert document.content == b"%PDF-capco"
    assert str(requests[0].url) == "https://sp.capco.org.cn:82/2023h1.pdf"
    assert waits == [0.5]
