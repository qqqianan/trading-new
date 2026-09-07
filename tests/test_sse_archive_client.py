import json
from urllib.parse import parse_qs

import httpx2

from ashare_lab.data.sse_client import SseArchiveClient
from ashare_lab.data.sync_service import RequestPacer


def test_sse_query_uses_exact_company_filter_and_request_pacer() -> None:
    # Given: one official SSE response and a wire-level request recorder.
    requests: list[httpx2.Request] = []
    waits: list[float] = []
    payload = _lookup_payload()

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, content=payload)

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = SseArchiveClient(http, RequestPacer(0.5, sleeper=waits.append))

        # When: the official company bulletin endpoint is queried.
        lookup = provider.search_prospectuses("688190")

    # Then: exact query bytes and parsed official identity are retained.
    query = parse_qs(requests[0].url.query.decode())
    assert lookup.payload == payload
    assert lookup.hits[0].security_code == "688190"
    assert query["productId"] == ["688190"]
    assert query["keyWord"] == ["招股说明书"]
    assert waits == [0.5]


def test_sse_pdf_download_retries_one_recognized_cookie_challenge() -> None:
    # Given: the SSE anti-bot challenge followed by the official PDF bytes.
    requests: list[httpx2.Request] = []
    waits: list[float] = []
    challenge = b"<html><script>var arg1='258098967B324E588E9DC576CEA569B0FAA953CE';</script>"

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        content = b"%PDF-official-sse" if len(requests) == 2 else challenge
        return httpx2.Response(200, content=content)

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = SseArchiveClient(http, RequestPacer(0.5, sleeper=waits.append))

        # When: the selected attachment is fetched through the paced adapter.
        document = provider.fetch_pdf("/disclosure/document.pdf")

    # Then: the retry carries the solved cookie and remains rate limited.
    assert document.content == b"%PDF-official-sse"
    assert requests[1].headers["cookie"] == ("acw_sc__v2=6a66ef43b71e8a51c296cf85dc0d3090ae05a65c")
    assert waits == [0.5, 0.5]


def _lookup_payload() -> bytes:
    return json.dumps(
        {
            "result": [
                {
                    "ADDDATE": "2021-11-21 15:30:12",
                    "SECURITY_CODE": "688190",
                    "SECURITY_NAME": "云路股份",
                    "SSEDATE": "2021-11-22",
                    "TITLE": "云路股份首次公开发行股票并在科创板上市招股说明书",
                    "URL": (
                        "/disclosure/listedinfo/announcement/c/new/2021-11-22/"
                        "688190_20211122_1_e9bbdBw0.pdf"
                    ),
                }
            ]
        },
        ensure_ascii=False,
    ).encode()
