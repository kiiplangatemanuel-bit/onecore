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
