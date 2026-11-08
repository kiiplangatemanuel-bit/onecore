from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.models import (
    Organization, User, AccountingAccount, AccountingInvoice,
    CRMContact, CRMLead, CRMCampaign, CRMQuote, CRMSalesOrder,
    CRMCampaignAttribution,
)
from app.api.routes import _record_paid_invoice_crm_attribution


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_fully_paid_crm_linked_invoice_emits_one_idempotent_campaign_event():
    db = _session()
    try:
        org = Organization(name="Attribution Test", slug="attribution-test", currency="KES")
        db.add(org)
        db.flush()
        user = User(email="finance@example.test", full_name="Finance", password_hash="x")
        db.add(user)
        db.flush()
        asset = AccountingAccount(
            organization_id=org.id, code="1100", name="Bank", account_type="asset", created_by=user.id
        )
        contact = CRMContact(
            organization_id=org.id, full_name="Customer One", created_by=user.id
        )
        campaign = CRMCampaign(
            organization_id=org.id, campaign_number="CMP-001", name="November campaign",
            channel="email", message="Campaign message", created_by=user.id
        )
        db.add_all([asset, contact, campaign])
        db.flush()
        lead = CRMLead(
            organization_id=org.id, contact_id=contact.id, source_campaign_id=campaign.id,
            title="Customer opportunity", created_by=user.id
        )
        db.add(lead)
        db.flush()
        quote = CRMQuote(
            organization_id=org.id, contact_id=contact.id, lead_id=lead.id,
            quote_number="QT-001", currency="KES",
            issue_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
            valid_until=datetime(2026, 11, 30, tzinfo=timezone.utc),
            subtotal=Decimal("1000.00"), tax_total=Decimal("0.00"),
            total=Decimal("1000.00"), created_by=user.id,
        )
        db.add(quote)
        db.flush()
        order = CRMSalesOrder(
            organization_id=org.id, quote_id=quote.id, contact_id=contact.id,
            lead_id=lead.id, order_number="SO-001", currency="KES",
            subtotal=Decimal("1000.00"), tax_total=Decimal("0.00"),
            total=Decimal("1000.00"), status="confirmed", created_by=user.id,
        )
        db.add(order)
        db.flush()
        invoice = AccountingInvoice(
            organization_id=org.id, invoice_type="receivable", contact_id=contact.id,
            crm_sales_order_id=order.id, invoice_number="INV-001",
            issue_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
            due_date=datetime(2026, 11, 30, tzinfo=timezone.utc), currency="KES",
            control_account_id=asset.id, subtotal=Decimal("1000.00"),
            tax_total=Decimal("0.00"), total=Decimal("1000.00"),
            amount_paid=Decimal("1000.00"), status="paid", created_by=user.id,
        )
        db.add(invoice)
        db.flush()

        created = _record_paid_invoice_crm_attribution(db, invoice, date(2026, 11, 8), user)
        db.commit()
        assert created is True

        events = db.query(CRMCampaignAttribution).filter_by(
            organization_id=org.id, accounting_invoice_id=invoice.id
        ).all()
        assert len(events) == 1
        assert events[0].campaign_id == campaign.id
        assert events[0].sales_order_id == order.id
        assert events[0].event_type == "invoice_paid"
        assert events[0].revenue_amount == Decimal("1000.00")
        assert events[0].currency == "KES"
        assert events[0].idempotency_key == f"accounting-invoice-paid-{invoice.id}"

        assert _record_paid_invoice_crm_attribution(db, invoice, date(2026, 11, 8), user) is False
        assert db.query(CRMCampaignAttribution).filter_by(
            organization_id=org.id, accounting_invoice_id=invoice.id
        ).count() == 1
    finally:
        db.close()


def test_invoice_attribution_uses_existing_order_campaign_event_when_lead_is_unlinked():
    db = _session()
    try:
        org = Organization(name="Fallback Test", slug="attribution-fallback", currency="KES")
        db.add(org)
        db.flush()
        user = User(email="fallback@example.test", full_name="Finance", password_hash="x")
        db.add(user)
        db.flush()
        asset = AccountingAccount(
            organization_id=org.id, code="1100", name="Bank", account_type="asset", created_by=user.id
        )
        contact = CRMContact(organization_id=org.id, full_name="Customer Two", created_by=user.id)
        campaign = CRMCampaign(
            organization_id=org.id, campaign_number="CMP-002", name="Linked campaign",
            channel="email", message="Campaign message", created_by=user.id
        )
        db.add_all([asset, contact, campaign])
        db.flush()
        lead = CRMLead(
            organization_id=org.id, contact_id=contact.id, title="Unlinked lead", created_by=user.id
        )
        db.add(lead)
        db.flush()
        quote = CRMQuote(
            organization_id=org.id, contact_id=contact.id, lead_id=lead.id,
            quote_number="QT-002", currency="KES",
            issue_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
            valid_until=datetime(2026, 11, 30, tzinfo=timezone.utc),
            subtotal=Decimal("500.00"), tax_total=Decimal("0.00"),
            total=Decimal("500.00"), created_by=user.id,
        )
        db.add(quote)
        db.flush()
        order = CRMSalesOrder(
            organization_id=org.id, quote_id=quote.id, contact_id=contact.id,
            lead_id=lead.id, order_number="SO-002", currency="KES",
            subtotal=Decimal("500.00"), tax_total=Decimal("0.00"),
            total=Decimal("500.00"), status="confirmed", created_by=user.id,
        )
        db.add(order)
        db.flush()
        db.add(CRMCampaignAttribution(
            organization_id=org.id, campaign_id=campaign.id, contact_id=contact.id,
            lead_id=lead.id, sales_order_id=order.id, event_type="order_won",
            revenue_amount=Decimal("500.00"), currency="KES",
            idempotency_key="manual-order-won-0001", created_by=user.id,
        ))
        invoice = AccountingInvoice(
            organization_id=org.id, invoice_type="receivable", contact_id=contact.id,
            crm_sales_order_id=order.id, invoice_number="INV-002",
            issue_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
            due_date=datetime(2026, 11, 30, tzinfo=timezone.utc), currency="KES",
            control_account_id=asset.id, subtotal=Decimal("500.00"),
            tax_total=Decimal("0.00"), total=Decimal("500.00"),
            amount_paid=Decimal("500.00"), status="paid", created_by=user.id,
        )
        db.add(invoice)
        db.flush()

        assert _record_paid_invoice_crm_attribution(db, invoice, date(2026, 11, 8), user) is True
        event = db.query(CRMCampaignAttribution).filter_by(
            organization_id=org.id, accounting_invoice_id=invoice.id
        ).one()
        assert event.campaign_id == campaign.id
        assert event.event_type == "invoice_paid"
    finally:
        db.close()
