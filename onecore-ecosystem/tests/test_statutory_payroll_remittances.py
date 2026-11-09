from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.models import Organization, User, AccountingAccount, AccountingJournal, AccountingJournalLine
from app.core.hr_payroll_models import PayrollRuleSet, PayrollRun, PayrollPayslip, PayrollAccountingLink, HREmployee
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.main import app


def test_statutory_batch_approval_remittance_and_ledger_settlement():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,autoflush=False,autocommit=False,expire_on_commit=False)
    db=Session()
    org=Organization(name="Statutory Test",slug="statutory-test",currency="KES")
    preparer=User(email="payroll-manager@example.test",full_name="Payroll Manager",password_hash="x")
    approver=User(email="payroll-approver@example.test",full_name="Payroll Approver",password_hash="x")
    payer=User(email="payroll-payer@example.test",full_name="Payroll Payer",password_hash="x")
    db.add_all([org,preparer,approver,payer]);db.flush()
    rules=PayrollRuleSet(organization_id=org.id,version=1,effective_from=datetime(2026,1,1,tzinfo=timezone.utc),currency="KES",rules={},source_evidence=[],created_by=preparer.id)
    db.add(rules);db.flush()
    employee=HREmployee(organization_id=org.id,employee_number="ST-001",first_name="Jane",last_name="Worker",hire_date=datetime(2026,1,1,tzinfo=timezone.utc),base_salary=Decimal("50000.00"),currency="KES",created_by=preparer.id)
    db.add(employee);db.flush()
    run=PayrollRun(organization_id=org.id,rule_set_id=rules.id,period_start=datetime(2026,10,1,tzinfo=timezone.utc),period_end=datetime(2026,10,31,tzinfo=timezone.utc),status="approved",currency="KES",employee_count=1,gross_total=Decimal("50000.00"),deductions_total=Decimal("2600.00"),net_total=Decimal("47400.00"),employer_cost_total=Decimal("50900.00"),idempotency_key="statutory-run-001",calculation_snapshot={},created_by=preparer.id)
    db.add(run);db.flush()
    accrual=AccountingJournal(organization_id=org.id,journal_number="STAT-ACCRUAL-1",status="posted",entry_date=datetime(2026,10,31,tzinfo=timezone.utc),created_by=preparer.id,posted_by=preparer.id,posted_at=datetime.now(timezone.utc))
    db.add(accrual);db.flush()
    link=PayrollAccountingLink(organization_id=org.id,payroll_run_id=run.id,journal_id=accrual.id,mapping_snapshot={},created_by=preparer.id)
    db.add(link)
    payslip=PayrollPayslip(organization_id=org.id,payroll_run_id=run.id,employee_id=employee.id,employee_number="ST-001",employee_name="Jane Worker",currency="KES",gross_pay=Decimal("50000.00"),taxable_pay=Decimal("50000.00"),paye=Decimal("1000.00"),nssf_employee=Decimal("600.00"),shif_employee=Decimal("500.00"),housing_levy_employee=Decimal("300.00"),pension_employee=Decimal("200.00"),total_deductions=Decimal("2600.00"),net_pay=Decimal("47400.00"),nssf_employer=Decimal("600.00"),housing_levy_employer=Decimal("300.00"),snapshot={})
    db.add(payslip)
    account_specs=[("1000","Bank","asset"),("2100","PAYE payable","liability"),("2110","NSSF payable","liability"),("2120","SHIF payable","liability"),("2130","Housing Levy payable","liability"),("2140","Pension payable","liability")]
    accounts=[AccountingAccount(organization_id=org.id,code=code,name=name,account_type=kind,created_by=preparer.id) for code,name,kind in account_specs]
    db.add_all(accounts);db.commit()
    org_id=org.id;run_id=run.id;user_map={"preparer":preparer,"approver":approver,"payer":payer};account_ids=[x.id for x in accounts];actor={"user":preparer,"role":"payroll_manager"}
    db.close()
    def override_db():
        session=Session()
        try: yield session
        finally: session.close()
    def override_user(): return actor["user"]
    def override_membership():
        return type("MembershipContext",(),{"organization_id":org_id,"role":actor["role"],"branch_scope":"*"})()
    app.dependency_overrides[get_db]=override_db
    app.dependency_overrides[current_user]=override_user
    app.dependency_overrides[active_membership]=override_membership
    try:
        with TestClient(app) as client:
            created=client.post("/api/v1/payroll/statutory-batches",json={"payroll_run_ids":[run_id],"idempotency_key":"statutory-batch-001"})
            assert created.status_code==201,created.text
            batch_id=created.json()["id"]
            assert created.json()["totals"]["NSSF_EMPLOYEE"]=="600.00"
            assert created.json()["totals"]["HOUSING_LEVY_EMPLOYER"]=="300.00"
            replay=client.post("/api/v1/payroll/statutory-batches",json={"payroll_run_ids":[run_id],"idempotency_key":"statutory-batch-001"})
            assert replay.status_code==201 and replay.json()["replayed"] is True
            duplicate_batch=client.post("/api/v1/payroll/statutory-batches",json={"payroll_run_ids":[run_id],"idempotency_key":"statutory-batch-002"})
            assert duplicate_batch.status_code==409
            returned=client.get(f"/api/v1/payroll/statutory-batches/{batch_id}/return")
            assert returned.status_code==200 and returned.json()["employee_lines"][0]["employee_number"]=="ST-001"
            submitted=client.post(f"/api/v1/payroll/statutory-batches/{batch_id}/submit",json={})
            assert submitted.status_code==200 and submitted.json()["status"]=="pending_approval"
            actor.update(user=user_map["approver"],role="payroll_approver")
            approved=client.post(f"/api/v1/payroll/statutory-batches/{batch_id}/approve",json={})
            assert approved.status_code==200 and approved.json()["status"]=="approved"
            actor.update(user=user_map["payer"],role="payroll_payment")
            payment=client.post(f"/api/v1/payroll/statutory-batches/{batch_id}/record-payment",json={
                "payment_reference":"BANK-STAT-001","payment_date":"2026-11-09",
                "bank_account_id":account_ids[0],"paye_payable_account_id":account_ids[1],
                "nssf_payable_account_id":account_ids[2],"shif_payable_account_id":account_ids[3],
                "housing_levy_payable_account_id":account_ids[4],"pension_payable_account_id":account_ids[5]})
            assert payment.status_code==200,payment.text
            assert payment.json()["status"]=="remitted"
            assert payment.json()["payment_journal_id"]
            check=Session()
            try:
                journal_id=payment.json()["payment_journal_id"]
                lines=check.query(AccountingJournalLine).filter_by(journal_id=journal_id).all()
                debits=sum((Decimal(x.debit) for x in lines),Decimal("0"))
                credits=sum((Decimal(x.credit) for x in lines),Decimal("0"))
                assert debits==credits==Decimal("3500.00")
            finally:
                check.close()
    finally:
        app.dependency_overrides.pop(get_db,None)
        app.dependency_overrides.pop(current_user,None)
        app.dependency_overrides.pop(active_membership,None)
        Base.metadata.drop_all(engine)
        engine.dispose()
