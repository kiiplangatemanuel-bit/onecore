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



def test_hr_attendance_contracts_and_duration():
    from datetime import datetime, timezone, timedelta
    from app.core.models import HRAttendance
    from app.services.hr import worked_minutes

    assert HRAttendance.__tablename__ == "hr_attendance"
    start = datetime(2026, 11, 7, 8, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=8, minutes=37)
    assert worked_minutes(start, end) == 517
    assert worked_minutes(start.replace(tzinfo=None), end) == 517
    with pytest.raises(ValueError):
        worked_minutes(end, start)
    paths = set(app.openapi()["paths"])
    assert "/api/v1/hr/attendance/clock-in" in paths
    assert "/api/v1/hr/attendance/clock-out" in paths
    assert "/api/v1/hr/my-attendance" in paths
    assert "/api/v1/hr/attendance" in paths


def test_school_fee_contracts_and_routes():
    from decimal import Decimal
    from app.core.models import SchoolFeeStructure, SchoolFeeCharge, SchoolFeePayment, SchoolFeePaymentAllocation
    from app.core.schemas import SchoolFeeStructureIn, SchoolFeePaymentIn

    schedule = SchoolFeeStructureIn(class_id=1, code="TUITION-T1",
        description="Term one tuition", academic_year=2026, term="Term 1",
        amount="12500.00", currency="KES", due_date="2026-11-30")
    assert schedule.amount == Decimal("12500.00")
    payment = SchoolFeePaymentIn(receipt_number="RCPT-001", method="cash",
        amount="5000.00", payment_date="2026-11-07",
        allocations=[{"charge_id": 1, "amount": "5000.00"}])
    assert payment.allocations[0].amount == payment.amount
    with pytest.raises(ValidationError):
        SchoolFeePaymentIn(receipt_number="RCPT-002", method="cash",
            amount="5000.00", payment_date="2026-11-07",
            allocations=[{"charge_id": 1, "amount": "4000.00"}])
    with pytest.raises(ValidationError):
        SchoolFeePaymentIn(receipt_number="RCPT-003", method="cash",
            amount="5000.00", payment_date="2026-11-07",
            allocations=[{"charge_id": 1, "amount": "2500.00"},
                         {"charge_id": 1, "amount": "2500.00"}])
    assert SchoolFeeStructure.__tablename__ == "school_fee_structures"
    assert SchoolFeeCharge.__tablename__ == "school_fee_charges"
    assert SchoolFeePayment.__tablename__ == "school_fee_payments"
    assert SchoolFeePaymentAllocation.__tablename__ == "school_fee_payment_allocations"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/school/fee-structures" in paths
    assert "/api/v1/school/fee-structures/{structure_id}/bill" in paths
    assert "/api/v1/school/learners/{learner_id}/fee-account" in paths
    assert "/api/v1/school/learners/{learner_id}/fee-payments" in paths


def test_healthcare_patient_and_appointment_contracts():
    from datetime import datetime, timezone, timedelta
    from app.core.models import HealthcarePatient, HealthcareAppointment
    from app.core.schemas import HealthcarePatientIn, HealthcareAppointmentIn

    patient = HealthcarePatientIn(patient_number="PAT-001",
        first_name="Asha", last_name="Njeri", phone="+254700000000")
    assert patient.patient_number == "PAT-001"
    start = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)
    appointment = HealthcareAppointmentIn(patient_id=1,
        appointment_number="APT-001", starts_at=start,
        ends_at=start + timedelta(minutes=30), reason="General consultation")
    assert appointment.ends_at > appointment.starts_at
    with pytest.raises(ValidationError):
        HealthcareAppointmentIn(patient_id=1, appointment_number="APT-002",
            starts_at="2026-11-09T09:00:00",
            ends_at="2026-11-09T09:30:00", reason="Consult")
    with pytest.raises(ValidationError):
        HealthcareAppointmentIn(patient_id=1, appointment_number="APT-003",
            starts_at=start, ends_at=start, reason="Consult")
    assert HealthcarePatient.__tablename__ == "healthcare_patients"
    assert HealthcareAppointment.__tablename__ == "healthcare_appointments"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/healthcare/patients" in paths
    assert "/api/v1/healthcare/appointments" in paths
    assert "/api/v1/healthcare/appointments/{appointment_id}/cancel" in paths
    assert "/api/v1/healthcare/appointments/{appointment_id}/complete" in paths
    assert "/healthcare" in paths
