import logging
import uuid

import pytest
from edp_api.core.errors import (
    HTTP_FOR_CODE,
    EdpError,
    ErrorCode,
    install_error_handlers,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

EXPECTED_MAPPING = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.TENANT_FORBIDDEN: 403,
    ErrorCode.TENANT_SUSPENDED: 403,
    ErrorCode.GUARD_POLICY_DENIED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INVALID_TRANSITION: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.UPSTREAM_UNAVAILABLE: 503,
    ErrorCode.INTERNAL: 500,
}


def test_error_code_count() -> None:
    assert len(ErrorCode) == 13


def test_http_for_code_full_mapping() -> None:
    assert HTTP_FOR_CODE == EXPECTED_MAPPING


@pytest.mark.parametrize(("code", "status"), sorted(EXPECTED_MAPPING.items()))
def test_http_mapping_entry_by_entry(code: ErrorCode, status: int) -> None:
    assert HTTP_FOR_CODE[code] == status
    assert EdpError(code, "msg").http_status == status


def test_edp_error_attributes() -> None:
    err = EdpError(ErrorCode.CONFLICT, "版本冲突", extra={"current_revision": 3})
    assert err.code is ErrorCode.CONFLICT
    assert err.message == "版本冲突"
    assert err.extra == {"current_revision": 3}
    assert err.http_status == 409
    assert err.args == (ErrorCode.CONFLICT, "版本冲突")


def test_edp_error_default_extra_isolated() -> None:
    a = EdpError(ErrorCode.NOT_FOUND, "a")
    b = EdpError(ErrorCode.NOT_FOUND, "b")
    a.extra["k"] = "v"
    assert b.extra == {}


@pytest.mark.parametrize(
    ("factory", "code"),
    [
        ("validation_error", ErrorCode.VALIDATION_ERROR),
        ("unauthenticated", ErrorCode.UNAUTHENTICATED),
        ("forbidden", ErrorCode.FORBIDDEN),
        ("tenant_forbidden", ErrorCode.TENANT_FORBIDDEN),
        ("tenant_suspended", ErrorCode.TENANT_SUSPENDED),
        ("guard_policy_denied", ErrorCode.GUARD_POLICY_DENIED),
        ("not_found", ErrorCode.NOT_FOUND),
        ("method_not_allowed", ErrorCode.METHOD_NOT_ALLOWED),
        ("conflict", ErrorCode.CONFLICT),
        ("invalid_transition", ErrorCode.INVALID_TRANSITION),
        ("rate_limited", ErrorCode.RATE_LIMITED),
        ("upstream_unavailable", ErrorCode.UPSTREAM_UNAVAILABLE),
        ("internal", ErrorCode.INTERNAL),
    ],
)
def test_factory_constructors(factory: str, code: ErrorCode) -> None:
    err: EdpError = getattr(EdpError, factory)("boom", extra={"k": 1})
    assert err.code is code
    assert err.message == "boom"
    assert err.extra == {"k": 1}
    assert err.http_status == EXPECTED_MAPPING[code]


def _make_client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom-edp")
    async def boom_edp() -> dict[str, str]:
        raise EdpError.tenant_suspended("租户已暂停")

    @app.get("/boom-edp-extra")
    async def boom_edp_extra() -> dict[str, str]:
        raise EdpError.conflict("版本冲突", extra={"current_revision": 2})

    @app.get("/boom-raw")
    async def boom_raw() -> dict[str, str]:
        raise RuntimeError("kaboom")

    @app.get("/need-int")
    async def need_int(q: int) -> dict[str, int]:
        return {"q": q}

    return TestClient(app)


def test_edp_error_handler_structure() -> None:
    resp = _make_client().get("/boom-edp")
    assert resp.status_code == 403
    body = resp.json()["error"]
    assert body["code"] == "TENANT_SUSPENDED"
    assert body["message"] == "租户已暂停"
    uuid.UUID(body["request_id"])


def test_edp_error_handler_merges_extra() -> None:
    resp = _make_client().get("/boom-edp-extra")
    assert resp.status_code == 409
    body = resp.json()["error"]
    assert body["code"] == "CONFLICT"
    assert body["current_revision"] == 2
    assert set(body) == {"code", "message", "request_id", "current_revision"}


def test_validation_error_handler() -> None:
    resp = _make_client().get("/need-int", params={"q": "abc"})
    assert resp.status_code == 400
    body = resp.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert "q" in body["message"]
    uuid.UUID(body["request_id"])


def test_unhandled_exception_handler(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom-raw")
    async def boom_raw() -> dict[str, str]:
        raise RuntimeError("kaboom")

    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        resp = client.get("/boom-raw")
    assert resp.status_code == 500
    body = resp.json()["error"]
    assert body["code"] == "INTERNAL"
    uuid.UUID(body["request_id"])
    assert any(r.exc_info for r in caplog.records)
