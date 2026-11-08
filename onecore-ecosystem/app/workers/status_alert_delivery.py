"""Deliver queued Status incident alerts using a dedicated RLS-constrained DB role."""
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import logging
import smtplib

from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.models import StatusAlertDelivery

logger = logging.getLogger("onecore.status_alert_worker")
MAX_ATTEMPTS = 8


def _send_email(delivery: StatusAlertDelivery) -> None:
    if not (settings.integration_email_enabled and settings.email_host and settings.email_from):
        raise RuntimeError("SMTP email integration is not configured")
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = delivery.recipient_email
    message["Subject"] = delivery.subject
    message["X-OneCore-Alert-ID"] = delivery.event_key
    message.set_content(delivery.body)
    with smtplib.SMTP(settings.email_host, settings.email_port, timeout=20) as smtp:
        if settings.email_use_starttls:
            smtp.starttls()
        if settings.email_username:
            smtp.login(settings.email_username, settings.email_password)
        smtp.send_message(message)


def run_status_alert_worker(batch_size: int = 25) -> int:
    if not settings.status_alert_worker_database_url:
        raise RuntimeError("STATUS_ALERT_WORKER_DATABASE_URL is required")
    engine = create_engine(settings.status_alert_worker_database_url, pool_pre_ping=True)
    processed = 0
    try:
        with Session(engine) as db:
            now = datetime.now(timezone.utc)
            rows = db.execute(
                select(StatusAlertDelivery)
                .where(
                    or_(StatusAlertDelivery.status == "pending",
                        StatusAlertDelivery.status == "processing"),
                    StatusAlertDelivery.next_attempt_at <= now,
                )
                .order_by(StatusAlertDelivery.next_attempt_at, StatusAlertDelivery.id)
                .limit(max(1, min(batch_size, 100)))
                .with_for_update(skip_locked=True)
            ).scalars().all()
            for delivery in rows:
                delivery.status = "processing"
                delivery.attempts += 1
                delivery.next_attempt_at = now + timedelta(minutes=5)
            db.commit()
            for delivery in rows:
                try:
                    _send_email(delivery)
                    delivery.status = "delivered"
                    delivery.delivered_at = datetime.now(timezone.utc)
                    delivery.last_error = ""
                except Exception as exc:
                    delivery.last_error = type(exc).__name__[:500]
                    if delivery.attempts >= MAX_ATTEMPTS:
                        delivery.status = "failed"
                    else:
                        delivery.status = "pending"
                        delay = min(3600, 30 * (2 ** (delivery.attempts - 1)))
                        delivery.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                    logger.warning("Status alert delivery %s failed (%s)", delivery.id, type(exc).__name__)
                processed += 1
            db.commit()
    finally:
        engine.dispose()
    return processed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = run_status_alert_worker()
    logger.info("processed %s Status alert deliveries", count)
