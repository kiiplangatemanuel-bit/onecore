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
