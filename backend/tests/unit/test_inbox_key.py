from uuid import UUID

import pytest
from edp_api.core.inbox import build_inbox_key

TENANT = UUID("11111111-1111-1111-1111-111111111111")


def test_inbox_key_is_stable_and_consumer_scoped() -> None:
    key = build_inbox_key(
        tenant_id=TENANT,
        consumer=" ebms-adapter ",
        source_system="M09_FAC",
        object_type="FinanceResult",
        object_id="FR-001",
        revision=3,
        event_type="fac.finance_result.verified",
    )

    assert key.consumer == "ebms-adapter"
    assert key.revision == 3
    assert key.as_tuple() == (
        str(TENANT),
        "ebms-adapter",
        "M09_FAC",
        "FinanceResult",
        "FR-001",
        3,
        "fac.finance_result.verified",
    )
    assert key.canonical() == (
        '["11111111-1111-1111-1111-111111111111","ebms-adapter",'
        '"M09_FAC","FinanceResult","FR-001",3,"fac.finance_result.verified"]'
    )
    assert key != build_inbox_key(
        tenant_id=TENANT,
        consumer="crm-adapter",
        source_system="M09_FAC",
        object_type="FinanceResult",
        object_id="FR-001",
        revision=3,
        event_type="fac.finance_result.verified",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("consumer", ""),
        ("source_system", " "),
        ("object_type", ""),
        ("object_id", ""),
        ("event_type", ""),
    ],
)
def test_inbox_key_rejects_blank_identity_parts(field: str, value: str) -> None:
    params = {
        "tenant_id": TENANT,
        "consumer": "consumer",
        "source_system": "source",
        "object_type": "Object",
        "object_id": "object-1",
        "revision": 1,
        "event_type": "event.created",
    }
    params[field] = value

    with pytest.raises(ValueError, match=field):
        build_inbox_key(**params)


def test_inbox_key_rejects_non_positive_revision() -> None:
    with pytest.raises(ValueError, match="revision"):
        build_inbox_key(
            tenant_id=TENANT,
            consumer="consumer",
            source_system="source",
            object_type="Object",
            object_id="object-1",
            revision=0,
            event_type="event.created",
        )
