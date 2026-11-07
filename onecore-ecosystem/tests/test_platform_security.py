import pytest
from app.core.platform_security import LoginRateLimiter


def test_login_limiter_allows_configured_attempts_then_blocks():
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)
    assert limiter.allow("203.0.113.1")
    assert limiter.allow("203.0.113.1")
    assert limiter.allow("203.0.113.1")
    assert not limiter.allow("203.0.113.1")


def test_login_limiter_isolates_clients_and_resets_successful_login():
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=60)
    assert limiter.allow("client-a")
    assert not limiter.allow("client-a")
    assert limiter.allow("client-b")
    limiter.reset("client-a")
    assert limiter.allow("client-a")


def test_login_limiter_rejects_invalid_configuration():
    import pytest
    with pytest.raises(ValueError):
        LoginRateLimiter(max_attempts=0)

from fastapi.testclient import TestClient
from app.main import app


def test_security_headers_and_request_id_are_present():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]
    assert response.headers["content-security-policy"]


def test_login_route_enforces_rate_limit():
    original = app.state.login_rate_limiter
    app.state.login_rate_limiter = LoginRateLimiter(max_attempts=2, window_seconds=60)
    try:
        with TestClient(app) as client:
            assert client.post("/api/v1/auth/login", data={}).status_code == 422
            assert client.post("/api/v1/auth/login", data={}).status_code == 422
            blocked = client.post("/api/v1/auth/login", data={})
            assert blocked.status_code == 429
            assert blocked.headers["retry-after"] == "60"
    finally:
        app.state.login_rate_limiter = original


def test_readiness_endpoint_checks_database():
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"

def test_production_settings_require_secure_values():
    from pydantic import ValidationError
    from app.core.config import Settings

    safe = dict(
        app_env="production",
        debug=False,
        secret_key="s" * 48,
        database_url="postgresql+psycopg://user:pass@db.example/onecore",
        cors_origins="https://app.example.com",
        trusted_hosts="api.example.com",
        force_https=True,
    )
    Settings(_env_file=None, **safe)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**safe, "secret_key": "unsafe-development-key-change-me"})
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**safe, "cors_origins": "*"})
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**safe, "database_url": "sqlite:///./onecore.db"})


def test_bootstrap_credentials_must_be_explicit_and_strong():
    from pydantic import ValidationError
    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, bootstrap_admin_email="admin@example.com")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, bootstrap_admin_email="admin@example.com",
                 bootstrap_admin_password="short")
