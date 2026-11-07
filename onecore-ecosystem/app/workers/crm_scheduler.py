import logging
import time
from app.core.database import SessionLocal
from app.services.crm_scheduler import run_due_schedules

logging.basicConfig(level=logging.INFO)
logger=logging.getLogger("onecore.crm_scheduler")


def main():
    while True:
        db=SessionLocal()
        try:
            processed=run_due_schedules(db,limit=10)
            if processed:logger.info("processed %s due campaign schedules",processed)
        except Exception:
            logger.exception("CRM scheduler iteration failed")
        finally:
            db.close()
        time.sleep(5)


if __name__=="__main__":
    main()
