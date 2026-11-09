from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.models import Organization, User, AccountingAccount, AccountingJournal, AccountingJournalLine
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.main import app


def test_fx_posting_and_revaluation_create_balanced_tenant_journals():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,autoflush=False,autocommit=False,expire_on_commit=False)
    db=Session()
    org=Organization(name="FX Test",slug="fx-test",currency="KES")
    user=User(email="fx@example.test",full_name="FX Operator",password_hash="x")
    db.add_all([org,user]);db.flush()
    accounts=[
        AccountingAccount(organization_id=org.id,code="1000",name="USD receivable",account_type="asset",created_by=user.id),
        AccountingAccount(organization_id=org.id,code="2000",name="USD payable",account_type="liability",created_by=user.id),
        AccountingAccount(organization_id=org.id,code="4000",name="FX gain",account_type="revenue",created_by=user.id),
        AccountingAccount(organization_id=org.id,code="5000",name="FX loss",account_type="expense",created_by=user.id),
        AccountingAccount(organization_id=org.id,code="1010",name="Bank",account_type="asset",created_by=user.id),
    ]
    db.add_all(accounts);db.commit()
    org_id=org.id;user_id=user.id;account_ids=[x.id for x in accounts]
    db.close()
    actor={"user":user}
    def override_db():
        session=Session()
        try: yield session
        finally: session.close()
    def override_user(): return actor["user"]
    def override_membership():
        return type("MembershipContext",(),{"organization_id":org_id,"role":"org_admin","branch_scope":"*"})()
    app.dependency_overrides[get_db]=override_db
    app.dependency_overrides[current_user]=override_user
    app.dependency_overrides[active_membership]=override_membership
    try:
        with TestClient(app) as client:
            rate=client.post("/api/v1/accounting/fx/rates",json={
                "currency":"USD","rate_date":"2026-11-01","units_per_base":"0.0076923077",
                "source":"approved-finance-rate","reference":"RATE-001"})
            assert rate.status_code==201,rate.text
            rate_id=rate.json()["id"]
            posting=client.post("/api/v1/accounting/fx/postings",json={
                "rate_id":rate_id,"entry_date":"2026-11-09","foreign_amount":"100.00",
                "debit_account_id":account_ids[0],"credit_account_id":account_ids[4],
                "reference":"USD-INV-001","idempotency_key":"fx-posting-0001"})
            assert posting.status_code==201,posting.text
            assert posting.json()["base_amount"]=="13000.00"
            replay=client.post("/api/v1/accounting/fx/postings",json={
                "rate_id":rate_id,"entry_date":"2026-11-09","foreign_amount":"100.00",
                "debit_account_id":account_ids[0],"credit_account_id":account_ids[4],
                "reference":"USD-INV-001","idempotency_key":"fx-posting-0001"})
            assert replay.status_code==201 and replay.json()["replayed"] is True
            conflicting_replay=client.post("/api/v1/accounting/fx/postings",json={
                "rate_id":rate_id,"entry_date":"2026-11-09","foreign_amount":"101.00",
                "debit_account_id":account_ids[0],"credit_account_id":account_ids[4],
                "reference":"USD-INV-001","idempotency_key":"fx-posting-0001"})
            assert conflicting_replay.status_code==409

            revaluation=client.post("/api/v1/accounting/fx/revaluations",json={
                "currency":"USD","valuation_date":"2026-11-09","closing_rate":"0.008",
                "fx_gain_account_id":account_ids[2],"fx_loss_account_id":account_ids[3],
                "positions":[
                    {"account_id":account_ids[0],"position_type":"asset","foreign_balance":"100.00","carrying_base_amount":"12000.00"},
                    {"account_id":account_ids[1],"position_type":"liability","foreign_balance":"100.00","carrying_base_amount":"13000.00"}
                ],"idempotency_key":"fx-reval-0001"})
            assert revaluation.status_code==201,revaluation.text
            assert revaluation.json()["total_gain"]=="1000.00"
            assert revaluation.json()["total_loss"]=="0.00"
            check=override_db()
            session=next(check)
            try:
                journal=session.query(AccountingJournal).filter_by(id=revaluation.json()["journal_id"]).one()
                lines=session.query(AccountingJournalLine).filter_by(journal_id=journal.id).all()
                assert sum((Decimal(x.debit) for x in lines),Decimal("0"))==sum((Decimal(x.credit) for x in lines),Decimal("0"))
                # Liability reduction is a debit to the liability and a credit to FX gain.
                liability_line=next(x for x in lines if x.account_id==account_ids[1])
                assert Decimal(liability_line.debit)==Decimal("500.00")
                assert Decimal(liability_line.credit)==Decimal("0.00")
            finally:
                session.close()
    finally:
        app.dependency_overrides.pop(get_db,None)
        app.dependency_overrides.pop(current_user,None)
        app.dependency_overrides.pop(active_membership,None)
        Base.metadata.drop_all(engine)
        engine.dispose()
