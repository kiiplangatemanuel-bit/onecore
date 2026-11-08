"""Reliable email delivery worker for the public Status Centre."""
import logging
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import and_, create_engine, or_, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import normalized_database_url
from app.core.models import StatusAlertDelivery

logger = logging.getLogger("onecore.status_alert_delivery")
MAX_ATTEMPTS = 8
BATCH_SIZE = 50


def _send_email(item: StatusAlertDelivery) -> None:
    if not settings.integration_email_enabled or not settings.email_host or not settings.email_from:
        raise RuntimeError("Status alert email delivery is not configured")
    message = EmailMessage()
    message["Subject"] = item.subject
    message["From"] = settings.email_from
    message["To"] = item.recipient_email
    message.set_content(item.body)
    with smtplib.SMTP(settings.email_host, settings.email_port, timeout=20) as smtp:
        if settings.email_use_starttls:
            smtp.starttls()
        if settings.email_username:
            smtp.login(settings.email_username, settings.email_password)
        smtp.send_message(message)


def run_status_alert_worker(limit: int = BATCH_SIZE) -> int:
    database_url = settings.status_alert_worker_database_url.strip()
    if not database_url:
        if settings.app_env.strip().lower() in {"production", "prod"}:
            raise RuntimeError("STATUS_ALERT_WORKER_DATABASE_URL must use the dedicated NOBYPASSRLS worker role")
        database_url = settings.database_connection_url
    engine = create_engine(normalized_database_url(database_url), pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    processed = 0
    try:
        with SessionLocal() as db:
            if db.bind.dialect.name == "postgresql":
                role = db.execute(text("SELECT current_user")).scalar_one()
                if role != "onecore_status_alert_worker":
                    raise RuntimeError("Status alert worker must connect as onecore_status_alert_worker")
            now = datetime.now(timezone.utc)
            rows = (
                db.query(StatusAlertDelivery)
                .filter(
                    or_(
                        and_(
                            StatusAlertDelivery.status == "pending",
                            StatusAlertDelivery.next_attempt_at <= now,
                        ),
                        and_(
                            StatusAlertDelivery.status == "sending",
                            StatusAlertDelivery.updated_at <= now - timedelta(minutes=10),
                        ),
                    ),
                )
                .order_by(StatusAlertDelivery.next_attempt_at, StatusAlertDelivery.id)
                .with_for_update(skip_locked=True)
                .limit(max(1, min(int(limit), 500)))
                .all()
            )
            for row in rows:
                row.status = "sending"
                row.attempts += 1
                row.updated_at = now
                delivery_id = row.id
                db.commit()
                try:
                    _send_email(row)
                except Exception as exc:
                    current = db.get(StatusAlertDelivery, delivery_id)
                    if current is not None:
                        current.status = "failed" if current.attempts >= MAX_ATTEMPTS else "pending"
                        delay_seconds = min(60 * (2 ** min(current.attempts, 6)), 3600)
                        current.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
                        current.last_error = type(exc).__name__[:120]
                        current.updated_at = datetime.now(timezone.utc)
                        db.commit()
                    logger.warning("Status alert delivery %s failed (%s)", delivery_id, type(exc).__name__)
                else:
                    current = db.get(StatusAlertDelivery, delivery_id)
                    if current is not None:
                        current.status = "delivered"
                        current.delivered_at = datetime.now(timezone.utc)
                        current.last_error = ""
                        current.updated_at = current.delivered_at
                        db.commit()
                processed += 1
        return processed
    finally:
        engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            processed = run_status_alert_worker()
            if processed:
                logger.info("processed %s Status alert deliveries", processed)
        except Exception:
            logger.exception("Status alert worker iteration failed")
        time.sleep(10)


if __name__ == "__main__":
    main()
