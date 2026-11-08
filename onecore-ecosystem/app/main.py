from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text
from app.core.platform_security import LoginRateLimiter
from fastapi.responses import HTMLResponse
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.models import User
from app.core.security import hash_password
from app.api.routes import router
from app.api.inventory_completion import router as inventory_completion_router
from app.api.pos_completion import router as pos_completion_router
from app.api.platform_routes import router as platform_router
from app.api.platform_programme import router as platform_programme_router
from app.api.accounting_statements import router as accounting_statements_router
from app.api.accounting_completion import router as accounting_completion_router
from app.api.accounting_pos import router as accounting_pos_router
from app.api.mpesa import router as mpesa_router
from app.api.crm_campaigns import router as crm_campaigns_router
from app.api.crm_automation import router as crm_automation_router
from app.api.crm_analytics import router as crm_analytics_router
from app.api.healthcare_privacy import router as healthcare_privacy_router
from app.api.healthcare_hospital import router as healthcare_hospital_router
from app.api.pharmacy_lab import router as pharmacy_lab_router
from app.api.procurement_workflows import router as procurement_workflows_router
from app.api.school_advanced import router as school_advanced_router
from app.api.ai_routes import router as ai_router
from app.api.hr_payroll import router as hr_payroll_router
from app.api.support import router as support_router
from app.api.auth_workflows import router as auth_workflows_router
from app.api.portal_auth import router as portal_auth_router
from app.api.portal_workflows import router as portal_workflows_router
from app.api.auth_mfa import router as auth_mfa_router
from app.api.supabase_auth import router as supabase_auth_router
from app.api.developer_api_keys import router as developer_api_keys_router
from app.api.developer_webhooks import router as developer_webhooks_router
from app.core import hr_payroll_models  # noqa: F401 - register HR/payroll tables

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
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
trusted_hosts = [x.strip() for x in settings.trusted_hosts.split(",") if x.strip()]
if trusted_hosts and "*" not in trusted_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)
app.add_middleware(CORSMiddleware,
                   allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],
                   allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key", "X-Organization-ID", "X-POS-Device-Token", "X-Support-Access-Token", "X-OneCore-API-Key"])
app.state.login_rate_limiter = LoginRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)
app.state.public_write_rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=300)

app.include_router(router)
app.include_router(inventory_completion_router)
app.include_router(pos_completion_router)
app.include_router(platform_router)
app.include_router(platform_programme_router)
app.include_router(accounting_statements_router)
app.include_router(accounting_completion_router)
app.include_router(accounting_pos_router)
app.include_router(mpesa_router)
app.include_router(crm_campaigns_router)
app.include_router(crm_automation_router)
app.include_router(crm_analytics_router)
app.include_router(healthcare_privacy_router)
app.include_router(healthcare_hospital_router)
app.include_router(pharmacy_lab_router)
app.include_router(procurement_workflows_router)
app.include_router(school_advanced_router)
app.include_router(ai_router)
app.include_router(hr_payroll_router)
app.include_router(support_router)
app.include_router(auth_workflows_router)
app.include_router(portal_auth_router)
app.include_router(portal_workflows_router)
app.include_router(auth_mfa_router)
app.include_router(supabase_auth_router)
app.include_router(developer_api_keys_router)
app.include_router(developer_webhooks_router)

@app.get("/school", response_class=HTMLResponse)
def school_ui():
    page = Path(__file__).resolve().parent / "web" / "school.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/school/advanced", response_class=HTMLResponse)
def school_advanced_ui():
    page = Path(__file__).resolve().parent / "web" / "school_advanced.html"
    return HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control":"no-store"})

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

@app.get("/accounting", response_class=HTMLResponse)
def accounting_ui():
    page = Path(__file__).resolve().parent / "web" / "accounting.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/inventory", response_class=HTMLResponse)
def inventory_ui():
    page = Path(__file__).resolve().parent / "web" / "inventory.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/crm/automation", response_class=HTMLResponse)
def crm_automation_ui():
    page = Path(__file__).resolve().parent / "web" / "crm_automation.html"
    return HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control":"no-store"})

@app.get("/crm/forecast", response_class=HTMLResponse)
def crm_forecast_ui():
    page = Path(__file__).resolve().parent / "web" / "crm_forecast.html"
    return HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control":"no-store"})

@app.get("/healthcare/hospital", response_class=HTMLResponse)
def healthcare_hospital_ui():
    page = Path(__file__).resolve().parent / "web" / "healthcare_hospital.html"
    return HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control":"no-store"})

@app.get("/pharmacy-lab", response_class=HTMLResponse)
def pharmacy_lab_ui():
    page = Path(__file__).resolve().parent / "web" / "pharmacy_lab.html"
    return HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control":"no-store"})

@app.get("/healthcare", response_class=HTMLResponse)
def healthcare_ui():
    page = Path(__file__).resolve().parent / "web" / "healthcare.html"
    return HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control":"no-store"})

