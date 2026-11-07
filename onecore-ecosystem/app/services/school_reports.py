"""Weighted, published-assessment-only school report calculations."""
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def grade_for_percentage(percentage, grade_bands):
    value = Decimal(str(percentage))
    matches = [band for band in grade_bands
        if Decimal(str(band.minimum_percent)) <= value <= Decimal(str(band.maximum_percent))]
    if not matches:
        return None
    band = max(matches, key=lambda item: Decimal(str(item.minimum_percent)))
    return {"grade": band.grade, "points": str(band.points)}


def build_learner_report_rows(assessment_rows, grade_bands):
    grouped = {}
    overall_weighted = Decimal("0")
    overall_weight = Decimal("0")
    all_complete = True
    for row in assessment_rows:
        subject_id = row["subject_id"]
        group = grouped.setdefault(subject_id, {
            "subject_id": subject_id, "subject": row["subject_name"],
            "expected_assessments": 0, "marked_assessments": 0,
            "weighted_score": Decimal("0"), "weight_total": Decimal("0"),
            "assessments": [],
        })
        group["expected_assessments"] += 1
        score = row["score"]
        maximum = Decimal(str(row["maximum_score"]))
        weight = Decimal(str(row["weight"]))
        assessment = {
            "assessment_id": row["assessment_id"],
            "title": row["title"],
            "maximum_score": str(maximum),
            "weight": str(weight),
            "score": None if score is None else str(score),
        }
        group["assessments"].append(assessment)
        if score is None:
            continue
        score = Decimal(str(score))
        if maximum <= 0 or score < 0 or score > maximum or weight <= 0:
            raise ValueError("Invalid published assessment score or weight")
        percentage = score / maximum * Decimal("100")
        group["weighted_score"] += percentage * weight
        group["weight_total"] += weight
        group["marked_assessments"] += 1
        overall_weighted += percentage * weight
        overall_weight += weight

    subjects = []
    for group in sorted(grouped.values(), key=lambda item: item["subject"].casefold()):
        complete = group["marked_assessments"] == group["expected_assessments"]
        partial = None
        if group["weight_total"] > 0:
            partial = (group["weighted_score"] / group["weight_total"]).quantize(
                CENT, rounding=ROUND_HALF_UP)
        percentage = partial if complete else None
        grade = grade_for_percentage(percentage, grade_bands) if percentage is not None else None
        all_complete = all_complete and complete
        subjects.append({
            "subject_id": group["subject_id"], "subject": group["subject"],
            "expected_assessments": group["expected_assessments"],
            "marked_assessments": group["marked_assessments"],
            "status": "complete" if complete else "incomplete",
            "percentage": None if percentage is None else str(percentage),
            "partial_percentage": None if partial is None else str(partial),
            "grade": grade["grade"] if grade else None,
            "grade_points": grade["points"] if grade else None,
            "assessments": group["assessments"],
        })
    overall = None
    if all_complete and overall_weight > 0:
        overall = (overall_weighted / overall_weight).quantize(CENT, rounding=ROUND_HALF_UP)
    overall_grade = grade_for_percentage(overall, grade_bands) if overall is not None else None
    return {
        "subjects": subjects,
        "complete": all_complete,
        "overall_percentage": None if overall is None else str(overall),
        "overall_grade": overall_grade["grade"] if overall_grade else None,
        "overall_grade_points": overall_grade["points"] if overall_grade else None,
    }
