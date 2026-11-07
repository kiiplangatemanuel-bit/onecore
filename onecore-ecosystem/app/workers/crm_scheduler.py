import time
from app.core.database import SessionLocal
from app.services.crm_scheduler import run_due_schedules


def main():
    while True:
        db=SessionLocal()
        try:
            run_due_schedules(db,limit=10)
        finally:
            db.close()
        time.sleep(5)


if __name__=="__main__":
    main()