@app.middleware("http")
async def platform_security_middleware(request, call_next):
    import uuid
    from fastapi.responses import JSONResponse

    request_id = request.headers.get("x-request-id", "")
    if not request_id or len(request_id) > 128 or any(ord(ch) < 32 for ch in request_id):
        request_id = str(uuid.uuid4())

    client_ip = request.client.host if request.client else "unknown"
    login_request = request.url.path in {"/api/v1/auth/login", "/api/v1/auth/supabase-session"} and request.method == "POST"
    public_write_request = request.method == "POST" and request.url.path in {
        "/api/v1/auth/register-organization", "/api/v1/auth/verify-email", "/api/v1/auth/exchange-portal-code", "/api/v1/auth/password-reset/request", "/api/v1/auth/password-reset/confirm", "/api/v1/auth/mfa/challenge", "/api/v1/support/public/tickets"
    }
    response = None
    if settings.force_https and request.url.scheme != "https":
        response = JSONResponse({"detail": "HTTPS is required", "request_id": request_id}, status_code=400)
    elif public_write_request and not request.app.state.public_write_rate_limiter.allow(client_ip):
        response = JSONResponse(
            {"detail": "Too many public submissions. Try again later.", "request_id": request_id},
            status_code=429, headers={"Retry-After": "300"},
        )
    elif login_request and not request.app.state.login_rate_limiter.allow(client_ip):
        response = JSONResponse(
            {"detail": "Too many login attempts. Try again later.", "request_id": request_id},
            status_code=429, headers={"Retry-After": str(settings.login_rate_limit_window_seconds)},
        )
    if response is None:
        response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https:; connect-src 'self' https:; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.url.path.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Vary"] = "Authorization"
    if request.url.path == "/api/v1/auth/login" and response.status_code < 400:
        client_ip = request.client.host if request.client else "unknown"
        request.app.state.login_rate_limiter.reset(client_ip)
    return response

@app.get("/health")
def health():
    return {"status": "ok", "service": "onecore-api"}

def _verify_rls_database_boundary(connection):
    """Reject production DB roles that bypass RLS or critical tables without forced policies."""
    role = connection.execute(text("""
        SELECT current_user AS role_name, r.rolsuper AS is_superuser,
               r.rolbypassrls AS bypasses_rls
        FROM pg_roles r WHERE r.rolname = current_user
    """)).mappings().one_or_none()
    if not role or role["is_superuser"] or role["bypasses_rls"]:
        raise RuntimeError("Production database role must be a non-superuser NOBYPASSRLS role")

    required_tables = (
        "portal_workflow_records", "support_tickets", "support_messages",
        "support_attachments", "developer_api_keys", "developer_api_key_usages",
        "memberships", "audit_events", "mpesa_payment_intents",
        "mpesa_refund_intents", "procurement_settlements", "crm_campaign_deliveries",
        "developer_webhook_endpoints", "developer_webhook_deliveries",
        "records", "branches", "inventory_products", "inventory_stock_movements",
        "accounting_accounts", "accounting_journals", "accounting_journal_lines",
        "crm_contacts", "crm_leads", "procurement_suppliers",
        "procurement_purchase_orders", "pos_shifts", "pos_sales",
        "school_classes", "school_learners", "accounting_invoices", "status_alert_deliveries",
    )
    table_names = ", ".join("'" + name + "'" for name in required_tables)
    rows = connection.execute(text(f"""
        SELECT c.relname, c.relrowsecurity AS rls_enabled,
               c.relforcerowsecurity AS rls_forced,
               EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid) AS has_policy
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname IN ({table_names})
    """)).mappings().all()
    verified = {row["relname"]: row for row in rows}
    missing = [name for name in required_tables if name not in verified]
    unsafe = [
        name for name, row in verified.items()
        if not row["rls_enabled"] or not row["rls_forced"] or not row["has_policy"]
    ]
    if missing or unsafe:
        raise RuntimeError("Critical tenant RLS schema is incomplete or unsafe")


@app.get("/ready")
def readiness():
    from fastapi import HTTPException
    from app.core.database import engine
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            if settings.app_env.strip().lower() in {"production", "prod"}:
                _verify_rls_database_boundary(connection)
    except Exception:
        raise HTTPException(status_code=503, detail="Service dependencies or tenant-security controls are not ready")
    return {"status": "ready", "service": "onecore-api"}

@app.get("/", response_class=HTMLResponse)
def public_home():
    return HTMLResponse('''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OneCore Technologies Ltd</title><style>body{font:16px system-ui;margin:0;color:#152238;background:#f5f7fb}header,main,footer{max-width:1100px;margin:auto;padding:28px}header{display:flex;justify-content:space-between;align-items:center}a,button{color:#0757a6}.hero{padding:80px 28px;background:#10243d;color:white;border-radius:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}.card{background:white;padding:22px;border-radius:14px}footer{text-align:center;color:#536273}</style></head><body><header><strong>ONECORE TECHNOLOGIES LTD</strong><nav><a href="/docs">Developer API</a></nav></header><main><section class="hero"><h1>One Platform. Every Organization. Anywhere.</h1><p>Powering Africa's Organizations Through Intelligent Software.</p><p>Connected business, industry and operations software on one shared platform.</p><a href="/docs" style="color:#fff">Explore API documentation →</a></section><h2>One connected ecosystem</h2><section class="grid"><div class="card"><h3>Core Platform</h3><p>Identity, tenants, permissions, billing, configuration and audit.</p></div><div class="card"><h3>Business & Industry OS</h3><p>Business, POS, School, Hospital, Finance, HR, Property and more.</p></div><div class="card"><h3>Digital Ecosystem</h3><p>Website, developer, docs, support, partners, community and files.</p></div><div class="card"><h3>Operations & Governance</h3><p>Monitoring, incidents, releases, security, continuity and compliance.</p></div></section></main><footer>Powered by OneCore Technologies Ltd</footer></body></html>''')
