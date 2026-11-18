import os

import pytest
from edp_api.core.config import Settings, get_settings


def _clear_edp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("EDP_"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_edp_env(monkeypatch)
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://edp_migrator:edp_dev@localhost:15432/edp"
    assert s.jwt_secret == "dev-secret"
    assert s.jwt_alg == "HS256"
    assert s.access_ttl_seconds == 7200
    assert s.refresh_ttl_seconds == 604800
    assert s.admin_initial_password == "Admin@123!"
    assert s.seed_password == "Admin@123!"
    assert s.dev_api_key == "edp-dev-agent-hub-key"
    assert s.idempotency_ttl_seconds == 86400
    assert s.outbox_max_retries == 8
    assert s.outbox_backoff_base_seconds == 5.0
    assert s.fac_base_url == ""
    assert s.fac_bearer_token == ""
    assert s.fac_timeout_seconds == 10.0
    assert s.plm_base_url == ""
    assert s.plm_bearer_token == ""
    assert s.plm_tenant_id == ""
    assert s.plm_timeout_seconds == 10.0
    assert s.plm_poll_interval_seconds == 5.0
    assert s.plm_batch_size == 50
    assert s.app_env == "dev"


def test_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_edp_env(monkeypatch)
    monkeypatch.setenv("EDP_DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/other")
    monkeypatch.setenv("EDP_JWT_SECRET", "s3cret")
    monkeypatch.setenv("EDP_JWT_ALG", "HS512")
    monkeypatch.setenv("EDP_ACCESS_TTL_SECONDS", "3600")
    monkeypatch.setenv("EDP_REFRESH_TTL_SECONDS", "1")
    monkeypatch.setenv("EDP_ADMIN_INITIAL_PASSWORD", "P@ss1")
    monkeypatch.setenv("EDP_SEED_PASSWORD", "P@ss2")
    monkeypatch.setenv("EDP_DEV_API_KEY", "key-x")
    monkeypatch.setenv("EDP_IDEMPOTENCY_TTL_SECONDS", "60")
    monkeypatch.setenv("EDP_OUTBOX_MAX_RETRIES", "3")
    monkeypatch.setenv("EDP_OUTBOX_BACKOFF_BASE_SECONDS", "2.5")
    monkeypatch.setenv("EDP_FAC_BASE_URL", "http://fac:8000")
    monkeypatch.setenv("EDP_FAC_BEARER_TOKEN", "fac-secret")
    monkeypatch.setenv("EDP_FAC_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setenv("EDP_PLM_BASE_URL", "http://plm:8080")
    monkeypatch.setenv("EDP_PLM_BEARER_TOKEN", "plm-jwt")
    monkeypatch.setenv(
        "EDP_PLM_TENANT_ID",
        "11111111-1111-1111-1111-111111111111",
    )
    monkeypatch.setenv("EDP_PLM_TIMEOUT_SECONDS", "4.5")
    monkeypatch.setenv("EDP_PLM_POLL_INTERVAL_SECONDS", "6.0")
    monkeypatch.setenv("EDP_PLM_BATCH_SIZE", "25")
    monkeypatch.setenv("EDP_APP_ENV", "prod")

    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://u:p@db:5432/other"
    assert s.jwt_secret == "s3cret"
    assert s.jwt_alg == "HS512"
    assert s.access_ttl_seconds == 3600
    assert s.refresh_ttl_seconds == 1
    assert s.admin_initial_password == "P@ss1"
    assert s.seed_password == "P@ss2"
    assert s.dev_api_key == "key-x"
    assert s.idempotency_ttl_seconds == 60
    assert s.outbox_max_retries == 3
    assert s.outbox_backoff_base_seconds == 2.5
    assert s.fac_base_url == "http://fac:8000"
    assert s.fac_bearer_token == "fac-secret"
    assert s.fac_timeout_seconds == 3.5
    assert s.plm_base_url == "http://plm:8080"
    assert s.plm_bearer_token == "plm-jwt"
    assert s.plm_tenant_id == "11111111-1111-1111-1111-111111111111"
    assert s.plm_timeout_seconds == 4.5
    assert s.plm_poll_interval_seconds == 6.0
    assert s.plm_batch_size == 25
    assert s.app_env == "prod"


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_edp_env(monkeypatch)
    first = get_settings()
    assert get_settings() is first

    monkeypatch.setenv("EDP_JWT_SECRET", "changed")
    assert get_settings() is first
    assert get_settings().jwt_secret == "dev-secret"

    get_settings.cache_clear()
    second = get_settings()
    assert second is not first
    assert second.jwt_secret == "changed"
