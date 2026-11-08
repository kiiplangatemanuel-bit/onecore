import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from app.core.models import Organization, CRMWorkerHeartbeat
from app.core.database import SessionLocal
from app.services.crm_scheduler import run_due_schedules
from app.core.security import set_verified_organization_context

logging.basicConfig(level=logging.INFO)
logger=logging.getLogger("onecore.crm_scheduler")


def main():
    while True:
        db = SessionLocal()
        try:
            # Iterate tenants explicitly. The database RLS context is rebound for
            # every transaction, including commits performed by run_due_schedules.
            organization_ids = [
                organization_id
                for (organization_id,) in db.query(Organization.id).filter(
                    Organization.is_active.is_(True)
                ).order_by(Organization.id).all()
            ]
            total_processed = 0
            for organization_id in organization_ids:
                try:
                    set_verified_organization_context(db, organization_id)
                    processed = run_due_schedules(
                        db, organization_id=organization_id, limit=10
                    )
                    total_processed += processed
                    now = datetime.now(timezone.utc)
                    heartbeat = db.query(CRMWorkerHeartbeat).filter_by(
                        organization_id=organization_id, worker_name="crm-scheduler"
                    ).first()
                    if heartbeat is None:
                        heartbeat = CRMWorkerHeartbeat(
                            organization_id=organization_id, worker_name="crm-scheduler"
                        )
                        db.add(heartbeat)
                    heartbeat.last_seen_at = now
                    heartbeat.last_processed = processed
                    heartbeat.last_error = ""
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    logger.exception(
                        "CRM scheduler failed for organization %s", organization_id
                    )
                    set_verified_organization_context(db, organization_id)
                    heartbeat = db.query(CRMWorkerHeartbeat).filter_by(
                        organization_id=organization_id, worker_name="crm-scheduler"
                    ).first()
                    if heartbeat is None:
                        heartbeat = CRMWorkerHeartbeat(
                            organization_id=organization_id, worker_name="crm-scheduler"
                        )
                        db.add(heartbeat)
                    heartbeat.last_seen_at = datetime.now(timezone.utc)
                    heartbeat.last_processed = 0
                    heartbeat.last_error = type(exc).__name__
                    db.commit()
            if total_processed:
                logger.info("processed %s due campaign schedules", total_processed)
        except Exception:
            db.rollback()
            logger.exception("CRM scheduler iteration failed before tenant processing")
        finally:
            db.close()
        Path("/tmp/crm-scheduler-heartbeat").write_text(
            str(time.time()), encoding="ascii"
        )
        time.sleep(5)


if __name__ == "__main__":
    main()
