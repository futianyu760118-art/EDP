from edp_api.core.contextvars import RequestIDMiddleware, current_request_id
from edp_api.core.errors import EdpError, install_error_handlers
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    install_error_handlers(app)

    @app.get("/echo-request-id")
    async def echo_request_id() -> dict[str, str | None]:
        return {"request_id": current_request_id.get()}

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise EdpError.forbidden("denied")

    return app


def test_middleware_generates_request_id() -> None:
    resp = TestClient(_make_app()).get("/echo-request-id")
    assert resp.status_code == 200
    rid = resp.json()["request_id"]
    assert rid is not None
    assert rid == resp.headers["X-Request-ID"]


def test_middleware_passthrough_existing_header() -> None:
    resp = TestClient(_make_app()).get(
        "/echo-request-id", headers={"X-Request-ID": "client-rid-42"}
    )
    assert resp.json()["request_id"] == "client-rid-42"
    assert resp.headers["X-Request-ID"] == "client-rid-42"


def test_error_response_uses_middleware_request_id() -> None:
    resp = TestClient(_make_app()).get("/boom", headers={"X-Request-ID": "rid-sync"})
    assert resp.status_code == 403
    body = resp.json()["error"]
    assert body["request_id"] == "rid-sync"
    assert resp.headers["X-Request-ID"] == "rid-sync"
