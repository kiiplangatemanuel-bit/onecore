"""Rate limits for unauthenticated public workflows.

The process-local limiter is a defensive baseline. Production must also apply
shared limits at the trusted ingress/WAF so multiple API workers cannot multiply
the quota. Never trust arbitrary X-Forwarded-For values here.
"""
from fastapi import HTTPException, Request


def enforce_public_write_limit(request: Request, scope: str) -> None:
    limiter = getattr(request.app.state, "public_write_rate_limiter", None)
    if limiter is None:
        # Fail closed if the application was assembled without its limiter.
        raise HTTPException(503, "Public request protection is unavailable")
    client_host = request.client.host if request.client else "unknown"
    key = f"{scope}:{client_host}"
    if not limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait before trying again.",
            headers={"Retry-After": str(limiter.window_seconds)},
        )
