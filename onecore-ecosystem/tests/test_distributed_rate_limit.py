"""Shared rate-limit behavior and PostgreSQL service-context RLS tests."""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base, engine as application_engine
from app.core.platform_security_models import PlatformRateLimitBucket
from app.core.platform_security import DatabaseRateLimiter

CI_RUNTIME_ROLE = os.getenv("ONECORE_CI_RLS_ROLE", "").strip()
pytestmark_postgres = pytest.mark.skipif(
    application_engine.dialect.name != "postgresql" or not CI_RUNTIME_ROLE,
    reason="Requires PostgreSQL and the CI-only NOBYPASSRLS runtime role",
)


def _sqlite_store(path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine, tables=[PlatformRateLimitBucket.__table__])
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_database_rate_limiter_shares_a_quota_across_instances(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secret_key", "test-rate-limit-secret-" + "x" * 40)
    engine, sessions = _sqlite_store(tmp_path / "shared-rate-limit.db")
    first = DatabaseRateLimiter(2, 60, scope="login", session_factory=sessions)
    second = DatabaseRateLimiter(2, 60, scope="login", session_factory=sessions)

    assert first.allow("203.0.113.10")
    assert second.allow("203.0.113.10")
    assert not first.allow("203.0.113.10")
    assert second.allow("203.0.113.11")

    with sessions() as db:
        rows = db.query(PlatformRateLimitBucket).all()
        assert len(rows) == 2
        assert all("203.0.113." not in row.key_hash for row in rows)
        assert all(row.request_count >= 1 for row in rows)
    engine.dispose()


def test_database_rate_limiter_resets_an_expired_fixed_window(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secret_key", "test-rate-limit-secret-" + "y" * 40)
    engine, sessions = _sqlite_store(tmp_path / "window-reset.db")
    now = [datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)]
    limiter = DatabaseRateLimiter(
        1, 30, scope="public-write", session_factory=sessions, now_fn=lambda: now[0]
    )

    assert limiter.allow("198.51.100.5")
    assert not limiter.allow("198.51.100.5")
    now[0] += timedelta(seconds=31)
    assert limiter.allow("198.51.100.5")

    with sessions() as db:
        row = db.query(PlatformRateLimitBucket).one()
        assert row.request_count == 1
        assert row.window_started_at == now[0]
    engine.dispose()


def test_database_rate_limiter_scopes_are_independent(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secret_key", "test-rate-limit-secret-" + "z" * 40)
    engine, sessions = _sqlite_store(tmp_path / "separate-scopes.db")
    login = DatabaseRateLimiter(1, 60, scope="login", session_factory=sessions)
    public = DatabaseRateLimiter(1, 60, scope="public-write", session_factory=sessions)

    assert login.allow("203.0.113.20")
    assert public.allow("203.0.113.20")
    assert not login.allow("203.0.113.20")
    assert not public.allow("203.0.113.20")

    with sessions() as db:
        assert db.query(PlatformRateLimitBucket).count() == 2
    engine.dispose()


@pytestmark_postgres
def test_rate_limit_table_requires_the_transaction_local_service_context():
    key_hash = uuid.uuid4().hex + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    with application_engine.begin() as connection:
        connection.execute(text(f'SET LOCAL ROLE "{CI_RUNTIME_ROLE}"'))
        assert connection.execute(
            text("SELECT count(*) FROM platform_rate_limit_buckets WHERE key_hash = :key"),
            {"key": key_hash},
        ).scalar_one() == 0

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("""
                        INSERT INTO platform_rate_limit_buckets
                            (key_hash, scope, window_started_at, request_count, expires_at, updated_at)
                        VALUES (:key, 'login', :started, 1, :expires, :updated)
                    """),
                    {"key": key_hash, "started": now, "expires": now + timedelta(minutes=1), "updated": now},
                )

        connection.execute(
            text("SELECT set_config('app.platform_rate_limit_service', 'enabled', true)")
        )
        connection.execute(
            text("""
                INSERT INTO platform_rate_limit_buckets
                    (key_hash, scope, window_started_at, request_count, expires_at, updated_at)
                VALUES (:key, 'login', :started, 1, :expires, :updated)
            """),
            {"key": key_hash, "started": now, "expires": now + timedelta(minutes=1), "updated": now},
        )
        assert connection.execute(
            text("SELECT count(*) FROM platform_rate_limit_buckets WHERE key_hash = :key"),
            {"key": key_hash},
        ).scalar_one() == 1
        connection.execute(
            text("SELECT set_config('app.platform_rate_limit_service', 'disabled', true)")
        )
        assert connection.execute(
            text("SELECT count(*) FROM platform_rate_limit_buckets WHERE key_hash = :key"),
            {"key": key_hash},
        ).scalar_one() == 0
        connection.execute(
            text("SELECT set_config('app.platform_rate_limit_service', 'enabled', true)")
        )
        connection.execute(
            text("DELETE FROM platform_rate_limit_buckets WHERE key_hash = :key"),
            {"key": key_hash},
        )
