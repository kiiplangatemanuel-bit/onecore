"""Dedicated least-privilege worker for encrypted identity email delivery."""
import logging
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import and_, create_engine, or_, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import normalized_database_url
from app.core.identity_models import IdentityEmailDelivery
from app.services.identity_email import decrypt_identity_email_payload

logger = logging.getLogger("onecore.identity_email_delivery")
MAX_ATTEMPTS = 8
BATCH_SIZE = 50
STALE_SENDING_AFTER = timedelta(minutes=10)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _send_email(payload: dict[str, str], delivery_id: int) -> None:
    if not (
        settings.integration_email_enabled
        and settings.email_host.strip()
        and settings.email_from.strip()
    ):
        raise RuntimeError("Identity email SMTP delivery is not configured")
    if settings.app_env.strip().lower() in {"production", "prod"} and not settings.email_use_starttls:
        raise RuntimeError("Production identity email delivery requires STARTTLS")
    message = EmailMessage()
    message["Subject"] = payload["subject"]
    message["From"] = settings.email_from
    message["To"] = payload["recipient_email"]
    message["X-OneCore-Delivery-ID"] = str(delivery_id)
    message.set_content(payload["body"])
    with smtplib.SMTP(settings.email_host, settings.email_port, timeout=20) as smtp:
        if settings.email_use_starttls:
            smtp.starttls()
        if settings.email_username:
            smtp.login(settings.email_username, settings.email_password)
        smtp.send_message(message)


def _worker_engine():
    database_url = settings.identity_email_worker_database_url.strip()
    production = settings.app_env.strip().lower() in {"production", "prod"}
    if production and not database_url:
        raise RuntimeError(
            "IDENTITY_EMAIL_WORKER_DATABASE_URL must use the dedicated NOBYPASSRLS worker role"
        )
    if production and __import__("os").getenv("ONECORE_DATABASE_RUNTIME_ROLE", "").strip() != "onecore_identity_email_worker":
        raise RuntimeError(
            "ONECORE_DATABASE_RUNTIME_ROLE must be onecore_identity_email_worker for this worker"
        )
    if not database_url:
        database_url = settings.database_connection_url
    url = normalized_database_url(database_url)
    connect_args = {}
    if url.get_backend_name() == "postgresql":
        connect_args["application_name"] = "onecore-identity-email-worker"
        if (url.host or "").lower().endswith(".pooler.supabase.com") and url.port == 6543:
            connect_args["prepare_threshold"] = None
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


def _assert_worker_role(db) -> None:
    if db.bind.dialect.name != "postgresql":
        return
    role = db.execute(text("SELECT current_user")).scalar_one()
    if role != "onecore_identity_email_worker":
        raise RuntimeError("Identity email worker must assume onecore_identity_email_worker")
    flags = db.execute(text("""
        SELECT rolsuper AS is_superuser, rolbypassrls AS bypasses_rls
        FROM pg_roles WHERE rolname = current_user
    """)).mappings().one_or_none()
    if not flags or flags["is_superuser"] or flags["bypasses_rls"]:
        raise RuntimeError("Identity email worker role must be a non-superuser NOBYPASSRLS role")


def run_identity_email_worker(limit: int = BATCH_SIZE) -> int:
    engine = _worker_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    processed = 0
    try:
        with SessionLocal() as db:
            _assert_worker_role(db)
            now = datetime.now(timezone.utc)
            rows = (
                db.query(IdentityEmailDelivery)
                .filter(
                    or_(
                        and_(
                            IdentityEmailDelivery.status == "pending",
                            IdentityEmailDelivery.next_attempt_at <= now,
                        ),
                        and_(
                            IdentityEmailDelivery.status == "sending",
                            IdentityEmailDelivery.updated_at <= now - STALE_SENDING_AFTER,
                        ),
                    )
                )
                .order_by(IdentityEmailDelivery.next_attempt_at, IdentityEmailDelivery.id)
                .with_for_update(skip_locked=True)
                .limit(max(1, min(int(limit), 500)))
                .all()
            )
            delivery_ids = []
            for row in rows:
                row.status = "sending"
                row.attempts += 1
                row.updated_at = now
                delivery_ids.append(row.id)
            db.commit()

        for delivery_id in delivery_ids:
            with SessionLocal() as db:
                row = (
                    db.query(IdentityEmailDelivery)
                    .filter(IdentityEmailDelivery.id == delivery_id)
                    .with_for_update()
                    .one_or_none()
                )
                if row is None or row.status != "sending":
                    continue
                now = datetime.now(timezone.utc)
                if _aware(row.expires_at) <= now:
                    row.status = "cancelled"
                    row.last_error = "expired"
                    row.updated_at = now
                    db.commit()
                    processed += 1
                    continue
                try:
                    payload = decrypt_identity_email_payload(row)
                    _send_email(payload, delivery_id)
                except Exception as exc:
                    row.status = "failed" if row.attempts >= MAX_ATTEMPTS else "pending"
                    delay_seconds = min(60 * (2 ** min(row.attempts, 6)), 3600)
                    row.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
                    row.last_error = type(exc).__name__[:120]
                    row.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.warning(
                        "Identity email delivery %s failed (%s)",
                        delivery_id,
                        type(exc).__name__,
                    )
                else:
                    delivered_at = datetime.now(timezone.utc)
                    row.status = "delivered"
                    row.delivered_at = delivered_at
                    row.last_error = ""
                    row.updated_at = delivered_at
                    db.commit()
                processed += 1
        return processed
    finally:
        engine.dispose()


def _write_heartbeat() -> None:
    try:
        Path("/tmp/identity-email-worker-heartbeat").touch()
    except OSError:
        logger.warning("Could not write identity email worker heartbeat")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            processed = run_identity_email_worker()
            if processed:
                logger.info("Processed %s identity email deliveries", processed)
        except Exception:
            logger.exception("Identity email worker iteration failed")
        _write_heartbeat()
        time.sleep(10)


if __name__ == "__main__":
    import logging
    main()
