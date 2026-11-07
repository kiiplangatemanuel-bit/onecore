from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.school_reports import build_learner_report_rows, grade_for_percentage
from app.main import app


def test_weighted_subject_report_uses_published_mark_weights():
    bands = [
        SimpleNamespace(minimum_percent=Decimal("80"), maximum_percent=Decimal("100"),
                        grade="A", points=Decimal("4")),
        SimpleNamespace(minimum_percent=Decimal("60"), maximum_percent=Decimal("79.999"),
                        grade="B", points=Decimal("3")),
    ]
    rows = [
        {"assessment_id": 1, "title": "Quiz", "subject_id": 10, "subject_name": "Mathematics",
         "maximum_score": Decimal("20"), "weight": Decimal("1"), "score": Decimal("18")},
        {"assessment_id": 2, "title": "Exam", "subject_id": 10, "subject_name": "Mathematics",
         "maximum_score": Decimal("100"), "weight": Decimal("3"), "score": Decimal("70")},
    ]
    report = build_learner_report_rows(rows, bands)
    assert report["complete"] is True
    assert report["subjects"][0]["percentage"] == "72.00"
    assert report["subjects"][0]["grade"] == "B"
    assert report["overall_percentage"] == "72.00"


def test_report_card_marks_incomplete_if_any_published_assessment_is_unmarked():
    bands = [SimpleNamespace(minimum_percent=Decimal("0"), maximum_percent=Decimal("100"),
                             grade="P", points=Decimal("1"))]
    rows = [
        {"assessment_id": 1, "title": "Quiz", "subject_id": 10, "subject_name": "Science",
         "maximum_score": Decimal("20"), "weight": Decimal("1"), "score": Decimal("15")},
        {"assessment_id": 2, "title": "Exam", "subject_id": 10, "subject_name": "Science",
         "maximum_score": Decimal("100"), "weight": Decimal("2"), "score": None},
    ]
    report = build_learner_report_rows(rows, bands)
    assert report["complete"] is False
    assert report["subjects"][0]["status"] == "incomplete"
    assert report["subjects"][0]["percentage"] is None
    assert report["subjects"][0]["partial_percentage"] == "75.00"
    assert report["overall_percentage"] is None


def test_report_card_with_no_published_assessments_is_incomplete():
    report = build_learner_report_rows([], [])
    assert report["subjects"] == []
    assert report["complete"] is True
    assert report["overall_percentage"] is None


def test_school_report_card_route_is_registered():
    assert "/api/v1/school/learners/{learner_id}/report-card" in app.openapi()["paths"]
