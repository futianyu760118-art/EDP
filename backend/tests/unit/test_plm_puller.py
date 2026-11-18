from datetime import UTC, datetime

import pytest
from edp_api.core.config import Settings
from edp_worker import plm_puller


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        plm_base_url="http://plm.local",
        plm_bearer_token="jwt-token",
        plm_tenant_id="11111111-1111-1111-1111-111111111111",
        plm_batch_size=50,
    )


def test_parse_pending_row_builds_full_m04_envelope() -> None:
    event = plm_puller.parse_pending_row(
        {
            "event_id": "PLM-EVT-13",
            "event_type": "BOMReleased",
            "object_type": "BOM",
            "object_id": "BOM-WL6000",
            "occurred_at": "2026-11-18T08:00:00Z",
            "source_system": "M04",
            "correlation_id": "BOM:WL6000",
            "version": 13,
            "evidence_refs": '["EV-BOM-R13"]',
            "payload_json": '{"rootPartNo":"WL6000","versionNo":"R13"}',
        }
    )
    assert event.event_id == "PLM-EVT-13"
    assert event.object_id == "BOM-WL6000"
    assert event.occurred_at == datetime(2026, 11, 18, 8, tzinfo=UTC)
    assert event.evidence_refs == ["EV-BOM-R13"]
    assert event.payload["rootPartNo"] == "WL6000"


def test_object_type_is_registry_safe() -> None:
    assert plm_puller._object_type("ProductConfiguration") == "PRODUCT_CONFIGURATION"
    assert plm_puller._object_type("BOM") == "BOM"


async def test_fetch_pending_uses_plm_result_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_http(method, url, *, token, timeout):
        assert method == "GET"
        assert "limit=50" in url
        assert token == "jwt-token"
        return {
            "code": 200,
            "data": [
                {
                    "event_id": "E1",
                    "event_type": "BOMReleased",
                    "object_type": "BOM",
                    "object_id": "B1",
                    "occurred_at": "2026-11-18T08:00:00+00:00",
                    "payload_json": "{}",
                }
            ],
        }

    monkeypatch.setattr(plm_puller, "_http_json", fake_http)
    result = await plm_puller.fetch_pending(_settings())
    assert len(result) == 1
    assert result[0].event_id == "E1"


async def test_ack_posts_only_after_explicit_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_http(method, url, *, token, timeout):
        calls.append((method, url, token))
        return {"code": 200, "data": {"updated": 1}}

    monkeypatch.setattr(plm_puller, "_http_json", fake_http)
    await plm_puller.ack_event(_settings(), "E1")
    assert calls == [
        (
            "POST",
            "http://plm.local/v1/integration/events/E1/ack",
            "jwt-token",
        )
    ]
