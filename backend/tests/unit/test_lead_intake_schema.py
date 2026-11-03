from datetime import UTC, datetime, timedelta

import pytest
from edp_api.modules.lead_intake.schemas import LeadIntakeIn
from pydantic import ValidationError


def payload() -> dict:
    return {
        "contract_version": "LeadIntakeV1",
        "intake_id": "lead_8b4f0c",
        "source_system": "PUBLIC_BFF",
        "submitted_at": datetime.now(UTC).isoformat(),
        "contact": {"name": "张三", "email_or_phone": "zhang@example.com"},
        "interest": "工业照明",
        "message": "请联系我",
        "consent": {
            "granted": True,
            "version": "privacy-v1",
            "purpose": "业务联系",
            "retention_until": (datetime.now(UTC) + timedelta(days=365)).isoformat(),
        },
        "trace_id": "trace-1",
        "idempotency_key": "website-001",
        "tenant_id": "11111111-1111-1111-1111-111111111111",
    }


def test_lead_intake_accepts_contract_shape() -> None:
    model = LeadIntakeIn.model_validate(payload())
    assert model.source_system == "PUBLIC_BFF"
    assert model.contact.name == "张三"


@pytest.mark.parametrize(
    "change",
    [
        {"source_system": "CRM"},
        {
            "consent": {
                "granted": False,
                "version": "v1",
                "purpose": "p",
                "retention_until": "2027-01-01T00:00:00Z",
            }
        },
        {"idempotency_key": "bad key"},
    ],
)
def test_lead_intake_rejects_contract_boundary(change: dict) -> None:
    data = payload()
    data.update(change)
    with pytest.raises(ValidationError):
        LeadIntakeIn.model_validate(data)


def test_lead_intake_rejects_unknown_fields() -> None:
    data = payload()
    data["internal_crm_id"] = "should-not-cross-boundary"
    with pytest.raises(ValidationError):
        LeadIntakeIn.model_validate(data)
