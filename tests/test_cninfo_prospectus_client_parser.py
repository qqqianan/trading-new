import json
from datetime import date
from urllib.parse import parse_qs

import httpx2

from ashare_lab.data.cninfo_client import CninfoArchiveClient
from ashare_lab.data.cninfo_industry_parser import (
    parse_industry_disclosure,
    select_prospectus,
)
from ashare_lab.data.sync_service import RequestPacer


def test_prospectus_query_is_bounded_and_uses_the_paced_client() -> None:
    # Given: one official client and a wire recorder for the announcement endpoint.
    requests: list[httpx2.Request] = []
    waits: list[float] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, content=_announcement_payload(()))

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = CninfoArchiveClient(http, RequestPacer(0.5, sleeper=waits.append))
        lookup = provider.search_prospectuses("688190", "gfbj0839122", date(2021, 11, 26))

    form = parse_qs(requests[0].content.decode())
    assert lookup.payload == _announcement_payload(())
    assert form["searchkey"] == ["招股说明书"]
    assert form["seDate"] == ["2019-11-27~2021-11-26"]
    assert waits == [0.5]


def test_prospectus_selection_rejects_summary_correction_and_draft() -> None:
    # Given: one final full prospectus mixed with non-authoritative variants.
    payload = _announcement_payload(
        (
            ("1", "首次公开发行股票招股说明书\uff08申报稿\uff09", 1),
            ("2", "首次公开发行股票招股说明书摘要", 2),
            ("3", "首次公开发行股票招股说明书更正公告", 3),
            ("4", "首次公开发行股票并上市招股说明书\uff08注册稿\uff09", 4),
        )
    )

    selected = select_prospectus(payload)

    assert selected.announcement_id == "4"
    assert selected.title == "首次公开发行股票并上市招股说明书\uff08注册稿\uff09"


def test_prospectus_disclosure_parses_explicit_code_label_formats() -> None:
    # Given: exact prospectus formats observed in the fixed pilot failures.
    texts = (
        "所属行业\uff1a公共设施管理业\uff08代码为N78\uff09",
        "行业分类 F51 批发业",
        "上市公司行业分类 C制造业 C38 电气机械和器材制造业",
        (
            "根据中国证监会《上市公司行业分类指引》\uff082012年修订\uff09\uff0c"
            "公司所处行业为农业\uff08行业代码\uff1aA01\uff09"
        ),
        (
            "上市公司行业分类C制造业C38电气机械和器材制造业"
            "管理型行业分类C制造业C38电气机械和器材制造业"
        ),
        "上市公司行业分类A农、林、牧、渔业A01农业管理型行业分类A01农业",
    )

    parsed = tuple(parse_industry_disclosure(text) for text in texts)

    assert tuple((item.industry_code, item.industry_name) for item in parsed) == (
        ("N78", "公共设施管理业"),
        ("F51", "批发业"),
        ("C38", "电气机械和器材制造业"),
        ("A01", "农业"),
        ("C38", "电气机械和器材制造业"),
        ("A01", "农业"),
    )
    assert parsed[3].taxonomy == "CSRC_2012"


def test_disclosure_maps_ordered_csrc_and_national_economy_codes_without_truncation() -> None:
    # Given: two named taxonomies followed by explicitly corresponding industry codes.
    text = (
        "根据中国证监会颁布的《上市公司行业分类指引》\uff082012年修订\uff09及国家统计局发布的"
        "《国民经济行业分类》\uff08GB/T4754-2011\uff09\uff0c公司所属行业为“电力、热力、燃气及水生产和"
        "供应业”中的“燃气生产和供应业”\uff0c行业代码分别为 D45 和 D4500。"
    )

    # When: the disclosure is parsed under the ordered-taxonomy rule.
    disclosure = parse_industry_disclosure(text)

    # Then: the explicit CSRC code is selected; the four-digit code is not truncated.
    assert disclosure.industry_code == "D45"
    assert disclosure.industry_name == "燃气生产和供应业"
    assert disclosure.taxonomy == "CSRC_2012"


def test_disclosure_prefers_explicit_company_scope_over_secondary_product_scope() -> None:
    # Given: the company classification and a later secondary-product classification.
    text = (
        "根据中国证监会颁布的《上市公司行业分类指引》\uff082012年修订\uff09\uff0c公司所处行业为"
        "计算机、通信和其他电子设备制造业\uff08分类代码\uff1aC39\uff09\u3002"
        "根据《上市公司行业分类指引》\uff082012年修订\uff09\uff0c碳纳米管产品属于“C26-化学原料和"
        "化学制品制造业”\u3002"
    )

    # When: the issuer-level declaration is parsed.
    disclosure = parse_industry_disclosure(text)

    # Then: a secondary product classification cannot replace the company industry.
    assert disclosure.industry_code == "C39"
    assert disclosure.industry_name == "计算机、通信和其他电子设备制造业"
    assert disclosure.taxonomy == "CSRC_2012"


def _announcement_payload(rows: tuple[tuple[str, str, int], ...]) -> bytes:
    announcements = [
        {
            "announcementId": announcement_id,
            "announcementTitle": title,
            "announcementTime": timestamp,
            "adjunctUrl": f"finalpage/2021-11-09/{announcement_id}.PDF",
            "adjunctSize": 1024,
            "adjunctType": "PDF",
            "secCode": "688190",
            "secName": "云路股份",
            "orgId": "gfbj0839122",
        }
        for announcement_id, title, timestamp in rows
    ]
    return json.dumps(
        {
            "totalAnnouncement": len(announcements),
            "announcements": announcements,
            "hasMore": False,
        },
        ensure_ascii=False,
    ).encode()
