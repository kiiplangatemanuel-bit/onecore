from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.models import User
from app.core.security import hash_password
from app.api.routes import router
from app.api.platform_routes import router as platform_router
from app.api.accounting_statements import router as accounting_statements_router
from app.api.payroll_completion import router as payroll_completion_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        email = settings.bootstrap_admin_email.lower()
        if not db.query(User).filter_by(email=email).first():
            db.add(User(email=email, full_name="OneCore Bootstrap Administrator",
                        password_hash=hash_password(settings.bootstrap_admin_password),
                        platform_role="root_superadmin"))
            db.commit()
    finally:
        db.close()
    yield

app = FastAPI(title=settings.app_name, version="0.1.0", description="OneCore modular-monolith foundation", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(platform_router)
app.include_router(accounting_statements_router)
app.include_router(payroll_completion_router)

@app.get("/school", response_class=HTMLResponse)
def school_ui():
    page = Path(__file__).resolve().parent / "web" / "school.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/pos", response_class=HTMLResponse)
def pos_ui():
    page = Path(__file__).resolve().parent / "web" / "pos.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/pos-sw.js", response_class=HTMLResponse)
def pos_service_worker():
    page = Path(__file__).resolve().parent / "web" / "pos-sw.js"
    return HTMLResponse(page.read_text(encoding="utf-8"), media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})

@app.get("/procurement", response_class=HTMLResponse)
def procurement_ui():
    page = Path(__file__).resolve().parent / "web" / "procurement.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/crm", response_class=HTMLResponse)
def crm_ui():
    page = Path(__file__).resolve().parent / "web" / "crm.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/sacco", response_class=HTMLResponse)
def sacco_ui():
    page = Path(__file__).resolve().parent / "web" / "sacco.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/pharmacy-lab", response_class=HTMLResponse)
def pharmacy_lab_ui():
    page = Path(__file__).resolve().parent / "web" / "pharmacy_lab.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/healthcare", response_class=HTMLResponse)
def healthcare_ui():
    page = Path(__file__).resolve().parent / "web" / "healthcare.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/hr", response_class=HTMLResponse)
def hr_ui():
    page = Path(__file__).resolve().parent / "web" / "hr.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/accounting", response_class=HTMLResponse)
def accounting_ui():
    page = Path(__file__).resolve().parent / "web" / "accounting.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/inventory", response_class=HTMLResponse)
def inventory_ui():
    page = Path(__file__).resolve().parent / "web" / "inventory.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/health")
def health():
    return {"status": "ok", "service": "onecore-api", "environment": settings.app_env}

@app.get("/", response_class=HTMLResponse)
def public_home():
    return HTMLResponse('''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OneCore Technologies Ltd</title><style>body{font:16px system-ui;margin:0;color:#152238;background:#f5f7fb}header,main,footer{max-width:1100px;margin:auto;padding:28px}header{display:flex;justify-content:space-between;align-items:center}a,button{color:#0757a6}.hero{padding:80px 28px;background:#10243d;color:white;border-radius:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}.card{background:white;padding:22px;border-radius:14px}footer{text-align:center;color:#536273}</style></head><body><header><strong>ONECORE TECHNOLOGIES LTD</strong><nav><a href="/docs">Developer API</a></nav></header><main><section class="hero"><h1>One Platform. Every Organization. Anywhere.</h1><p>Powering Africa's Organizations Through Intelligent Software.</p><p>Connected business, industry and operations software on one shared platform.</p><a href="/docs" style="color:#fff">Explore API documentation →</a></section><h2>One connected ecosystem</h2><section class="grid"><div class="card"><h3>Core Platform</h3><p>Identity, tenants, permissions, billing, configuration and audit.</p></div><div class="card"><h3>Business & Industry OS</h3><p>Business, POS, School, Hospital, Finance, HR, Property and more.</p></div><div class="card"><h3>Digital Ecosystem</h3><p>Website, developer, docs, support, partners, community and files.</p></div><div class="card"><h3>Operations & Governance</h3><p>Monitoring, incidents, releases, security, continuity and compliance.</p></div></section></main><footer>Powered by OneCore Technologies Ltd</footer></body></html>''')
