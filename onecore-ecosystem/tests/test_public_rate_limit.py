from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from app.core.platform_security import LoginRateLimiter
from app.core.public_rate_limit import enforce_public_write_limit


def test_public_workflow_rate_limit_blocks_excess_requests():
    app = FastAPI()
    app.state.public_write_rate_limiter = LoginRateLimiter(max_attempts=1, window_seconds=300)
    request = Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/auth/register-organization",
        "raw_path": b"/api/v1/auth/register-organization",
        "query_string": b"",
        "headers": [],
        "client": ("203.0.113.10", 12345),
        "server": ("onecore.example", 443),
        "app": app,
    })

    enforce_public_write_limit(request, "organization-registration")
    try:
        enforce_public_write_limit(request, "organization-registration")
    except HTTPException as exc:
        assert exc.status_code == 429
        assert exc.headers["Retry-After"] == "300"
    else:
        raise AssertionError("Excess public requests must be rejected")
