"""Hospital operations on top of the existing healthcare PHI boundary.

All patient-linked payloads are Fernet-encrypted, tenant/branch scoped and audited.
External pharmacy/lab/insurer connections are represented as durable integration
jobs until a verified provider adapter is configured; no live payer response is faked.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import (
    User, HealthcarePatient, HealthcareResource, HealthcareEvent, HealthcareAccessAudit,
    HealthcareBreakGlassSession,
)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import can_access_branch
from app.api.healthcare_privacy import (
    _require, _patient, _audit, _treatment_allowed, encrypt, decrypt,
)

router = APIRouter(prefix="/api/v1/healthcare", tags=["Healthcare hospital operations"])
NOW = lambda: datetime.now(timezone.utc)
RESOURCE_TYPES = {
    "ward", "room", "bed", "admission", "vital_observation", "nursing_task", "care_plan",
    "doctor_order", "treatment_plan", "invoice", "insurance_policy", "insurance_claim",
    "preauthorization", "settlement", "pharmacy_job", "laboratory_job", "emergency_visit",
    "theatre", "procedure", "clinical_document", "retention_policy", "recovery_drill",
    "integration_job",
}
ADMIN_ROLES = {"healthcare_admin"}
ROLE_ACTIONS = {
    "hospital.manage": {"healthcare_admin"},
    "admissions.manage": {"healthcare_admin", "clinician", "nurse", "receptionist", "ward_clerk"},
    "nursing.manage": {"healthcare_admin", "clinician", "nurse"},
    "observations.manage": {"healthcare_admin", "clinician", "nurse"},
    "orders.manage": {"healthcare_admin", "clinician"},
    "billing.manage": {"healthcare_admin", "billing_officer", "insurance_officer"},
    "insurance.manage": {"healthcare_admin", "insurance_officer"},
    "pharmacy.manage": {"healthcare_admin", "pharmacist"},
    "lab.manage": {"healthcare_admin", "lab_technician"},
    "emergency.manage": {"healthcare_admin", "clinician", "nurse", "receptionist"},
    "theatre.manage": {"healthcare_admin", "clinician", "theatre_staff"},
    "documents.manage": {"healthcare_admin", "clinician", "nurse", "theatre_staff"},
    "privacy.monitor": {"healthcare_admin", "privacy_officer", "clinical_auditor"},
    "retention.manage": {"healthcare_admin", "privacy_officer"},
    "recovery.manage": {"healthcare_admin"},
}


def _roles(db, m, u, branch_id):
    from app.api.healthcare_privacy import _roles as base_roles
    return base_roles(db, m, u, branch_id)


def _need(db, m, u, action: str, branch_id=None):
    if action not in ROLE_ACTIONS:
        raise HTTPException(403, "Unknown hospital permission")
    roles = _roles(db, m, u, branch_id)
    if not roles.intersection(ROLE_ACTIONS[action]):
        raise HTTPException(403, "Healthcare role does not grant this hospital action")
    if branch_id is None and (m.branch_scope or "").strip() != "*":
        raise HTTPException(403, "Select a branch within your assigned healthcare scope")
    return roles


def _patient_access(db, m, u, patient_id: int, permission="clinical.read", write=False):
    patient = _patient(db, patient_id, m)
    emergency, roles = _require(db, m, u, permission, patient.branch_id, patient.id, True)
    if write and not emergency and not _treatment_allowed(db, m.organization_id, patient.id):
        raise HTTPException(409, "Current treatment consent is required before recording care")
    return patient, emergency, roles


def _resource(db, m, resource_id: int, kind: str | None = None, lock=False):
    q = db.query(HealthcareResource).filter_by(id=resource_id, organization_id=m.organization_id)
    if kind:
        q = q.filter_by(resource_type=kind)
    row = q.with_for_update() if lock else q
    row = row.first()
    if not row or not can_access_branch(m, row.branch_id):
        raise HTTPException(404, "Hospital resource not found")
    return row


def _payload(row):
    return decrypt(row.encrypted_payload)


def _view(row, include_payload=True):
    result = {"id": row.id, "resource_type": row.resource_type, "branch_id": row.branch_id,
        "patient_id": row.patient_id, "parent_id": row.parent_id, "external_key": row.external_key,
        "status": row.status, "amount": str(row.amount) if row.amount is not None else None,
        "currency": row.currency, "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat()}
    if include_payload:
        result["data"] = _payload(row)
    return result


def _create(db, m, u, kind: str, data: dict, branch_id=None, patient_id=None,
            parent_id=None, status="active", external_key=None, idempotency_key=None,
            amount=None, currency="KES"):
    if kind not in RESOURCE_TYPES:
        raise HTTPException(422, "Unsupported hospital resource type")
    if branch_id is not None and not can_access_branch(m, branch_id):
        raise HTTPException(403, "Hospital branch is outside your scope")
    if external_key and db.query(HealthcareResource.id).filter_by(
        organization_id=m.organization_id, resource_type=kind, external_key=external_key).first():
        raise HTTPException(409, "Resource reference already exists")
    if idempotency_key:
        existing = db.query(HealthcareResource).filter_by(
            organization_id=m.organization_id, resource_type=kind,
            idempotency_key=idempotency_key).first()
        if existing:
            if existing.patient_id != patient_id or _payload(existing) != data:
                raise HTTPException(409, "Idempotency key was already used with different data")
            return existing
    row = HealthcareResource(organization_id=m.organization_id, branch_id=branch_id,
        patient_id=patient_id, parent_id=parent_id, resource_type=kind,
        external_key=external_key, idempotency_key=idempotency_key, status=status,
        amount=amount, currency=currency, encrypted_payload=encrypt(data),
        created_by=u.id, updated_by=u.id)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Duplicate hospital resource reference or idempotency key")
    return row


def _event(db, m, u, patient_id, branch_id, event_type, detail, resource_id=None, idempotency_key=None):
    row = HealthcareEvent(organization_id=m.organization_id, branch_id=branch_id,
        patient_id=patient_id, resource_id=resource_id, event_type=event_type,
        idempotency_key=idempotency_key, encrypted_detail=encrypt(detail), actor_user_id=u.id)
    db.add(row)
    return row


def _money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(422, "A valid monetary amount is required")
    if not amount.is_finite() or amount <= 0 or amount.quantize(Decimal("0.01")) != amount:
        raise HTTPException(422, "Amount must be positive with at most two decimal places")
    return amount


def _required_text(data, key, max_len=180):
    value = str(data.get(key, "")).strip()
    if not value or len(value) > max_len:
        raise HTTPException(422, f"{key} is required (maximum {max_len} characters)")
    return value


def _create_patient_resource(kind, payload, m, u, db, patient_id, action, write=True,
                             amount=None, status="active", idempotency_key=None):
    patient, emergency, _ = _patient_access(db, m, u, patient_id,
        "clinical.write" if write else "clinical.read", write=write)
    if kind in {"invoice", "insurance_policy", "insurance_claim", "preauthorization", "settlement"}:
        _need(db, m, u, "insurance.manage" if kind in {"insurance_policy","insurance_claim","preauthorization","settlement"} else "billing.manage", patient.branch_id)
    row = _create(db, m, u, kind, payload, patient.branch_id, patient.id,
        status=status, amount=amount, idempotency_key=idempotency_key)
    _audit(db, m, u, patient, action, str(payload.get("reason", "")), emergency)
    _event(db, m, u, patient.id, patient.branch_id, action, {"resource_id": row.id}, row.id, idempotency_key)
    db.commit()
    db.refresh(row)
    return _view(row)


# ---- Ward, room and bed inventory ----

@router.post("/wards", status_code=201)
def create_ward(payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    branch = payload.get("branch_id")
    _need(db, m, u, "hospital.manage", branch)
    data = {"name": _required_text(payload, "name"), "code": _required_text(payload, "code", 40),
            "specialty": str(payload.get("specialty", "general"))[:80]}
    row = _create(db, m, u, "ward", data, branch, external_key=data["code"])
    db.commit()
    return _view(row)


@router.post("/wards/{ward_id}/rooms", status_code=201)
def create_room(ward_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    ward = _resource(db, m, ward_id, "ward")
    _need(db, m, u, "hospital.manage", ward.branch_id)
    data = {"name": _required_text(payload, "name"), "code": _required_text(payload, "code", 40),
            "room_type": str(payload.get("room_type", "standard"))[:40], "floor": str(payload.get("floor", ""))[:30]}
    row = _create(db, m, u, "room", data, ward.branch_id, parent_id=ward.id, external_key=f"{ward.id}:{data['code']}")
    db.commit()
    return _view(row)


@router.post("/rooms/{room_id}/beds", status_code=201)
def create_bed(room_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    room = _resource(db, m, room_id, "room")
    _need(db, m, u, "hospital.manage", room.branch_id)
    data = {"label": _required_text(payload, "label", 40), "bed_type": str(payload.get("bed_type", "standard"))[:40]}
    row = _create(db, m, u, "bed", data, room.branch_id, parent_id=room.id,
                  status="available", external_key=f"{room.id}:{data['label']}")
    db.commit()
    return _view(row)


@router.get("/beds")
def list_beds(branch_id: str, ward_id: int | None=None, status: str | None=None,
              m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    _need(db, m, u, "admissions.manage", branch_id)
    query = db.query(HealthcareResource).filter_by(
        organization_id=m.organization_id, resource_type="bed", branch_id=branch_id)
    rows = query.order_by(HealthcareResource.id).all()
    out = []
    for bed in rows:
        room = _resource(db, m, bed.parent_id, "room") if bed.parent_id else None
        if ward_id is not None and (not room or room.parent_id != ward_id): continue
        if status and bed.status != status: continue
        out.append({**_view(bed), "room": _view(room) if room else None})
    return out


@router.get("/occupancy")
def occupancy(branch_id: str, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    _need(db, m, u, "admissions.manage", branch_id)
    beds = db.query(HealthcareResource).filter_by(
        organization_id=m.organization_id, branch_id=branch_id, resource_type="bed").all()
    counts = {"available": 0, "occupied": 0, "blocked": 0, "maintenance": 0}
    for bed in beds:
        counts[bed.status if bed.status in counts else "blocked"] += 1
    total = len(beds)
    return {"branch_id": branch_id, "total_beds": total, "beds": counts,
        "occupancy_percent": round(counts["occupied"] * 100 / total, 2) if total else 0}


# ---- Inpatient admissions, discharge and transfers ----

@router.post("/admissions", status_code=201)
def admit_patient(payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient_id = int(payload.get("patient_id", 0))
    patient, emergency, _ = _patient_access(db, m, u, patient_id, "patient.read", write=True)
    _need(db, m, u, "admissions.manage", patient.branch_id)
    patient = db.query(HealthcarePatient).filter_by(id=patient.id, organization_id=m.organization_id).with_for_update().first()
    if payload.get("idempotency_key"):
        retry = db.query(HealthcareResource).filter_by(organization_id=m.organization_id,
            resource_type="admission", idempotency_key=payload["idempotency_key"]).first()
        if retry:
            if retry.patient_id != patient.id: raise HTTPException(409, "Idempotency key belongs to another patient")
            return _view(retry)
    active = db.query(HealthcareResource.id).filter_by(organization_id=m.organization_id,
        patient_id=patient.id, resource_type="admission", status="admitted").first()
    if active: raise HTTPException(409, "Patient already has an active inpatient admission")
    bed = _resource(db, m, int(payload.get("bed_id", 0)), "bed", lock=True)
    if bed.branch_id != patient.branch_id or bed.status != "available":
        raise HTTPException(409, "Selected bed is not available in the patient's branch")
    admission_data = {"admitted_at": NOW().isoformat(),
        "admission_reason": _required_text(payload, "admission_reason", 1000),
        "admitting_doctor_id": u.id, "bed_id": bed.id, "ward_room_id": bed.parent_id,
        "diagnosis_code": str(payload.get("diagnosis_code", ""))[:40], "discharge_summary": ""}
    row = _create(db, m, u, "admission", admission_data, patient.branch_id, patient.id,
        status="admitted", idempotency_key=payload.get("idempotency_key"))
    bed.status = "occupied"; bed.updated_by = u.id; bed.updated_at = NOW()
    _audit(db, m, u, patient, "admission.created", payload.get("reason", ""), emergency)
    _event(db, m, u, patient.id, patient.branch_id, "patient.admitted",
        {"bed_id": bed.id, "admission_id": row.id}, row.id, payload.get("idempotency_key"))
    db.commit()
    return _view(row)


@router.post("/admissions/{admission_id}/discharge")
def discharge_patient(admission_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    admission = _resource(db, m, admission_id, "admission", lock=True)
    patient, emergency, _ = _patient_access(db, m, u, admission.patient_id, "clinical.write", write=True)
    _need(db, m, u, "admissions.manage", patient.branch_id)
    if admission.status != "admitted":
        raise HTTPException(409, "Only an admitted patient can be discharged")
    summary = _required_text(payload, "discharge_summary", 4000)
    data = _payload(admission); data.update({"discharged_at": NOW().isoformat(),
        "discharge_summary": summary, "discharge_destination": str(payload.get("destination", "home"))[:80]})
    admission.encrypted_payload = encrypt(data); admission.status = "discharged"
    admission.updated_by = u.id; admission.updated_at = NOW()
    bed_id = int(data["bed_id"])
    bed = _resource(db, m, bed_id, "bed", lock=True)
    if bed.status != "occupied":
        raise HTTPException(409, "Admission bed occupancy is inconsistent; resolve before discharge")
    bed.status = "available"; bed.updated_by = u.id; bed.updated_at = NOW()
    _audit(db, m, u, patient, "admission.discharged", payload.get("reason", ""), emergency)
    _event(db, m, u, patient.id, patient.branch_id, "patient.discharged",
        {"admission_id": admission.id, "bed_id": bed.id, "summary": summary}, admission.id)
    db.commit()
    return _view(admission)


@router.post("/admissions/{admission_id}/transfer")
def transfer_patient(admission_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    admission = _resource(db, m, admission_id, "admission", lock=True)
    patient, emergency, _ = _patient_access(db, m, u, admission.patient_id, "clinical.write", write=True)
    _need(db, m, u, "admissions.manage", patient.branch_id)
    if admission.status != "admitted": raise HTTPException(409, "Only admitted patients can be transferred")
    target = _resource(db, m, int(payload.get("target_bed_id", 0)), "bed", lock=True)
    if target.branch_id != patient.branch_id or target.status != "available":
        raise HTTPException(409, "Target bed is not available in the patient's branch")
    data = _payload(admission); old_id = int(data["bed_id"])
    if old_id == target.id: raise HTTPException(422, "Target bed is already assigned")
    old = _resource(db, m, old_id, "bed", lock=True)
    if old.status != "occupied": raise HTTPException(409, "Current bed occupancy is inconsistent")
    old.status = "available"; old.updated_by = u.id; old.updated_at = NOW()
    target.status = "occupied"; target.updated_by = u.id; target.updated_at = NOW()
    data.update({"bed_id": target.id, "ward_room_id": target.parent_id,
        "last_transfer_at": NOW().isoformat(), "transfer_reason": _required_text(payload, "reason", 500)})
    admission.encrypted_payload = encrypt(data); admission.updated_by = u.id; admission.updated_at = NOW()
    _audit(db, m, u, patient, "admission.transferred", payload["reason"], emergency)
    _event(db, m, u, patient.id, patient.branch_id, "patient.transferred",
        {"admission_id": admission.id, "from_bed_id": old.id, "to_bed_id": target.id, "reason": payload["reason"]}, admission.id)
    db.commit()
    return _view(admission)


@router.get("/patients/{patient_id}/movement-history")
def movement_history(patient_id: int, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _ = _patient_access(db, m, u, patient_id, "clinical.read", write=False)
    rows = db.query(HealthcareEvent).filter_by(organization_id=m.organization_id, patient_id=patient.id).order_by(HealthcareEvent.occurred_at).all()
    _audit(db, m, u, patient, "patient.movement_history.read", "", emergency); db.commit()
    return [{"id": x.id, "event_type": x.event_type, "occurred_at": x.occurred_at.isoformat(),
        "detail": decrypt(x.encrypted_detail)} for x in rows if x.event_type.startswith("patient.")]


# ---- Clinical observations, nursing and doctor orders ----

@router.post("/patients/{patient_id}/observations", status_code=201)
def record_observation(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _ = _patient_access(db, m, u, patient_id, "clinical.write", write=True)
    _need(db, m, u, "observations.manage", patient.branch_id)
    values = payload.get("values")
    if not isinstance(values, dict) or not values or len(values) > 30: raise HTTPException(422, "Observation values object is required")
    allowed = {"temperature_c", "pulse_bpm", "respiratory_rate", "systolic_bp", "diastolic_bp",
        "spo2_percent", "weight_kg", "height_cm", "pain_score", "blood_glucose_mmol"}
    if set(values) - allowed: raise HTTPException(422, "Unsupported observation field")
    numeric = {}
    bounds = {"temperature_c": (25, 45), "pulse_bpm": (20, 250), "respiratory_rate": (4, 80),
        "systolic_bp": (40, 300), "diastolic_bp": (20, 200), "spo2_percent": (0, 100),
        "weight_kg": (0.2, 500), "height_cm": (20, 260), "pain_score": (0, 10), "blood_glucose_mmol": (0.1, 60)}
    for key, value in values.items():
        try: n = float(value)
        except (ValueError, TypeError): raise HTTPException(422, f"{key} must be numeric")
        if not bounds[key][0] <= n <= bounds[key][1]: raise HTTPException(422, f"{key} is outside accepted recording bounds")
        numeric[key] = n
    row = _create(db, m, u, "vital_observation", {"values": numeric, "observed_at": NOW().isoformat(),
        "recorded_by": u.id, "note": str(payload.get("note", ""))[:500]}, patient.branch_id, patient.id,
        status="recorded", idempotency_key=payload.get("idempotency_key"))
    _audit(db, m, u, patient, "clinical.observation.created", payload.get("reason", ""), emergency)
    _event(db, m, u, patient.id, patient.branch_id, "observation.recorded", {"observation_id": row.id}, row.id)
    db.commit()
    return _view(row)


@router.post("/patients/{patient_id}/care-plans", status_code=201)
def create_care_plan(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _ = _patient_access(db, m, u, patient_id, "clinical.write", write=True)
    _need(db, m, u, "nursing.manage", patient.branch_id)
    interventions = payload.get("interventions")
    if not isinstance(interventions, list) or not interventions or len(interventions) > 100:
        raise HTTPException(422, "Care plan needs 1–100 interventions")
    clean = [{"goal": _required_text(x, "goal", 500), "intervention": _required_text(x, "intervention", 1000),
        "frequency": str(x.get("frequency", ""))[:80]} for x in interventions if isinstance(x, dict)]
    if len(clean) != len(interventions): raise HTTPException(422, "Invalid care plan intervention")
    row = _create(db, m, u, "care_plan", {"title": _required_text(payload, "title"),
        "problem": _required_text(payload, "problem", 1000), "interventions": clean,
        "review_at": payload.get("review_at"), "created_by": u.id}, patient.branch_id, patient.id, status="active")
    _audit(db, m, u, patient, "nursing.care_plan.created", payload.get("reason", ""), emergency)
    _event(db, m, u, patient.id, patient.branch_id, "care_plan.created", {"care_plan_id": row.id}, row.id)
    db.commit()
    return _view(row)


@router.post("/patients/{patient_id}/nursing-tasks", status_code=201)
def create_nursing_task(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _ = _patient_access(db, m, u, patient_id, "clinical.write", write=True)
    _need(db, m, u, "nursing.manage", patient.branch_id)
    due = payload.get("due_at")
    if not due: raise HTTPException(422, "due_at is required")
    row = _create(db, m, u, "nursing_task", {"task": _required_text(payload, "task", 1000),
        "due_at": due, "assigned_to": payload.get("assigned_to"), "completed_at": None,
        "completion_note": ""}, patient.branch_id, patient.id, status="pending",
        idempotency_key=payload.get("idempotency_key"))
    _audit(db, m, u, patient, "nursing.task.created", "", emergency); db.commit()
    return _view(row)


@router.post("/nursing-tasks/{task_id}/complete")
def complete_nursing_task(task_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    row = _resource(db, m, task_id, "nursing_task", lock=True)
    patient, emergency, _ = _patient_access(db, m, u, row.patient_id, "clinical.write", write=True)
    _need(db, m, u, "nursing.manage", patient.branch_id)
    if row.status != "pending": raise HTTPException(409, "Only pending nursing tasks can be completed")
    data = _payload(row); data.update({"completed_at": NOW().isoformat(), "completion_note": str(payload.get("note", ""))[:1000], "completed_by": u.id})
    row.encrypted_payload = encrypt(data); row.status = "completed"; row.updated_by = u.id
    _audit(db, m, u, patient, "nursing.task.completed", "", emergency); db.commit()
    return _view(row)


@router.post("/patients/{patient_id}/doctor-orders", status_code=201)
def create_doctor_order(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, roles = _patient_access(db, m, u, patient_id, "clinical.write", write=True)
    _need(db, m, u, "orders.manage", patient.branch_id)
    order_type = payload.get("order_type")
    if order_type not in {"medication", "laboratory", "imaging", "procedure", "nursing", "diet", "other"}:
        raise HTTPException(422, "Unsupported doctor order type")
    row = _create(db, m, u, "doctor_order", {"order_type": order_type,
        "description": _required_text(payload, "description", 2000), "instructions": str(payload.get("instructions", ""))[:4000],
        "ordered_by": u.id, "ordered_at": NOW().isoformat(), "priority": payload.get("priority", "routine")},
        patient.branch_id, patient.id, status="pending", idempotency_key=payload.get("idempotency_key"))
    _audit(db, m, u, patient, "clinical.doctor_order.created", "", emergency)
    _event(db, m, u, patient.id, patient.branch_id, "doctor_order.created", {"order_id": row.id}, row.id)
    db.commit()
    return _view(row)


@router.post("/doctor-orders/{order_id}/decision")
def decide_doctor_order(order_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    row = _resource(db, m, order_id, "doctor_order", lock=True)
    patient, emergency, _ = _patient_access(db, m, u, row.patient_id, "clinical.write", write=True)
    _need(db, m, u, "orders.manage", patient.branch_id)
    decision = payload.get("decision")
    if decision not in {"accepted", "in_progress", "completed", "cancelled", "rejected"}:
        raise HTTPException(422, "Invalid order decision")
    if row.status in {"completed", "cancelled", "rejected"}: raise HTTPException(409, "Order is already terminal")
    data = _payload(row); data.update({"decision_at": NOW().isoformat(), "decision_by": u.id,
        "decision_reason": str(payload.get("reason", ""))[:1000]})
    row.encrypted_payload = encrypt(data); row.status = decision; row.updated_by = u.id
    _audit(db, m, u, patient, "clinical.doctor_order.decision", payload.get("reason", ""), emergency); db.commit()
    return _view(row)


@router.post("/patients/{patient_id}/treatment-plans", status_code=201)
def create_treatment_plan(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _ = _patient_access(db, m, u, patient_id, "clinical.write", write=True)
    _need(db, m, u, "orders.manage", patient.branch_id)
    row = _create(db, m, u, "treatment_plan", {"diagnosis": _required_text(payload, "diagnosis", 1000),
        "plan": _required_text(payload, "plan", 4000), "review_date": payload.get("review_date"),
        "author_id": u.id}, patient.branch_id, patient.id, status="active")
    _audit(db, m, u, patient, "clinical.treatment_plan.created", "", emergency); db.commit()
    return _view(row)


# ---- Billing, insurance and settlement ----

@router.post("/patients/{patient_id}/invoices", status_code=201)
def create_invoice(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _ = _patient_access(db, m, u, patient_id, "patient.read", write=False)
    _need(db, m, u, "billing.manage", patient.branch_id)
    lines = payload.get("lines")
    if not isinstance(lines, list) or not lines or len(lines) > 100: raise HTTPException(422, "Invoice requires 1–100 lines")
    clean=[]; total=Decimal("0")
    for line in lines:
        if not isinstance(line, dict): raise HTTPException(422, "Invalid invoice line")
        qty = _money(line.get("quantity")); price = _money(line.get("unit_price"))
        subtotal = (qty * price).quantize(Decimal("0.01")); total += subtotal
        clean.append({"description": _required_text(line, "description", 500), "quantity": str(qty),
            "unit_price": str(price), "line_total": str(subtotal)})
    currency = str(payload.get("currency", "KES")).upper()
    if len(currency) != 3 or not currency.isalpha(): raise HTTPException(422, "Currency must be an ISO 4217 code")
    row = _create(db, m, u, "invoice", {"invoice_number": _required_text(payload, "invoice_number", 80),
        "issued_at": NOW().isoformat(), "due_date": payload.get("due_date"), "lines": clean,
        "paid_amount": "0.00", "balance": str(total), "patient_id": patient.id},
        patient.branch_id, patient.id, status="issued", external_key=_required_text(payload, "invoice_number", 80),
        amount=total, currency=currency, idempotency_key=payload.get("idempotency_key"))
    _audit(db, m, u, patient, "billing.invoice.created", "", emergency)
    _event(db, m, u, patient.id, patient.branch_id, "invoice.issued", {"invoice_id": row.id, "amount": str(total)}, row.id)
    db.commit()
    return _view(row)


@router.post("/patients/{patient_id}/insurance/eligibility")
def record_eligibility(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _ = _patient_access(db, m, u, patient_id, "patient.read", write=False)
    _need(db, m, u, "insurance.manage", patient.branch_id)
    result = payload.get("result")
    if result not in {"eligible", "ineligible", "pending", "unknown"}: raise HTTPException(422, "Invalid eligibility result")
    row = _create(db, m, u, "insurance_policy", {"payer": _required_text(payload, "payer"),
        "member_number": _required_text(payload, "member_number", 100), "result": result,
        "checked_at": NOW().isoformat(), "coverage_notes": str(payload.get("coverage_notes", ""))[:2000],
        "verification_source": str(payload.get("verification_source", "manual"))[:80]},
        patient.branch_id, patient.id, status=result, idempotency_key=payload.get("idempotency_key"))
    _audit(db, m, u, patient, "insurance.eligibility.recorded", "", emergency); db.commit()
    return _view(row)


@router.post("/patients/{patient_id}/insurance/preauthorizations", status_code=201)
def request_preauthorization(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _ = _patient_access(db, m, u, patient_id, "patient.read", write=False)
    _need(db, m, u, "insurance.manage", patient.branch_id)
    amount = _money(payload.get("requested_amount"))
    row = _create(db, m, u, "preauthorization", {"payer": _required_text(payload, "payer"),
        "service": _required_text(payload, "service", 500), "requested_amount": str(amount),
        "reference": _required_text(payload, "reference", 100), "response": str(payload.get("response", ""))[:2000]},
        patient.branch_id, patient.id, status="pending", external_key=payload["reference"], amount=amount)
    _audit(db, m, u, patient, "insurance.preauthorization.requested", "", emergency); db.commit()
    return _view(row)


@router.post("/preauthorizations/{preauth_id}/decision")
def decide_preauthorization(preauth_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    row = _resource(db, m, preauth_id, "preauthorization", lock=True)
    patient, emergency, _ = _patient_access(db, m, u, row.patient_id, "clinical.read", write=False)
    _need(db, m, u, "insurance.manage", patient.branch_id)
    if row.status != "pending": raise HTTPException(409, "Preauthorization is no longer pending")
    decision = payload.get("decision")
    if decision not in {"approved", "partially_approved", "denied", "more_information"}: raise HTTPException(422, "Invalid payer decision")
    approved = _money(payload.get("approved_amount")) if decision == "partially_approved" else (row.amount or Decimal("0"))
    if approved > (row.amount or Decimal("0")): raise HTTPException(422, "Approved amount exceeds request")
    data = _payload(row); data.update({"decision": decision, "approved_amount": str(approved),
        "decided_at": NOW().isoformat(), "payer_reference": str(payload.get("payer_reference", ""))[:100]})
    row.encrypted_payload=encrypt(data); row.status=decision; row.updated_by=u.id
    _audit(db,m,u,patient,"insurance.preauthorization.decision","",emergency); db.commit()
    return _view(row)


@router.post("/patients/{patient_id}/insurance/claims", status_code=201)
def submit_claim(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _ = _patient_access(db, m, u, patient_id, "clinical.read", write=False)
    _need(db, m, u, "insurance.manage", patient.branch_id)
    amount = _money(payload.get("amount"))
    row = _create(db, m, u, "insurance_claim", {"payer": _required_text(payload, "payer"),
        "claim_number": _required_text(payload, "claim_number", 100), "invoice_id": payload.get("invoice_id"),
        "submitted_at": NOW().isoformat(), "settled_amount": "0.00", "adjustment_reason": ""},
        patient.branch_id, patient.id, status="submitted", external_key=_required_text(payload, "claim_number", 100),
        amount=amount, currency=str(payload.get("currency", "KES")).upper(),
        idempotency_key=payload.get("idempotency_key"))
    _audit(db,m,u,patient,"insurance.claim.submitted","",emergency);db.commit()
    return _view(row)


@router.post("/insurance/claims/{claim_id}/settle")
def settle_claim(claim_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    claim = _resource(db, m, claim_id, "insurance_claim", lock=True)
    patient, emergency, _ = _patient_access(db, m, u, claim.patient_id, "clinical.read", write=False)
    _need(db, m, u, "insurance.manage", patient.branch_id)
    amount = _money(payload.get("settled_amount"))
    data = _payload(claim); already = Decimal(data.get("settled_amount", "0"))
    if amount + already > (claim.amount or Decimal("0")): raise HTTPException(422, "Settlement exceeds claim value")
    data.update({"settled_amount": str(already + amount), "settlement_reference": _required_text(payload, "settlement_reference", 100),
        "settled_at": NOW().isoformat(), "adjustment_reason": str(payload.get("adjustment_reason", ""))[:1000]})
    claim.encrypted_payload=encrypt(data); claim.status="settled" if already+amount==(claim.amount or Decimal("0")) else "partially_settled"
    claim.updated_by=u.id
    _create(db,m,u,"settlement",{"claim_id":claim.id,"settlement_reference":data["settlement_reference"],
        "amount":str(amount),"settled_at":data["settled_at"]},patient.branch_id,patient.id,
        status="posted",external_key=data["settlement_reference"],amount=amount,currency=claim.currency)
    _audit(db,m,u,patient,"insurance.claim.settled","",emergency);db.commit()
    return _view(claim)


# ---- Pharmacy and laboratory integration queue ----

def _integration_job(kind, patient_id, payload, m, u, db):
    patient, emergency, _ = _patient_access(db,m,u,patient_id,"clinical.read",write=False)
    if kind == "pharmacy_job": _need(db,m,u,"pharmacy.manage",patient.branch_id)
    else: _need(db,m,u,"lab.manage",patient.branch_id)
    order_id = payload.get("doctor_order_id")
    if order_id:
        order = _resource(db,m,int(order_id),"doctor_order")
        if order.patient_id != patient.id: raise HTTPException(404,"Doctor order not found")
    row = _create(db,m,u,kind,{"doctor_order_id":order_id,"request":payload.get("request",{}),
        "integration_status":"queued","provider_reference":"","response":None,
        "queued_at":NOW().isoformat()},patient.branch_id,patient.id,status="queued",
        idempotency_key=payload.get("idempotency_key"))
    _audit(db,m,u,patient,f"{kind}.queued","",emergency);db.commit()
    return _view(row)


@router.post("/patients/{patient_id}/pharmacy/dispense", status_code=201)
def pharmacy_dispense(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    return _integration_job("pharmacy_job",patient_id,payload,m,u,db)


@router.post("/patients/{patient_id}/laboratory/orders", status_code=201)
def laboratory_order(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    return _integration_job("laboratory_job",patient_id,payload,m,u,db)


@router.post("/integrations/jobs/{job_id}/result")
def integration_result(job_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    row = _resource(db,m,job_id)
    if row.resource_type not in {"pharmacy_job","laboratory_job","integration_job"}: raise HTTPException(404,"Integration job not found")
    patient, emergency, _ = _patient_access(db,m,u,row.patient_id,"clinical.write",write=True)
    action = "pharmacy.manage" if row.resource_type=="pharmacy_job" else "lab.manage"
    _need(db,m,u,action,patient.branch_id)
    if row.status not in {"queued","processing"}: raise HTTPException(409,"Integration job is not awaiting a result")
    data=_payload(row);data.update({"integration_status":"completed","provider_reference":str(payload.get("provider_reference",""))[:120],
        "response":payload.get("response",{}),"completed_at":NOW().isoformat()})
    row.encrypted_payload=encrypt(data);row.status="completed";row.updated_by=u.id
    _audit(db,m,u,patient,"integration.result.recorded","",emergency);db.commit()
    return _view(row)


# ---- Emergency department and theatre ----

@router.post("/patients/{patient_id}/emergency/triage", status_code=201)
def emergency_triage(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _ = _patient_access(db,m,u,patient_id,"clinical.write",write=True)
    _need(db,m,u,"emergency.manage",patient.branch_id)
    acuity=payload.get("acuity")
    if acuity not in {1,2,3,4,5}: raise HTTPException(422,"Acuity must be 1 (highest) to 5 (lowest)")
    row=_create(db,m,u,"emergency_visit",{"arrived_at":NOW().isoformat(),"acuity":acuity,
        "chief_complaint":_required_text(payload,"chief_complaint",1000),
        "triage_observations":payload.get("observations",{}),"triaged_by":u.id},
        patient.branch_id,patient.id,status="waiting",idempotency_key=payload.get("idempotency_key"))
    _audit(db,m,u,patient,"emergency.triaged","",emergency)
    _event(db,m,u,patient.id,patient.branch_id,"emergency.triaged",{"visit_id":row.id,"acuity":acuity},row.id)
    db.commit();return _view(row)


@router.post("/emergency/{visit_id}/status")
def update_emergency(visit_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    row=_resource(db,m,visit_id,"emergency_visit",lock=True)
    patient, emergency, _=_patient_access(db,m,u,row.patient_id,"clinical.write",write=True)
    _need(db,m,u,"emergency.manage",patient.branch_id)
    if row.status in {"discharged","admitted","transferred"}:raise HTTPException(409,"Emergency visit is closed")
    status=payload.get("status")
    if status not in {"waiting","in_treatment","admitted","transferred","discharged"}:raise HTTPException(422,"Invalid emergency status")
    data=_payload(row);data.update({"status_changed_at":NOW().isoformat(),"status_changed_by":u.id,
        "disposition":str(payload.get("disposition",""))[:1000]})
    row.encrypted_payload=encrypt(data);row.status=status;row.updated_by=u.id
    _audit(db,m,u,patient,"emergency.status.changed","",emergency);db.commit();return _view(row)


@router.post("/theatres", status_code=201)
def create_theatre(payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    branch=payload.get("branch_id");_need(db,m,u,"theatre.manage",branch)
    row=_create(db,m,u,"theatre",{"name":_required_text(payload,"name"),
        "code":_required_text(payload,"code",40),"capacity":int(payload.get("capacity",1))},
        branch,status="available",external_key=str(payload["code"]))
    db.commit();return _view(row)


@router.post("/patients/{patient_id}/procedures", status_code=201)
def schedule_procedure(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _=_patient_access(db,m,u,patient_id,"clinical.write",write=True)
    _need(db,m,u,"theatre.manage",patient.branch_id)
    theatre=_resource(db,m,int(payload.get("theatre_id",0)),"theatre",lock=True)
    if theatre.status!="available":raise HTTPException(409,"Theatre is not available")
    starts=str(payload.get("starts_at",""));ends=str(payload.get("ends_at",""))
    try:
        start=datetime.fromisoformat(starts.replace("Z","+00:00"));end=datetime.fromisoformat(ends.replace("Z","+00:00"))
        if start.tzinfo is None or end.tzinfo is None or end<=start:raise ValueError()
    except Exception:raise HTTPException(422,"Procedure times must be timezone-aware and end after start")
    conflicts=db.query(HealthcareResource).filter_by(organization_id=m.organization_id,resource_type="procedure",parent_id=theatre.id,status="scheduled").all()
    for conflict in conflicts:
        d=_payload(conflict)
        cs=datetime.fromisoformat(d["starts_at"].replace("Z","+00:00"));ce=datetime.fromisoformat(d["ends_at"].replace("Z","+00:00"))
        if start<ce and end>cs:raise HTTPException(409,"Theatre has an overlapping scheduled procedure")
    row=_create(db,m,u,"procedure",{"name":_required_text(payload,"name"),
        "starts_at":start.isoformat(),"ends_at":end.isoformat(),"surgeon_user_id":payload.get("surgeon_user_id"),
        "anaesthesia_plan":str(payload.get("anaesthesia_plan",""))[:2000]},
        patient.branch_id,patient.id,parent_id=theatre.id,status="scheduled",idempotency_key=payload.get("idempotency_key"))
    _audit(db,m,u,patient,"theatre.procedure.scheduled","",emergency)
    _event(db,m,u,patient.id,patient.branch_id,"procedure.scheduled",{"procedure_id":row.id,"theatre_id":theatre.id},row.id)
    db.commit();return _view(row)


@router.post("/procedures/{procedure_id}/complete")
def complete_procedure(procedure_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    row=_resource(db,m,procedure_id,"procedure",lock=True)
    patient, emergency, _=_patient_access(db,m,u,row.patient_id,"clinical.write",write=True)
    _need(db,m,u,"theatre.manage",patient.branch_id)
    if row.status!="scheduled":raise HTTPException(409,"Procedure is not scheduled")
    data=_payload(row);data.update({"operative_note":str(payload.get("operative_note",""))[:8000],
        "completed_at":NOW().isoformat(),"completed_by":u.id})
    row.encrypted_payload=encrypt(data);row.status="completed";row.updated_by=u.id
    _audit(db,m,u,patient,"theatre.procedure.completed","",emergency);db.commit();return _view(row)


# ---- Clinical documents, privacy monitoring, retention and recovery ----

@router.post("/patients/{patient_id}/documents", status_code=201)
def add_clinical_document(patient_id: int, payload: dict, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _=_patient_access(db,m,u,patient_id,"clinical.write",write=True)
    _need(db,m,u,"documents.manage",patient.branch_id)
    mime=str(payload.get("mime_type","application/octet-stream"))
    if mime not in {"application/pdf","image/jpeg","image/png","text/plain","application/dicom"}:
        raise HTTPException(422,"Unsupported clinical document MIME type")
    content=str(payload.get("content_base64",""))
    if not content or len(content)>8_000_000:raise HTTPException(422,"Document content is required and limited to 6 MiB encoded")
    row=_create(db,m,u,"clinical_document",{"title":_required_text(payload,"title"),
        "mime_type":mime,"content_base64":content,"sha256":str(payload.get("sha256",""))[:64],
        "document_type":str(payload.get("document_type","clinical"))[:60],"uploaded_at":NOW().isoformat()},
        patient.branch_id,patient.id,status="stored",idempotency_key=payload.get("idempotency_key"))
    _audit(db,m,u,patient,"clinical.document.created","",emergency);db.commit();return _view(row)


@router.get("/patients/{patient_id}/documents")
def list_clinical_documents(patient_id: int, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _=_patient_access(db,m,u,patient_id,"clinical.read",write=False)
    rows=db.query(HealthcareResource).filter_by(organization_id=m.organization_id,patient_id=patient.id,resource_type="clinical_document").all()
    _audit(db,m,u,patient,"clinical.documents.listed","",emergency);db.commit()
    return [{"id":x.id,"status":x.status,"title":_payload(x)["title"],"mime_type":_payload(x)["mime_type"],
        "document_type":_payload(x)["document_type"],"uploaded_at":_payload(x)["uploaded_at"]} for x in rows]


@router.get("/privacy/monitor")
def privacy_monitor(branch_id: str, since_hours: int=Query(24,ge=1,le=720),
                    m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    _need(db,m,u,"privacy.monitor",branch_id)
    from datetime import timedelta
    cutoff=NOW()-timedelta(hours=since_hours)
    audits=db.query(HealthcareAccessAudit).filter_by(organization_id=m.organization_id).filter(
        HealthcareAccessAudit.created_at>=cutoff).all()
    patient_branches={x.id:x.branch_id for x in db.query(HealthcarePatient).filter_by(
        organization_id=m.organization_id).all()}
    audits=[x for x in audits if x.patient_id in patient_branches
        and can_access_branch(m,patient_branches[x.patient_id])]
    sessions=db.query(HealthcareBreakGlassSession).filter_by(
        organization_id=m.organization_id,ended_at=None).all()
    active=[x for x in sessions if x.expires_at>NOW() and x.patient_id in patient_branches
        and can_access_branch(m,patient_branches[x.patient_id])]
    return {"window_hours":since_hours,"access_events":len(audits),
        "emergency_access_events":sum(1 for x in audits if x.emergency),
        "active_break_glass_sessions":[{"id":x.id,"patient_id":x.patient_id,"user_id":x.user_id,
            "justification":x.justification,"expires_at":x.expires_at.isoformat()} for x in active]}


@router.put("/retention/policy")
def set_retention_policy(payload: dict, branch_id: str, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    _need(db,m,u,"retention.manage",branch_id)
    years=payload.get("clinical_record_years")
    if not isinstance(years,int) or years<7 or years>100:
        raise HTTPException(422,"Clinical retention must be 7–100 years; verify local statutory policy")
    prior=db.query(HealthcareResource).filter_by(organization_id=m.organization_id,
        branch_id=branch_id,resource_type="retention_policy",external_key=f"policy:{branch_id}").with_for_update().first()
    policy={"clinical_record_years":years,"legal_hold":bool(payload.get("legal_hold",True)),
        "reviewed_by":u.id,"reviewed_at":NOW().isoformat(),"note":str(payload.get("note",""))[:1000]}
    if prior:
        prior.encrypted_payload=encrypt(policy);prior.updated_by=u.id;prior.updated_at=NOW();row=prior
    else:
        row=_create(db,m,u,"retention_policy",policy,branch_id,status="active",external_key=f"policy:{branch_id}")
    db.commit()
    return _view(row)


@router.post("/recovery/drills", status_code=201)
def record_recovery_drill(payload: dict, branch_id: str, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    _need(db,m,u,"recovery.manage",branch_id)
    rpo=int(payload.get("rpo_minutes",-1));rto=int(payload.get("rto_minutes",-1))
    if not 0<=rpo<=10080 or not 0<=rto<=10080:raise HTTPException(422,"RPO/RTO must be between 0 and 10080 minutes")
    status=payload.get("status")
    if status not in {"passed","failed","partial"}:raise HTTPException(422,"Recovery drill status must be passed, failed or partial")
    if status=="passed" and not payload.get("restore_verified",False):raise HTTPException(422,"A passed recovery drill requires a verified restore")\n    row=_create(db,m,u,"recovery_drill",{"drill_date":NOW().isoformat(),"status":status,
        "rpo_minutes":rpo,"rto_minutes":rto,"backup_reference":_required_text(payload,"backup_reference",180),
        "restore_verified":bool(payload.get("restore_verified",False)),
        "notes":str(payload.get("notes",""))[:2000],"performed_by":u.id},
        branch_id,status=status)
    db.commit();return _view(row)


@router.get("/dashboard")
def hospital_dashboard(branch_id: str, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    _need(db,m,u,"admissions.manage",branch_id)
    rows=db.query(HealthcareResource).filter_by(organization_id=m.organization_id,branch_id=branch_id).all()
    count=lambda kind,status=None:sum(1 for x in rows if x.resource_type==kind and (status is None or x.status==status))
    return {"branch_id":branch_id,"beds":{"total":count("bed"),"available":count("bed","available"),"occupied":count("bed","occupied")},
        "active_admissions":count("admission","admitted"),"pending_nursing_tasks":count("nursing_task","pending"),
        "pending_doctor_orders":count("doctor_order","pending"),"emergency_waiting":count("emergency_visit","waiting"),
        "pending_lab_jobs":count("laboratory_job","queued"),"pending_pharmacy_jobs":count("pharmacy_job","queued"),
        "unpaid_invoices":count("invoice","issued")}


@router.get("/patients/{patient_id}/resources")
def patient_resources(patient_id: int, resource_type: str, m=Depends(active_membership), u: User=Depends(current_user), db: Session=Depends(get_db)):
    patient, emergency, _=_patient_access(db,m,u,patient_id,"clinical.read",write=False)
    if resource_type not in RESOURCE_TYPES:raise HTTPException(422,"Unsupported resource_type")
    rows=db.query(HealthcareResource).filter_by(organization_id=m.organization_id,patient_id=patient.id,resource_type=resource_type).order_by(HealthcareResource.id.desc()).all()
    _audit(db,m,u,patient,f"clinical.{resource_type}.listed","",emergency);db.commit()
    return [_view(x) for x in rows]
