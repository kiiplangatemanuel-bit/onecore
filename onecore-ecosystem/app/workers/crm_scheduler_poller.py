"""Poll the authenticated CRM scheduler API and report health."""
import json, logging, os, time
from pathlib import Path
from datetime import datetime, timezone
import httpx
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
log=logging.getLogger("onecore.crm_scheduler")
def main():
    base=os.getenv("CRM_SCHEDULER_API_URL","http://api:8000/api/v1/crm").rstrip("/")
    token=os.getenv("CRM_SCHEDULER_BEARER_TOKEN","").strip()
    interval=max(15,int(os.getenv("CRM_SCHEDULER_INTERVAL_SECONDS","30")))
    name=os.getenv("CRM_SCHEDULER_WORKER_NAME","crm-scheduler")
    if not token:raise SystemExit("CRM_SCHEDULER_BEARER_TOKEN is required; use a dedicated manager service identity")
    headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"}
    with httpx.Client(timeout=35,headers=headers) as client:
        while True:
            try:
                response=client.post(base+"/scheduler/run-due");response.raise_for_status()
                count=int(response.json().get("processed",0))
                client.post(base+"/scheduler/heartbeat",json={"worker_name":name,"processed":count,"error":""}).raise_for_status()
                log.info(json.dumps({"event":"crm_scheduler_poll","processed":count,"at":datetime.now(timezone.utc).isoformat()}))
            except Exception as exc:
                error=type(exc).__name__
                log.error(json.dumps({"event":"crm_scheduler_error","error_type":error}))
                try:client.post(base+"/scheduler/heartbeat",json={"worker_name":name,"processed":0,"error":error}).raise_for_status()
                except Exception:pass
            Path("/tmp/crm-scheduler-heartbeat").write_text(str(time.time()),encoding="ascii")
            time.sleep(interval)
if __name__=="__main__":main()
