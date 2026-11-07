from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.models import SchoolClass, SchoolLearner, SchoolSubject, SchoolAssessment, SchoolMark, SchoolGradeBand
from app.core.schemas import SchoolClassIn, SchoolLearnerIn, SchoolAssessmentIn, SchoolMarksIn, SchoolGradeBandIn, SchoolAttendanceIn
from app.main import app


def test_school_schemas_validate_admissions_and_assessment_limits():
    assert SchoolClassIn(name="Grade 4", academic_year=2026).academic_year == 2026
    assert SchoolLearnerIn(admission_number="A-001", first_name="Ada", last_name="Learner").admission_number == "A-001"
    with pytest.raises(ValidationError):
        SchoolAssessmentIn(class_id=1, subject_id=1, title="Exam", academic_year=2026,
                           term="Term 1", maximum_score=0)
    with pytest.raises(ValidationError):
        SchoolMarksIn(marks=[{"learner_id": 1, "score": -1}])


def test_school_models_are_tenant_scoped():
    assert SchoolClass.__tablename__ == "school_classes"
    assert SchoolLearner.__tablename__ == "school_learners"
    assert SchoolSubject.__tablename__ == "school_subjects"
    assert SchoolAssessment.__tablename__ == "school_assessments"
    assert SchoolMark.__tablename__ == "school_marks"
    assert SchoolGradeBand.__tablename__ == "school_grade_bands"


def test_school_api_routes_are_registered():
    paths = set(app.openapi()["paths"])
    assert "/api/v1/school/classes" in paths
    assert "/api/v1/school/admissions" in paths
    assert "/api/v1/school/learners/{learner_id}/admit" in paths
    assert "/api/v1/school/subjects" in paths
    assert "/api/v1/school/assessments" in paths
    assert "/api/v1/school/assessments/{assessment_id}/marks" in paths
    assert "/api/v1/school/assessments/{assessment_id}/publish" in paths
    assert "/api/v1/school/assessments/{assessment_id}/results" in paths
    assert "/api/v1/school/classes/{class_id}/report-cards" in paths
    assert "/school" in paths


def test_school_attendance_payload_rejects_duplicate_learners_and_bad_status():
    from pydantic import ValidationError
    payload = SchoolAttendanceIn(
        class_id=1, attendance_date="2026-11-07",
        entries=[{"learner_id": 1, "status": "present"},
                 {"learner_id": 2, "status": "late", "note": "Arrived after assembly"}])
    assert len(payload.entries) == 2
    with pytest.raises(ValidationError):
        SchoolAttendanceIn(class_id=1, attendance_date="2026-11-07",
            entries=[{"learner_id": 1, "status": "present"},
                     {"learner_id": 1, "status": "absent"}])
    with pytest.raises(ValidationError):
        SchoolAttendanceIn(class_id=1, attendance_date="2026-11-07",
            entries=[{"learner_id": 1, "status": "unknown"}])


def test_school_attendance_model_and_api_routes_are_registered():
    from app.core.models import SchoolAttendance
    assert SchoolAttendance.__tablename__ == "school_attendance"
    assert "/api/v1/school/attendance" in app.openapi()["paths"]
    operation = app.openapi()["paths"]["/api/v1/school/attendance"]
    assert "post" in operation and "get" in operation


def test_school_workspace_exposes_daily_attendance_controls():
    from pathlib import Path
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "school.html"
    html = page.read_text(encoding="utf-8")
    assert 'id="attendanceLoad"' in html
    assert 'id="attendanceSave"' in html
    assert "/school/attendance" in html
    assert all(status in html for status in ("present", "absent", "late", "excused"))



def test_school_learner_placement_schema_and_routes():
    from app.core.models import SchoolEnrollmentHistory
    from app.core.schemas import SchoolLearnerPlacementIn

    promotion = SchoolLearnerPlacementIn(
        target_class_id=22, effective_date="2027-01-01",
        change_type="promotion", reason="Completed the previous academic year")
    assert promotion.target_class_id == 22
    assert promotion.reason == "Completed the previous academic year"
    transfer = SchoolLearnerPlacementIn(
        target_class_id=23, effective_date="2026-11-08",
        change_type="transfer", reason="Family moved to another school branch")
    assert transfer.change_type == "transfer"
    with pytest.raises(ValidationError):
        SchoolLearnerPlacementIn(
            target_class_id=0, effective_date="2027-01-01",
            change_type="promotion", reason="Valid reason")
    with pytest.raises(ValidationError):
        SchoolLearnerPlacementIn(
            target_class_id=23, effective_date="2027-01-01",
            change_type="graduation", reason="Invalid change type")
    with pytest.raises(ValidationError):
        SchoolLearnerPlacementIn(
            target_class_id=23, effective_date="2027-01-01",
            change_type="transfer", reason="    ")
    assert SchoolEnrollmentHistory.__tablename__ == "school_enrollment_history"
    paths = app.openapi()["paths"]
    assert "/api/v1/school/learners/{learner_id}/placements" in paths
    assert "post" in paths["/api/v1/school/learners/{learner_id}/placements"]
    assert "get" in paths["/api/v1/school/learners/{learner_id}/placements"]


def test_advanced_school_schemas_validate_ranking_exam_and_bulk_promotion():
    from app.api.school_advanced import RankingConfigIn, ExamSessionIn, BulkPromotionIn, FeePaymentIn
    assert RankingConfigIn(academic_year=2026, grouping="subject",
                           ranking_method="dense").ranking_method == "dense"
    with pytest.raises(ValidationError):
        ExamSessionIn(timetable_id=1, subject_id=2, exam_date="2026-11-10",
                      starts_at="14:00", ends_at="13:00", venue="Hall")
    with pytest.raises(ValidationError):
        BulkPromotionIn(source_class_id=1, target_class_id=2, effective_date="2027-01-01",
                        learner_ids=[1, 1], reason="Completed academic year")
    payment=FeePaymentIn(learner_id=1, amount="1500.00", payment_date="2026-11-08",
                         method="mpesa", reference="QWERTY123", idempotency_key="mpesa-QWERTY123")
    assert str(payment.amount) == "1500.00"


def test_advanced_school_routes_are_registered():
    paths=app.openapi()["paths"]
    expected={
        "/api/v1/school/advanced/ranking-config",
        "/api/v1/school/rankings",
        "/api/v1/school/exam-timetables",
        "/api/v1/school/exam-timetables/{timetable_id}/sessions/{session_index}/seating",
        "/api/v1/school/assessments/{assessment_id}/moderation",
        "/api/v1/school/curriculum/nodes",
        "/api/v1/school/competencies",
        "/api/v1/school/promotions/bulk",
        "/api/v1/school/fees/charges",
        "/api/v1/school/fees/payments",
        "/api/v1/school/fees/payments/{payment_id}/allocate",
        "/api/v1/school/fees/learners/{learner_id}/statement",
        "/api/v1/school/guardian/portal",
        "/api/v1/school/teacher/portal",
        "/api/v1/school/staff/portal",
        "/api/v1/school/report-cards",
        "/api/v1/school/transcripts/{learner_id}",
        "/api/v1/school/dashboard",
        "/api/v1/school/reconciliation",
    }
    assert expected.issubset(paths.keys())


def test_school_guardian_and_teacher_roles_are_least_privilege():
    from app.core.authorization import ROLE_PERMISSIONS
    assert ROLE_PERMISSIONS["guardian"] == {"read"}
    assert "manage" not in ROLE_PERMISSIONS["teacher"]
    assert "manage" in ROLE_PERMISSIONS["school_admin"]
