"""Safe, composable CRM audience segmentation predicates."""
from datetime import datetime, timezone
from sqlalchemy import and_, or_
from app.core.models import CRMContact, CRMLead

CONTACT_FIELDS = {
    "name": CRMContact.full_name,
    "company": CRMContact.company,
    "email": CRMContact.email,
    "phone": CRMContact.phone,
    "branch_id": CRMContact.branch_id,
}
LEAD_FIELDS = {"lead_stage": CRMLead.stage, "lead_source": CRMLead.source}
DATE_FIELDS = {"created_after": CRMContact.created_at, "created_before": CRMContact.created_at}


def validate_segment_definition(definition):
    if not isinstance(definition, dict) or set(definition) - {"all", "any"}:
        raise ValueError("Segment definition must contain only all/any groups")
    if not definition or any(not isinstance(definition.get(k, []), list) for k in ("all", "any")):
        raise ValueError("Segment groups must be arrays")
    clauses = definition.get("all", []) + definition.get("any", [])
    if len(clauses) > 30:
        raise ValueError("A segment may contain at most 30 criteria")
    allowed = set(CONTACT_FIELDS) | set(LEAD_FIELDS) | {"lead_value"}
    for item in clauses:
        if not isinstance(item, dict) or set(item) != {"field", "op", "value"}:
            raise ValueError("Each criterion requires field, op and value")
        field, op, value = item["field"], item["op"], item["value"]
        if field not in allowed:
            raise ValueError(f"Unsupported segment field: {field}")
        if op not in {"eq", "neq", "contains", "in", "gte", "lte"}:
            raise ValueError(f"Unsupported segment operator: {op}")
        if op == "in" and (not isinstance(value, list) or not 1 <= len(value) <= 100):
            raise ValueError("in operator requires an array of 1 to 100 values")
        if isinstance(value, str) and len(value) > 500:
            raise ValueError("Criterion text values cannot exceed 500 characters")
        if op == "contains" and not isinstance(value, str):
            raise ValueError("contains requires a text value")
        if op in {"eq", "neq", "gte", "lte"} and isinstance(value, (dict, list)):
            raise ValueError("Criterion values must be scalar")
    return definition


def _criterion(item):
    field, op, value = item["field"], item["op"], item["value"]
    if field in CONTACT_FIELDS:
        col = CONTACT_FIELDS[field]
    elif field in LEAD_FIELDS:
        col = LEAD_FIELDS[field]
    elif field == "lead_value":
        col = CRMLead.estimated_value
    else:
        raise ValueError("Unsupported segment field")
    if op == "eq": return col == value
    if op == "neq": return col != value
    if op == "contains": return col.ilike(f"%{value}%")
    if op == "in": return col.in_(value)
    if op == "gte": return col >= value
    if op == "lte": return col <= value
    raise ValueError("Unsupported segment operator")


def apply_segment(query, definition):
    validate_segment_definition(definition)
    clauses = definition.get("all", []) + definition.get("any", [])
    if any(x["field"] in LEAD_FIELDS or x["field"] == "lead_value" for x in clauses):
        query = query.outerjoin(
            CRMLead,
            and_(CRMLead.organization_id == CRMContact.organization_id,
                 CRMLead.contact_id == CRMContact.id),
        )
    all_clauses = [_criterion(x) for x in definition.get("all", [])]
    any_clauses = [_criterion(x) for x in definition.get("any", [])]
    if all_clauses: query = query.filter(and_(*all_clauses))
    if any_clauses: query = query.filter(or_(*any_clauses))
    return query.distinct()

def render_template_text(text, contact):
    import re
    values = {"full_name": contact.full_name or "",
              "first_name": (contact.full_name or "").split(" ")[0],
              "company": contact.company or "", "email": contact.email or "",
              "phone": contact.phone or ""}
    token = re.compile(r"{{\s*([a-z_]+)\s*}}")
    def replace(match):
        key = match.group(1)
        if key not in values:
            raise ValueError(f"Unsupported template variable: {key}")
        return values[key]
    return token.sub(replace, text or "")

def validate_template_text(text):
    import re
    allowed = {"first_name", "full_name", "company", "email", "phone"}
    token = re.compile(r"{{\s*([a-z_]+)\s*}}")
    for match in token.finditer(text or ""):
        if match.group(1) not in allowed:
            raise ValueError(f"Unsupported template variable: {match.group(1)}")
    return text
