import hashlib
from datetime import datetime

from ashare_lab.data.cninfo_industry_bridge import (
    BridgeStatus,
    CninfoBridgeEvidence,
    TimestampPrecision,
)
from ashare_lab.data.cninfo_prospectus_bridge import (
    CninfoProspectusBridgeAudit,
    ProspectusBridgeCandidate,
    ProspectusSourceTrace,
)


def prospectus_audit(
    candidate: ProspectusBridgeCandidate,
    *,
    observed_at: datetime,
    found: bool,
    marker: str,
) -> CninfoProspectusBridgeAudit:
    """Build one fully traced source observation for consistency tests."""
    response_hash = marker * 64
    common = {
        "security_response_sha256": "c" * 64,
        "org_id": "9900041682",
        "announcement_response_sha256": response_hash,
    }
    trace = ProspectusSourceTrace(
        **common,
        announcement_id="1211660704" if found else None,
        announcement_title="云路股份首次公开发行股票招股说明书" if found else None,
        provider_announced_at=observed_at if found else None,
        timestamp_precision=TimestampPrecision.DATE_ONLY if found else None,
        pdf_url="https://static.cninfo.com.cn/document.pdf" if found else None,
        pdf_sha256="d" * 64 if found else None,
        pdf_bytes=1024 if found else None,
    )
    evidence = (
        CninfoBridgeEvidence(
            symbol=candidate.symbol,
            listing_date=candidate.listing_date,
            **common,
            announcement_id="1211660704",
            announcement_title="云路股份首次公开发行股票招股说明书",
            provider_announced_at=observed_at,
            timestamp_precision=TimestampPrecision.DATE_ONLY,
            pdf_url="https://static.cninfo.com.cn/document.pdf",
            pdf_sha256="d" * 64,
            pdf_bytes=1024,
            taxonomy="CSRC_UNVERSIONED",
            industry_code="C31",
            industry_name="黑色金属冶炼和压延加工业",
            matched_disclosure="C31 黑色金属冶炼和压延加工业",
        )
        if found
        else None
    )
    return CninfoProspectusBridgeAudit(
        audit_id=(
            "cninfo_prospectus_bridge_audit_"
            f"{hashlib.sha256(observed_at.isoformat().encode()).hexdigest()}"
        ),
        audit_version="cninfo_prospectus_bridge_audit_v4",
        audited_at=observed_at,
        candidate=candidate,
        status=BridgeStatus.FOUND if found else BridgeStatus.MISSING,
        failure_reason=None if found else "final_prospectus_missing",
        evidence=evidence,
        trace=trace,
        research_use_authorized=False,
    )
