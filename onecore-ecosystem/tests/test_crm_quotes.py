from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.models import CRMQuote, CRMQuoteLine, CRMSalesOrder, CRMSalesOrderLine, CRMContactConsent, CRMCampaign, CRMCampaignRecipient
from app.core.schemas import CRMQuoteIn, CRMQuoteConvertIn, CRMContactConsentIn, CRMCampaignIn
from app.main import app


def test_crm_quote_schema_calculates_valid_contract_fields():
    payload = CRMQuoteIn(
        contact_id=1, quote_number="QT-2026-001", issue_date="2026-11-08",
        valid_until="2026-11-30",
        lines=[{"description":"Implementation service","quantity":"2",
                "unit_price":"1000.00","tax_rate":"16"}])
    assert payload.lines[0].quantity == Decimal("2")
    with pytest.raises(ValidationError):
        CRMQuoteIn(contact_id=1, quote_number="QT-002", issue_date="2026-11-08",
                   valid_until="2026-11-30", lines=[])


def test_crm_quote_models_and_routes_are_registered():
    assert CRMQuote.__tablename__ == "crm_quotes"
    assert CRMQuoteLine.__tablename__ == "crm_quote_lines"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/crm/quotes" in paths
    assert "/api/v1/crm/quotes/{quote_id}" in paths
    assert "/api/v1/crm/quotes/{quote_id}/issue" in paths
    assert "/api/v1/crm/quotes/{quote_id}/accept" in paths
    assert "/api/v1/crm/quotes/{quote_id}/reject" in paths
    assert "/api/v1/crm/forecast" in paths



def test_crm_quote_conversion_contract_and_routes():
    payload = CRMQuoteConvertIn(order_number="SO-QT-2026-001")
    assert payload.order_number == "SO-QT-2026-001"
    assert CRMSalesOrder.__tablename__ == "crm_sales_orders"
    assert CRMSalesOrderLine.__tablename__ == "crm_sales_order_lines"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/crm/quotes/{quote_id}/convert-to-order" in paths
    assert "/api/v1/crm/orders" in paths
    assert "/api/v1/crm/orders/{order_id}" in paths
    with pytest.raises(ValidationError):
        CRMQuoteConvertIn(order_number="invalid order number with spaces")



def test_crm_consent_and_campaign_contracts_and_routes():
    consent = CRMContactConsentIn(channel="email", decision="granted", source="website signup")
    assert consent.purpose == "marketing"
    with pytest.raises(ValidationError):
        CRMContactConsentIn(channel="email", decision="granted", source=" ")
    with pytest.raises(ValidationError):
        CRMContactConsentIn(channel="sms", decision="allowed", source="website")
    campaign = CRMCampaignIn(
        campaign_number="CMP-2026-001", name="November update",
        channel="email", message="Our November product update")
    assert campaign.channel == "email"
    assert CRMContactConsent.__tablename__ == "crm_contact_consents"
    assert CRMCampaign.__tablename__ == "crm_campaigns"
    assert CRMCampaignRecipient.__tablename__ == "crm_campaign_recipients"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/crm/contacts/{contact_id}/consents" in paths
    assert "/api/v1/crm/campaigns" in paths
    assert "/api/v1/crm/campaigns/{campaign_id}/prepare" in paths

from datetime import date
from app.core.models import HREmployee, HRLeaveRequest
from app.core.schemas import HREmployeeIn, HRLeaveRequestIn, HRLeaveDecisionIn
from app.services.hr import business_days


def test_hr_employee_and_leave_contracts():
    employee = HREmployeeIn(employee_number="EMP-001", first_name="Amina",
        last_name="Otieno", start_date="2026-11-02", employment_type="full_time")
    assert employee.employee_number == "EMP-001"
    request = HRLeaveRequestIn(employee_id=1, leave_type="annual",
        start_date="2026-11-09", end_date="2026-11-13",
        reason="Annual family leave")
    assert request.end_date > request.start_date
    assert HRLeaveDecisionIn(decision="approved").decision == "approved"
    assert HREmployee.__tablename__ == "hr_employees"
    assert HRLeaveRequest.__tablename__ == "hr_leave_requests"


def test_hr_leave_business_days_excludes_weekends():
    assert business_days(date(2026, 11, 9), date(2026, 11, 13)) == 5
    assert business_days(date(2026, 11, 7), date(2026, 11, 9)) == 1
    assert business_days(date(2026, 11, 9), date(2026, 11, 9)) == 1
    with pytest.raises(ValueError):
        business_days(date(2026, 11, 10), date(2026, 11, 9))


def test_hr_routes_registered():
    paths=set(app.openapi()["paths"])
    assert "/api/v1/hr/employees" in paths
    assert "/api/v1/hr/leave-requests" in paths
    assert "/api/v1/hr/my-leave-requests" in paths
    assert "/api/v1/hr/leave-requests/{request_id}/decision" in paths
    assert "/hr" in paths
