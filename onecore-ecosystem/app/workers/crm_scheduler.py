import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from app.core.models import Organization, CRMWorkerHeartbeat
from app.core.database import SessionLocal
from app.services.crm_scheduler import run_due_schedules

logging.basicConfig(level=logging.INFO)
logger=logging.getLogger("onecore.crm_scheduler")


def main():
    while True:
        db=SessionLocal()
        try:
            processed=run_due_schedules(db,limit=10)
            now=datetime.now(timezone.utc)
            for (org_id,) in db.query(Organization.id).filter(Organization.is_active.is_(True)).all():
                heartbeat=db.query(CRMWorkerHeartbeat).filter_by(organization_id=org_id,worker_name="crm-scheduler").first()
                if heartbeat is None:
                    heartbeat=CRMWorkerHeartbeat(organization_id=org_id,worker_name="crm-scheduler")
                    db.add(heartbeat)
                heartbeat.last_seen_at=now;heartbeat.last_processed=processed;heartbeat.last_error=""
            db.commit()
            if processed:logger.info("processed %s due campaign schedules",processed)
        except Exception as exc:
            db.rollback()
            logger.exception("CRM scheduler iteration failed")
            now=datetime.now(timezone.utc)
            for (org_id,) in db.query(Organization.id).filter(Organization.is_active.is_(True)).all():
                heartbeat=db.query(CRMWorkerHeartbeat).filter_by(organization_id=org_id,worker_name="crm-scheduler").first()
                if heartbeat is None:
                    heartbeat=CRMWorkerHeartbeat(organization_id=org_id,worker_name="crm-scheduler")
                    db.add(heartbeat)
                heartbeat.last_seen_at=now;heartbeat.last_processed=0;heartbeat.last_error=type(exc).__name__
            db.commit()
        finally:
            db.close()
        Path("/tmp/crm-scheduler-heartbeat").write_text(str(time.time()),encoding="ascii")
        time.sleep(5)


if __name__=="__main__":
    main()
