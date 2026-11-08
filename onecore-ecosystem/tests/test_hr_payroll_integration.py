from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.authorization import ROLE_PERMISSIONS
from app.core.database import Base, get_db
from app.core.models import Organization, User, Branch
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.main import app


def test_employee_to_approved_paid_payroll_flow_is_tenant_and_role_scoped():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = TestingSession()
    org = Organization(name="Payroll Test", slug="payroll-test", industry="general")
    users = [
        User(email="hr@example.test", full_name="HR Admin", password_hash="x"),
        User(email="approver@example.test", full_name="Payroll Approver", password_hash="x"),
        User(email="payment@example.test", full_name="Payment Officer", password_hash="x"),
    ]
    db.add(org)
    db.flush()
    db.add_all(users)
    db.flush()
    branch = Branch(id="payroll-branch", organization_id=org.id, code="HQ", name="Head Office")
    db.add(branch)
    db.commit()
    org_id, branch_id = org.id, branch.id
    db.close()

    actor = {"user": users[0], "role": "hr_admin"}

    def override_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    def override_user():
        return actor["user"]

    def override_membership():
        return type("MembershipContext", (), {
            "organization_id": org_id, "role": actor["role"], "branch_scope": branch_id
        })()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[current_user] = override_user
    app.dependency_overrides[active_membership] = override_membership

    try:
        with TestClient(app) as client:
            employee = client.post("/api/v1/hr/employees", json={
                "branch_id": branch_id, "employee_number": "PAY-001",
                "first_name": "Amina", "last_name": "Test",
                "hire_date": "2026-11-01", "base_salary": "20000.00",
                "currency": "KES", "pension_contribution": "1000.00",
                "recurring_allowances": {"transport": "1000.00"},
                "recurring_benefits": {"housing": "500.00"},
            })
            assert employee.status_code == 201, employee.text
            employee_id = employee.json()["id"]

            actor["role"] = "payroll_manager"
            rule = client.post("/api/v1/payroll/rule-sets", json={
                "effective_from": "2026-01-01", "currency": "KES",
                "paye_bands": [
                    {"lower_bound": "0", "upper_bound": "24000", "rate": "0.1"},
                    {"lower_bound": "24000", "upper_bound": None, "rate": "0.2"},
                ],
                "personal_relief": "1000.00",
                "pension_tax_deductible_limit": "3000.00",
                "nssf_tiers": [
                    {"lower_bound": "0", "upper_bound": "100000", "employee_rate": "0.06", "employer_rate": "0.06"},
                ],
                "shif_rate": "0.0275",
                "housing_levy_employee_rate": "0.015",
                "housing_levy_employer_rate": "0.015",
                "source_evidence": [
                    {"authority": "KRA", "url": "https://www.kra.go.ke/", "title": "KRA statutory rules", "effective_date": "2026-01-01", "checked_on": "2026-11-08"},
                    {"authority": "NSSF", "url": "https://www.nssf.or.ke/", "title": "NSSF statutory rules", "effective_date": "2026-01-01", "checked_on": "2026-11-08"},
                    {"authority": "SHA", "url": "https://sha.go.ke/", "title": "SHA statutory rules", "effective_date": "2026-01-01", "checked_on": "2026-11-08"},
                ],
            })
            assert rule.status_code == 201, rule.text
            rule_id = rule.json()["id"]
            assert client.post(f"/api/v1/payroll/rule-sets/{rule_id}/submit").status_code == 200

            actor["user"], actor["role"] = users[1], "payroll_approver"
            approved_rule = client.post(f"/api/v1/payroll/rule-sets/{rule_id}/approve")
            assert approved_rule.status_code == 200, approved_rule.text
            assert approved_rule.json()["status"] == "active"

            actor["user"], actor["role"] = users[0], "payroll_manager"
            run = client.post("/api/v1/payroll/runs", json={
                "branch_id": branch_id, "period_start": "2026-11-01",
                "period_end": "2026-11-30", "employee_ids": [employee_id],
                "idempotency_key": "payroll-2026-11-hq",
            })
            assert run.status_code == 201, run.text
            run_id = run.json()["id"]
            assert run.json()["gross_total"] == "21500.00"
            assert run.json()["employer_cost_total"] == "23112.50"
            assert client.post(f"/api/v1/payroll/runs/{run_id}/submit").status_code == 200

            actor["user"], actor["role"] = users[1], "payroll_approver"
            approved_run = client.post(f"/api/v1/payroll/runs/{run_id}/approve")
            assert approved_run.status_code == 200, approved_run.text
            assert approved_run.json()["status"] == "approved"

            slips = client.get(f"/api/v1/payroll/runs/{run_id}/payslips")
            assert slips.status_code == 200, slips.text
            assert len(slips.json()) == 1
            assert slips.json()[0]["employee_id"] == employee_id
            assert slips.json()[0]["net_pay"] == "17246.25"

            actor["user"], actor["role"] = users[2], "payroll_payment"
            paid = client.post(f"/api/v1/payroll/runs/{run_id}/mark-paid",
                               json={"payment_reference": "BANK-REF-2026-11"})
            assert paid.status_code == 200, paid.text
            assert paid.json()["status"] == "paid"

            actor["role"] = "staff"
            forbidden = client.get(f"/api/v1/payroll/runs/{run_id}/payslips")
            assert forbidden.status_code == 403
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
