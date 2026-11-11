from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base
from app.core.identity_models import IdentityEmailDelivery
from app.services.identity_email import (
    decrypt_identity_email_payload,
    queue_password_reset_email,
    queue_verification_email,
)
from app.workers import identity_email_delivery as worker


def _engine(path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine, tables=[IdentityEmailDelivery.__table__])
    return engine


def _configure(monkeypatch):
    monkeypatch.setattr(settings, "identity_email_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "integration_email_enabled", True)
    monkeypatch.setattr(settings, "email_host", "smtp.example.test")
    monkeypatch.setattr(settings, "email_from", "no-reply@example.test")
    monkeypatch.setattr(settings, "email_use_starttls", True)
    monkeypatch.setattr(settings, "public_site_url", "https://onecore.example.test")
    monkeypatch.setattr(settings, "app_env", "development")


def _queue(db, expires_at=None):
    return queue_verification_email(
        db,
        user_id=7,
        email="member@example.test",
        full_name="Member",
        token="raw-one-time-token",
        token_hash="a" * 64,
        expires_at=expires_at or datetime.now(timezone.utc) + timedelta(hours=1),
    )


def test_identity_email_payload_is_encrypted_and_round_trips(monkeypatch, tmp_path):
    _configure(monkeypatch)
    engine = _engine(tmp_path / "encrypted.db")
    with Session(engine) as db:
        row = _queue(db)
        db.commit()
        assert "member@example.test" not in row.payload_ciphertext
        assert "raw-one-time-token" not in row.payload_ciphertext
        payload = decrypt_identity_email_payload(row)
        assert payload["recipient_email"] == "member@example.test"
        assert "raw-one-time-token" in payload["body"]
        assert row.status == "pending"
        assert row.attempts == 0
    engine.dispose()


def test_identity_email_queue_fails_closed_without_valid_encryption_key(monkeypatch, tmp_path):
    _configure(monkeypatch)
    engine = _engine(tmp_path / "no-key.db")
    with Session(engine) as db:
        monkeypatch.setattr(settings, "identity_email_encryption_key", "")
        with pytest.raises(RuntimeError, match="IDENTITY_EMAIL_ENCRYPTION_KEY"):
            _queue(db)
        monkeypatch.setattr(settings, "identity_email_encryption_key", "not-a-fernet-key")
        with pytest.raises(RuntimeError, match="IDENTITY_EMAIL_ENCRYPTION_KEY"):
            _queue(db)
        assert db.query(IdentityEmailDelivery).count() == 0
    engine.dispose()


def test_identity_email_worker_delivers_and_marks_outbox_row(monkeypatch, tmp_path):
    _configure(monkeypatch)
    database = tmp_path / "worker-success.db"
    engine = _engine(database)
    with Session(engine) as db:
        _queue(db)
        db.commit()
    engine.dispose()

    sent = []
    monkeypatch.setattr(settings, "identity_email_worker_database_url", f"sqlite:///{database}")
    monkeypatch.setattr(worker, "_send_email", lambda payload, delivery_id: sent.append((payload, delivery_id)))
    assert worker.run_identity_email_worker() == 1
    assert len(sent) == 1
    assert sent[0][0]["recipient_email"] == "member@example.test"

    engine = _engine(database)
    with Session(engine) as db:
        row = db.query(IdentityEmailDelivery).one()
        assert row.status == "delivered"
        assert row.attempts == 1
        assert row.delivered_at is not None
        assert row.last_error == ""
    engine.dispose()


def test_identity_email_worker_retries_transient_smtp_failures(monkeypatch, tmp_path):
    _configure(monkeypatch)
    database = tmp_path / "worker-retry.db"
    engine = _engine(database)
    with Session(engine) as db:
        _queue(db)
        db.commit()
    engine.dispose()

    monkeypatch.setattr(settings, "identity_email_worker_database_url", f"sqlite:///{database}")
    monkeypatch.setattr(
        worker,
        "_send_email",
        lambda *_args: (_ for _ in ()).throw(TimeoutError()),
    )
    assert worker.run_identity_email_worker() == 1

    engine = _engine(database)
    with Session(engine) as db:
        row = db.query(IdentityEmailDelivery).one()
        assert row.status == "pending"
        assert row.attempts == 1
        assert row.next_attempt_at > datetime.now(timezone.utc)
        assert row.last_error == "TimeoutError"
    engine.dispose()


def test_identity_email_worker_cancels_expired_messages_without_sending(monkeypatch, tmp_path):
    _configure(monkeypatch)
    database = tmp_path / "worker-expired.db"
    engine = _engine(database)
    with Session(engine) as db:
        row = _queue(db)
        # Simulate an outbox row queued before the token expired.
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=2)
        db.commit()
    engine.dispose()

    monkeypatch.setattr(settings, "identity_email_worker_database_url", f"sqlite:///{database}")
    sent = []
    monkeypatch.setattr(worker, "_send_email", lambda *_args: sent.append(True))
    assert worker.run_identity_email_worker() == 1
    assert sent == []

    engine = _engine(database)
    with Session(engine) as db:
        row = db.query(IdentityEmailDelivery).one()
        assert row.status == "cancelled"
        assert row.last_error == "expired"
    engine.dispose()


def test_production_identity_email_worker_requires_dedicated_role_url(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "identity_email_worker_database_url", "")
    monkeypatch.setattr(__import__("os"), "getenv", lambda *_args: "onecore_identity_email_worker")
    with pytest.raises(RuntimeError, match="IDENTITY_EMAIL_WORKER_DATABASE_URL"):
        worker._worker_engine()
