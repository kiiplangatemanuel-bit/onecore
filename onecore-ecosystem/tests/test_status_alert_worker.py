from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base
from app.core.models import StatusAlertDelivery
from app.workers import status_alert_delivery


def test_status_alert_worker_delivers_pending_message(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'worker.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[StatusAlertDelivery.__table__])
    with Session(engine) as db:
        db.add(StatusAlertDelivery(
            user_id=1, incident_record_id=1, recipient_email="person@example.test",
            event_key="incident-1", subject="Incident", body="Update",
            status="pending", attempts=0, next_attempt_at=datetime.now(timezone.utc),
        ))
        db.commit()
    engine.dispose()

    sent = []
    monkeypatch.setattr(settings, "status_alert_worker_database_url", url)
    monkeypatch.setattr(status_alert_delivery, "_send_email", lambda item: sent.append(item.event_key))
    assert status_alert_delivery.run_status_alert_worker() == 1
    assert sent == ["incident-1"]

    engine = create_engine(url)
    with Session(engine) as db:
        delivery = db.query(StatusAlertDelivery).one()
        assert delivery.status == "delivered"
        assert delivery.attempts == 1
        assert delivery.delivered_at is not None
    engine.dispose()


def test_status_alert_worker_retries_failures_with_bounded_backoff(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'retry.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[StatusAlertDelivery.__table__])
    with Session(engine) as db:
        db.add(StatusAlertDelivery(
            user_id=1, incident_record_id=1, recipient_email="person@example.test",
            event_key="incident-2", subject="Incident", body="Update",
            status="pending", attempts=0, next_attempt_at=datetime.now(timezone.utc),
        ))
        db.commit()
    engine.dispose()

    monkeypatch.setattr(settings, "status_alert_worker_database_url", url)
    monkeypatch.setattr(status_alert_delivery, "_send_email",
                        lambda item: (_ for _ in ()).throw(TimeoutError()))
    assert status_alert_delivery.run_status_alert_worker() == 1

    engine = create_engine(url)
    with Session(engine) as db:
        delivery = db.query(StatusAlertDelivery).one()
        assert delivery.status == "pending"
        assert delivery.attempts == 1
        assert delivery.next_attempt_at > datetime.now(timezone.utc)
        assert delivery.last_error == "TimeoutError"
    engine.dispose()
