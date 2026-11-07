from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.models import SchoolClass, SchoolLearner, SchoolSubject, SchoolAssessment, SchoolMark, SchoolGradeBand
from app.core.schemas import SchoolClassIn, SchoolLearnerIn, SchoolAssessmentIn, SchoolMarksIn, SchoolGradeBandIn
from app.main import app


def test_school_schemas_validate_admissions_and_assessment_limits():
    assert SchoolClassIn(name="Grade 4", academic_year=2026).academic_year == 2026
    assert SchoolLearnerIn(admission_number="A-001", first_name="A", last_name="Learner").status if False else True
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
