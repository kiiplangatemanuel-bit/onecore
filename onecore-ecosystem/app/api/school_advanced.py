"""Advanced School workflows built on tenant-scoped OneCore records.

The generic Record store is used deliberately so these workflows can be deployed
without altering the existing academic foundation or its migration chain.
Sensitive portal reads are always resolved through explicit guardian/teacher links.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Record, AuditEvent, User, SchoolClass, SchoolLearner, SchoolAssessment, SchoolMark, SchoolEnrollmentHistory
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, can_access_branch

router = APIRouter(prefix="/api/v1", tags=["school-advanced"])
MODULE = "school_advanced"


def _rows(db: Session, m, kind: str):
    return db.query(Record).filter_by(
        organization_id=m.organization_id, module_key=MODULE, record_type=kind
    ).order_by(Record.id.asc()).all()


def _visible_rows(db: Session, m, kind: str):
    return [x for x in _rows(db,m,kind)
            if x.branch_id is None or can_access_branch(m,x.branch_id)]


def _get(db: Session, m, kind: str, record_id: int, branch_field: str = "branch_id"):
    row = db.query(Record).filter_by(
        id=record_id, organization_id=m.organization_id,
        module_key=MODULE, record_type=kind
    ).first()
    branch_id = ((row.data or {}).get(branch_field) or row.branch_id) if row else None
    if not row or (branch_id is not None and not can_access_branch(m, branch_id)):
        raise HTTPException(404, f"{kind.replace('_', ' ').title()} not found")
    return row


def _create(db, m, user, kind, data):
    payload = dict(data)
    branch_id = payload.get("branch_id")
    if branch_id is None and payload.get("learner_id"):
        learner = db.query(SchoolLearner).filter_by(
            id=int(payload["learner_id"]), organization_id=m.organization_id
        ).first()
        if learner:
            branch_id = learner.branch_id
    if branch_id is None and payload.get("class_id"):
        cls = db.query(SchoolClass).filter_by(
            id=int(payload["class_id"]), organization_id=m.organization_id
        ).first()
        if cls:
            branch_id = cls.branch_id
    if branch_id is not None and not can_access_branch(m, branch_id):
        raise HTTPException(403, "Branch is outside your access scope")
    if branch_id is not None:
        payload["branch_id"] = str(branch_id)
    row = Record(organization_id=m.organization_id, module_key=MODULE,
                 record_type=kind, data=payload, branch_id=str(branch_id) if branch_id else None,
                 created_by=user.id)
    db.add(row)
    db.flush()
    return row


def _audit(db, m, user, action, kind, row_id, detail=""):
    db.add(AuditEvent(organization_id=m.organization_id, actor_user_id=user.id,
                      action=action, resource_type=kind, resource_id=str(row_id),
                      detail=str(detail)[:1000]))


def _commit(db):
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _data(row):
    return {"id": row.id, **(row.data or {}), "created_at": row.created_at.isoformat()}


class RankingConfigIn(BaseModel):
    academic_year: int = Field(ge=2000, le=2200)
    class_id: int | None = Field(default=None, gt=0)
    subject_id: int | None = Field(default=None, gt=0)
    grouping: str = Field(default="class", pattern=r"^(class|stream|grade|subject|whole_school)$")
    ranking_method: str = Field(default="competition", pattern=r"^(competition|dense|ordinal)$")
    tie_breakers: list[str] = Field(default_factory=list, max_length=8)
    include_inactive: bool = False


class ExamTimetableIn(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    academic_year: int = Field(ge=2000, le=2200)
    term: str = Field(min_length=1, max_length=40)
    class_id: int = Field(gt=0)
    branch_id: str | None = Field(default=None, max_length=36)
    sessions: list[dict[str, Any]] = Field(min_length=1, max_length=300)


class ExamSessionIn(BaseModel):
    timetable_id: int = Field(gt=0)
    subject_id: int = Field(gt=0)
    exam_date: date
    starts_at: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    ends_at: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    venue: str = Field(min_length=1, max_length=120)
    invigilators: list[int] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def valid_time(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Exam session must end after it starts")
        return self


class ModerationIn(BaseModel):
    assessment_id: int = Field(gt=0)
    decision: str = Field(pattern=r"^(approve|return_for_revision)$")
    reason: str = Field(default="", max_length=1000)
    mark_ids: list[int] = Field(default_factory=list, max_length=2000)


class ReportCardDecisionIn(BaseModel):
    decision: str = Field(pattern=r"^(approve|reject|publish)$")
    reason: str = Field(default="", max_length=1000)


class CurriculumNodeIn(BaseModel):
    academic_year: int = Field(ge=2000, le=2200)
    grade: str = Field(min_length=1, max_length=40)
    learning_area: str = Field(min_length=2, max_length=120)
    strand: str = Field(min_length=2, max_length=160)
    sub_strand: str = Field(default="", max_length=160)
    outcome_code: str = Field(min_length=2, max_length=60)
    outcome: str = Field(min_length=5, max_length=2000)
    indicators: list[str] = Field(default_factory=list, max_length=40)


class CompetencyIn(BaseModel):
    learner_id: int = Field(gt=0)
    curriculum_node_id: int = Field(gt=0)
    level: str = Field(pattern=r"^(emerging|approaching|meeting|exceeding)$")
    evidence: str = Field(default="", max_length=2000)
    observed_on: date


class BulkPromotionIn(BaseModel):
    source_class_id: int = Field(gt=0)
    target_class_id: int = Field(gt=0)
    effective_date: date
    learner_ids: list[int] = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=5, max_length=500)
    change_type: str = Field(default="promotion", pattern=r"^(promotion|transfer)$")
    skip_ineligible: bool = False

    @model_validator(mode="after")
    def unique_learners(self):
        if len(self.learner_ids) != len(set(self.learner_ids)):
            raise ValueError("Learner IDs must be unique")
        return self


class FeeChargeIn(BaseModel):
    learner_id: int = Field(gt=0)
    academic_year: int = Field(ge=2000, le=2200)
    term: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=2, max_length=180)
    amount: Decimal = Field(gt=0, le=Decimal("999999999999"), decimal_places=2)
    due_date: date
    reference: str = Field(min_length=2, max_length=80)


class FeePaymentIn(BaseModel):
    learner_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, le=Decimal("999999999999"), decimal_places=2)
    payment_date: date
    method: str = Field(pattern=r"^(cash|bank|mpesa|card|other)$")
    reference: str = Field(min_length=3, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=100)


class FeeAllocationIn(BaseModel):
    allocations: list[dict[str, Any]] = Field(min_length=1, max_length=200)


class GuardianLinkIn(BaseModel):
    guardian_user_id: int = Field(gt=0)
    learner_id: int = Field(gt=0)
    relationship: str = Field(min_length=2, max_length=40)
    permissions: list[str] = Field(default_factory=lambda: ["academic", "fees", "attendance"],
                                    max_length=10)


class StaffProfileIn(BaseModel):
    user_id: int = Field(gt=0)
    staff_type: str = Field(pattern=r"^(teacher|administrator|support|other)$")
    employee_number: str = Field(min_length=2, max_length=40)
    branch_id: str | None = Field(default=None, max_length=36)
    class_ids: list[int] = Field(default_factory=list, max_length=100)
    subject_ids: list[int] = Field(default_factory=list, max_length=100)


def _learner(db, m, learner_id):
    learner = db.query(SchoolLearner).filter_by(
        id=learner_id, organization_id=m.organization_id
    ).first()
    if not learner:
        raise HTTPException(404, "Learner not found")
    if learner.branch_id and not can_access_branch(m, learner.branch_id):
        raise HTTPException(404, "Learner not found")
    return learner


def _class(db, m, class_id):
    row = db.query(SchoolClass).filter_by(id=class_id, organization_id=m.organization_id).first()
    if not row or not can_access_branch(m, row.branch_id):
        raise HTTPException(404, "Class not found")
    return row


@router.get("/school/advanced/ranking-config")
def list_ranking_configs(m=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(m, "read")
    return [_data(x) for x in _rows(db, m, "ranking_config") if can_access_branch(m, x.branch_id)]


@router.put("/school/advanced/ranking-config")
def save_ranking_config(payload: RankingConfigIn, m=Depends(active_membership),
                        u: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(m, "manage")
    if payload.class_id:
        _class(db, m, payload.class_id)
    rows = _rows(db, m, "ranking_config")
    data = payload.model_dump(mode="json")
    existing = next((x for x in rows if x.data.get("academic_year")==payload.academic_year
                     and x.data.get("class_id")==payload.class_id
                     and x.data.get("subject_id")==payload.subject_id), None)
    if existing:
        existing.data = data
        row = existing
    else:
        row = _create(db, m, u, "ranking_config", data)
    _audit(db,m,u,"school.ranking.configured","ranking_config",row.id)
    _commit(db)
    return _data(row)



@router.get("/school/rankings")
def school_rankings(academic_year:int,class_id:int|None=None,subject_id:int|None=None,
                    m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    configs=_rows(db,m,"ranking_config")
    config=next((x.data for x in configs if x.data.get("academic_year")==academic_year
                 and x.data.get("class_id")==class_id and x.data.get("subject_id")==subject_id),{})
    q=db.query(SchoolAssessment).filter_by(organization_id=m.organization_id,academic_year=academic_year,status="published")
    if class_id is not None: q=q.filter(SchoolAssessment.class_id==class_id)
    if subject_id is not None: q=q.filter(SchoolAssessment.subject_id==subject_id)
    visible_class_ids={x.id for x in db.query(SchoolClass).filter_by(
        organization_id=m.organization_id).all() if can_access_branch(m,x.branch_id)}
    q=q.filter(SchoolAssessment.class_id.in_(visible_class_ids or {-1}))
    assessments=q.all()
    assessment_ids=[x.id for x in assessments]
    by_id={x.id:x for x in assessments}
    marks=db.query(SchoolMark).filter(SchoolMark.organization_id==m.organization_id,
        SchoolMark.assessment_id.in_(assessment_ids)).all()
    totals={}
    for mark in marks:
        assessment=by_id[mark.assessment_id]
        key=mark.learner_id
        entry=totals.setdefault(key,{"weighted_score":Decimal("0"),"weight":Decimal("0"),"class_id":assessment.class_id})
        weight=Decimal(assessment.weight)
        entry["weighted_score"]+=(Decimal(mark.score)/Decimal(assessment.maximum_score))*Decimal("100")*weight
        entry["weight"]+=weight
    results=[]
    for learner_id,entry in totals.items():
        learner=_learner(db,m,learner_id)
        if class_id is not None and learner.class_id!=class_id: continue
        if not entry["weight"]: continue
        results.append({"learner_id":learner_id,"admission_number":learner.admission_number,
            "learner_name":learner.first_name+" "+learner.last_name,
            "class_id":learner.class_id,"average_percent":str((entry["weighted_score"]/entry["weight"]).quantize(Decimal("0.01")))})
    results.sort(key=lambda x:Decimal(x["average_percent"]),reverse=True)
    method=config.get("ranking_method","competition")
    previous=None; rank=0
    for index,item in enumerate(results,1):
        score=Decimal(item["average_percent"])
        if score!=previous: rank=index if method in ("competition","ordinal") else (rank+1)
        item["rank"]=index if method=="ordinal" else rank
        previous=score
    return {"academic_year":academic_year,"configuration":config,"rankings":results}


@router.post("/school/exam-timetables", status_code=201)
def create_exam_timetable(payload: ExamTimetableIn, m=Depends(active_membership),
                          u: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(m, "create")
    cls = _class(db,m,payload.class_id)
    if payload.branch_id and payload.branch_id != cls.branch_id:
        raise HTTPException(422, "Timetable branch must match the class branch")
    # Validate every slot and reject overlapping sessions for the same class/venue.
    normalized=[]
    for slot in payload.sessions:
        try:
            d=date.fromisoformat(str(slot["exam_date"]))
            start=str(slot["starts_at"]); end=str(slot["ends_at"])
            if len(start)!=5 or len(end)!=5 or end<=start: raise ValueError()
            subject_id=int(slot["subject_id"])
        except (KeyError,ValueError,TypeError):
            raise HTTPException(422,"Each session needs a valid date, subject_id, starts_at and ends_at")
        for other in normalized:
            if other["exam_date"]==d.isoformat() and max(start,other["starts_at"]) < min(end,other["ends_at"]):
                raise HTTPException(422,"Exam sessions in one timetable cannot overlap")
        normalized.append({**slot,"exam_date":d.isoformat(),"starts_at":start,"ends_at":end,"subject_id":subject_id})
    row=_create(db,m,u,"exam_timetable",{**payload.model_dump(mode="json"),"sessions":normalized,"status":"draft"})
    _audit(db,m,u,"school.exam_timetable.created","exam_timetable",row.id)
    _commit(db)
    return _data(row)


@router.get("/school/exam-timetables")
def list_exam_timetables(m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    return [_data(x) for x in _rows(db,m,"exam_timetable") if can_access_branch(m,x.branch_id)]


@router.post("/school/exam-sessions",status_code=201)
def create_exam_session(payload:ExamSessionIn,m=Depends(active_membership),
                        u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"create")
    timetable=_get(db,m,"exam_timetable",payload.timetable_id)
    if timetable.data.get("status")!="draft":
        raise HTTPException(409,"Sessions can only be added to a draft timetable")
    start=payload.starts_at; end=payload.ends_at
    for s in timetable.data.get("sessions",[]):
        if s.get("exam_date")==payload.exam_date.isoformat() and max(start,s["starts_at"])<min(end,s["ends_at"]):
            raise HTTPException(409,"Session overlaps an existing exam")
    timetable.data={**timetable.data,"sessions":timetable.data.get("sessions",[])+[payload.model_dump(mode="json")]}
    _audit(db,m,u,"school.exam_session.created","exam_timetable",timetable.id)
    _commit(db)
    return _data(timetable)


@router.post("/school/exam-timetables/{timetable_id}/publish")
def publish_exam_timetable(timetable_id:int,m=Depends(active_membership),
                           u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    row=_get(db,m,"exam_timetable",timetable_id)
    if not row.data.get("sessions"): raise HTTPException(409,"Cannot publish an empty timetable")
    row.data={**row.data,"status":"published","published_by":u.id,"published_at":datetime.now(timezone.utc).isoformat()}
    _audit(db,m,u,"school.exam_timetable.published","exam_timetable",row.id)
    _commit(db)
    return _data(row)


@router.put("/school/exam-timetables/{timetable_id}/sessions/{session_index}/seating")
def save_seating_plan(timetable_id:int,session_index:int,payload:list[dict[str,Any]],m=Depends(active_membership),
                      u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    timetable=_get(db,m,"exam_timetable",timetable_id)
    sessions=list(timetable.data.get("sessions",[]))
    if session_index<0 or session_index>=len(sessions): raise HTTPException(404,"Exam session not found")
    seats=[str(x.get("seat","")).strip() for x in payload]
    learners=[int(x.get("learner_id",0)) for x in payload]
    if not payload or any(not x for x in seats) or len(seats)!=len(set(seats)) or len(learners)!=len(set(learners)) or 0 in learners:
        raise HTTPException(422,"Seating plan requires unique learner IDs and seat labels")
    timetable_class_id=int(timetable.data.get("class_id",0))
    for learner_id in learners:
        learner=_learner(db,m,learner_id)
        if learner.status!="active" or learner.class_id!=timetable_class_id:
            raise HTTPException(422,"Every seated learner must be active in the timetable class")
    sessions[session_index]={**sessions[session_index],"seating_plan":payload}
    timetable.data={**timetable.data,"sessions":sessions}
    _audit(db,m,u,"school.exam.seating_saved","exam_timetable",timetable.id)
    _commit(db)
    return _data(timetable)


@router.post("/school/assessments/{assessment_id}/moderation")
def moderate_assessment(assessment_id:int,payload:ModerationIn,m=Depends(active_membership),
                        u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    assessment=db.query(SchoolAssessment).filter_by(id=assessment_id,organization_id=m.organization_id).first()
    if not assessment: raise HTTPException(404,"Assessment not found")
    assessment_class=db.query(SchoolClass).filter_by(
        id=assessment.class_id,organization_id=m.organization_id).first()
    if not assessment_class or not can_access_branch(m,assessment_class.branch_id):
        raise HTTPException(404,"Assessment not found")
    if payload.decision=="return_for_revision" and len(payload.reason.strip())<5:
        raise HTTPException(422,"A reason is required when returning marks")
    marks_q=db.query(SchoolMark).filter_by(assessment_id=assessment_id,organization_id=m.organization_id)
    if payload.mark_ids: marks_q=marks_q.filter(SchoolMark.id.in_(payload.mark_ids))
    marks=marks_q.all()
    if not marks: raise HTTPException(409,"No marks are available for moderation")
    row=_create(db,m,u,"moderation_decision",{"assessment_id":assessment_id,"decision":payload.decision,
        "reason":payload.reason.strip(),"mark_ids":[x.id for x in marks],"moderator_id":u.id,
        "created_at":datetime.now(timezone.utc).isoformat()})
    _audit(db,m,u,"school.marks.moderated","moderation_decision",row.id)
    _commit(db)
    return _data(row)


@router.post("/school/curriculum/nodes",status_code=201)
def create_curriculum_node(payload:CurriculumNodeIn,m=Depends(active_membership),
                           u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"create")
    dup=next((x for x in _rows(db,m,"curriculum_node") if x.data.get("academic_year")==payload.academic_year
              and x.data.get("grade")==payload.grade and x.data.get("outcome_code")==payload.outcome_code),None)
    if dup: raise HTTPException(409,"Outcome code already exists for this grade and year")
    row=_create(db,m,u,"curriculum_node",payload.model_dump(mode="json"))
    _audit(db,m,u,"school.curriculum.created","curriculum_node",row.id)
    _commit(db)
    return _data(row)


@router.get("/school/curriculum/nodes")
def list_curriculum_nodes(academic_year:int|None=None,grade:str|None=None,m=Depends(active_membership),
                          db:Session=Depends(get_db)):
    require_permission(m,"read")
    rows=_rows(db,m,"curriculum_node")
    return [_data(x) for x in rows if (academic_year is None or x.data.get("academic_year")==academic_year)
            and (grade is None or x.data.get("grade")==grade)]


@router.post("/school/competencies",status_code=201)
def record_competency(payload:CompetencyIn,m=Depends(active_membership),
                      u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"create")
    _learner(db,m,payload.learner_id)
    _get(db,m,"curriculum_node",payload.curriculum_node_id)
    row=_create(db,m,u,"competency",payload.model_dump(mode="json"))
    _audit(db,m,u,"school.competency.recorded","competency",row.id)
    _commit(db)
    return _data(row)


@router.get("/school/learners/{learner_id}/competencies")
def learner_competencies(learner_id:int,m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    _learner(db,m,learner_id)
    return [_data(x) for x in _rows(db,m,"competency") if x.data.get("learner_id")==learner_id]


@router.post("/school/promotions/bulk")
def bulk_promote(payload:BulkPromotionIn,m=Depends(active_membership),
                 u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    source=_class(db,m,payload.source_class_id); target=_class(db,m,payload.target_class_id)
    if source.id==target.id: raise HTTPException(422,"Source and target classes must differ")
    if payload.change_type=="promotion" and target.academic_year<=source.academic_year:
        raise HTTPException(422,"Promotion target must be a later academic year")
    if target.academic_year<source.academic_year: raise HTTPException(422,"Cannot move learners backwards")
    learners=db.query(SchoolLearner).filter(SchoolLearner.organization_id==m.organization_id,
        SchoolLearner.id.in_(payload.learner_ids),SchoolLearner.class_id==source.id,
        SchoolLearner.status=="active").with_for_update().all()
    found={x.id for x in learners}
    missing=sorted(set(payload.learner_ids)-found)
    if missing and not payload.skip_ineligible:
        raise HTTPException(422,{"message":"Some learners are not active in the source class","learner_ids":missing})
    moved=[]
    for learner in learners:
        learner.class_id=target.id
        learner.branch_id=target.branch_id
        hist=SchoolEnrollmentHistory(organization_id=m.organization_id,learner_id=learner.id,
            from_class_id=source.id,to_class_id=target.id,
            effective_date=datetime.combine(payload.effective_date,datetime.min.time(),tzinfo=timezone.utc),
            change_type=payload.change_type,reason=payload.reason.strip(),changed_by=u.id)
        db.add(hist); db.flush()
        moved.append({"learner_id":learner.id,"history_id":hist.id})
    _audit(db,m,u,"school.learners.bulk_placement","school_learner",source.id,
           f"target_class={target.id};moved={len(moved)};skipped={len(missing)}")
    _commit(db)
    return {"moved":moved,"skipped_learner_ids":missing,"count":len(moved)}


@router.post("/school/fees/charges",status_code=201)
def create_fee_charge(payload:FeeChargeIn,m=Depends(active_membership),
                      u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"create")
    learner=_learner(db,m,payload.learner_id)
    if any(x.data.get("reference")==payload.reference for x in _rows(db,m,"fee_charge")):
        raise HTTPException(409,"Fee charge reference already exists")
    data=payload.model_dump(mode="json")
    data.update({"amount":str(payload.amount),"balance":str(payload.amount),"status":"unpaid"})
    row=_create(db,m,u,"fee_charge",data)
    _audit(db,m,u,"school.fee.charge_created","fee_charge",row.id,payload.reference)
    _commit(db)
    return _data(row)


@router.post("/school/fees/payments",status_code=201)
def record_fee_payment(payload:FeePaymentIn,m=Depends(active_membership),
                       u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"create")
    _learner(db,m,payload.learner_id)
    existing=next((x for x in _rows(db,m,"fee_payment") if x.data.get("idempotency_key")==payload.idempotency_key),None)
    if existing:
        if int(existing.data.get("learner_id",0))!=payload.learner_id:
            raise HTTPException(409,"Payment idempotency key is already used for another learner")
        if existing.branch_id is not None and not can_access_branch(m,existing.branch_id):
            raise HTTPException(404,"Payment not found")
        return _data(existing)
    data=payload.model_dump(mode="json")
    data.update({"amount":str(payload.amount),"unallocated":str(payload.amount),"allocations":[]})
    row=_create(db,m,u,"fee_payment",data)
    _audit(db,m,u,"school.fee.payment_received","fee_payment",row.id,payload.reference)
    _commit(db)
    return _data(row)


@router.post("/school/fees/payments/{payment_id}/allocate")
def allocate_fee_payment(payment_id:int,payload:FeeAllocationIn,m=Depends(active_membership),
                         u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    payment=_get(db,m,"fee_payment",payment_id)
    if payment.data.get("allocations"): raise HTTPException(409,"Payment has already been allocated")
    try: available=Decimal(payment.data["unallocated"])
    except (InvalidOperation,KeyError): raise HTTPException(409,"Payment balance is invalid")
    charges={x.id:x for x in _rows(db,m,"fee_charge") if x.data.get("learner_id")==payment.data.get("learner_id")}
    allocations=[]; total=Decimal("0")
    requested={}
    for item in payload.allocations:
        try:
            charge_id=int(item["charge_id"]); amount=Decimal(str(item["amount"]))
        except (KeyError,ValueError,TypeError,InvalidOperation):
            raise HTTPException(422,"Each allocation needs charge_id and a valid amount")
        if amount<=0: raise HTTPException(422,"Allocation amounts must be positive")
        requested[charge_id]=requested.get(charge_id,Decimal("0"))+amount
    for charge_id,amount in requested.items():
        charge=charges.get(charge_id)
        if not charge: raise HTTPException(422,"Allocation references an invalid charge")
        balance=Decimal(charge.data["balance"])
        if amount>balance: raise HTTPException(422,"Allocation exceeds the outstanding charge balance")
        total+=amount; allocations.append((charge,amount))
    if total>available: raise HTTPException(422,"Allocations exceed the unallocated payment amount")
    for charge,amount in allocations:
        d=dict(charge.data); d["balance"]=str(Decimal(d["balance"])-amount)
        d["status"]="paid" if Decimal(d["balance"])==0 else "partial"
        charge.data=d
    p=dict(payment.data); p["allocations"]=[{"charge_id":c.id,"amount":str(a)} for c,a in allocations]
    p["unallocated"]=str(available-total); payment.data=p
    _audit(db,m,u,"school.fee.payment_allocated","fee_payment",payment.id,f"allocated={total}")
    _commit(db)
    return {"payment":_data(payment),"allocations":p["allocations"]}


@router.get("/school/fees/learners/{learner_id}/statement")
def learner_fee_statement(learner_id:int,m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    _learner(db,m,learner_id)
    charges=[x for x in _rows(db,m,"fee_charge") if x.data.get("learner_id")==learner_id]
    payments=[x for x in _rows(db,m,"fee_payment") if x.data.get("learner_id")==learner_id]
    total_charged=sum((Decimal(x.data["amount"]) for x in charges),Decimal("0"))
    outstanding=sum((Decimal(x.data["balance"]) for x in charges),Decimal("0"))
    received=sum((Decimal(x.data["amount"]) for x in payments),Decimal("0"))
    allocated=received-sum((Decimal(x.data["unallocated"]) for x in payments),Decimal("0"))
    return {"learner_id":learner_id,"currency":"KES","charges":[_data(x) for x in charges],
            "payments":[_data(x) for x in payments],"total_charged":str(total_charged),
            "received":str(received),"allocated":str(allocated),"unallocated":str(received-allocated),
            "outstanding":str(outstanding),"arrears":[_data(x) for x in charges if x.data.get("due_date","")<date.today().isoformat() and Decimal(x.data["balance"])>0]}


@router.post("/school/guardians/links",status_code=201)
def link_guardian(payload:GuardianLinkIn,m=Depends(active_membership),
                  u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    _learner(db,m,payload.learner_id)
    guardian=db.query(User).filter_by(id=payload.guardian_user_id,is_active=True).first()
    if not guardian: raise HTTPException(404,"Guardian user account not found")
    if payload.guardian_user_id==u.id: raise HTTPException(422,"Staff cannot link themselves as a guardian")
    if not set(payload.permissions).issubset({"academic","fees","attendance","communications"}):
        raise HTTPException(422,"Unsupported guardian permission")
    duplicate=next((x for x in _rows(db,m,"guardian_link") if x.data.get("guardian_user_id")==payload.guardian_user_id
                    and x.data.get("learner_id")==payload.learner_id and x.data.get("active")),None)
    if duplicate: raise HTTPException(409,"Guardian is already linked to this learner")
    row=_create(db,m,u,"guardian_link",{**payload.model_dump(mode="json"),"active":True})
    _audit(db,m,u,"school.guardian.linked","guardian_link",row.id)
    _commit(db)
    return _data(row)


@router.get("/school/guardian/portal")
def guardian_portal(m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"read")
    links=[x for x in _rows(db,m,"guardian_link") if x.data.get("guardian_user_id")==u.id and x.data.get("active")]
    if not links: raise HTTPException(403,"No active guardian-to-learner link")
    output=[]
    for link in links:
        learner=_learner(db,m,int(link.data["learner_id"]))
        permissions=set(link.data.get("permissions",[]))
        item={"learner":{"id":learner.id,"admission_number":learner.admission_number,
                         "first_name":learner.first_name,"last_name":learner.last_name}}
        if "fees" in permissions:
            charges=[x for x in _rows(db,m,"fee_charge") if x.data.get("learner_id")==learner.id]
            item["fee_balance"]=str(sum((Decimal(x.data["balance"]) for x in charges),Decimal("0")))
        if "academic" in permissions:
            item["competencies"]=[_data(x) for x in _rows(db,m,"competency") if x.data.get("learner_id")==learner.id]
            item["report_cards"]=[_data(x) for x in _rows(db,m,"report_card") if x.data.get("learner_id")==learner.id and x.data.get("status")=="published"]
        if "attendance" in permissions:
            item["attendance"]=[_data(x) for x in _rows(db,m,"guardian_notification") if x.data.get("learner_id")==learner.id and x.data.get("category")=="attendance"]
        if "communications" in permissions:
            item["notifications"]=[_data(x) for x in _rows(db,m,"guardian_notification")
                if x.data.get("learner_id")==learner.id and u.id in x.data.get("guardian_user_ids",[])]
        output.append(item)
    return {"learners":output}


@router.post("/school/staff/profiles",status_code=201)
def create_staff_profile(payload:StaffProfileIn,m=Depends(active_membership),
                         u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    if payload.branch_id and not can_access_branch(m,payload.branch_id):
        raise HTTPException(403,"Branch is outside your access scope")
    if payload.staff_type=="teacher":
        for cid in payload.class_ids: _class(db,m,cid)
    row=_create(db,m,u,"staff_profile",payload.model_dump(mode="json"))
    _audit(db,m,u,"school.staff.profile_created","staff_profile",row.id)
    _commit(db)
    return _data(row)


@router.get("/school/teacher/portal")
def teacher_portal(m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"read")
    profiles=[x for x in _rows(db,m,"staff_profile") if x.data.get("user_id")==u.id and x.data.get("staff_type")=="teacher"]
    if not profiles: raise HTTPException(403,"No teacher profile is linked to this account")
    class_ids={cid for p in profiles for cid in p.data.get("class_ids",[])}
    classes=[_class(db,m,cid) for cid in class_ids]
    return {"classes":[{"id":x.id,"name":x.name,"stream":x.stream,"academic_year":x.academic_year} for x in classes],
            "assessments":[{"id":x.id,"title":x.title,"class_id":x.class_id,"subject_id":x.subject_id,
                            "status":x.status} for x in db.query(SchoolAssessment).filter(
                SchoolAssessment.organization_id==m.organization_id,SchoolAssessment.class_id.in_(class_ids or {-1})).all()]}



class ReportCardIn(BaseModel):
    learner_id: int = Field(gt=0)
    academic_year: int = Field(ge=2000, le=2200)
    term: str = Field(min_length=1, max_length=40)
    summary: str = Field(default="", max_length=4000)
    grades: dict[str, Any] = Field(default_factory=dict)



@router.get("/school/staff/portal")
def staff_portal(m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"read")
    profiles=[x for x in _rows(db,m,"staff_profile") if x.data.get("user_id")==u.id]
    if not profiles: raise HTTPException(403,"No staff profile is linked to this account")
    return {"profiles":[_data(x) for x in profiles],
            "pending_report_cards":sum(1 for x in _rows(db,m,"report_card") if x.data.get("status")=="submitted"),
            "pending_moderation":sum(1 for x in _rows(db,m,"moderation_decision") if x.data.get("decision")=="return_for_revision")}


@router.post("/school/report-cards",status_code=201)
def create_report_card(payload:ReportCardIn,m=Depends(active_membership),
                       u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"create")
    learner=_learner(db,m,payload.learner_id)
    duplicate=next((x for x in _rows(db,m,"report_card") if x.data.get("learner_id")==learner.id
                    and x.data.get("academic_year")==payload.academic_year
                    and x.data.get("term")==payload.term),None)
    if duplicate: raise HTTPException(409,"A report card already exists for this learner, year and term")
    row=_create(db,m,u,"report_card",{**payload.model_dump(mode="json"),"status":"draft"})
    _audit(db,m,u,"school.report_card.created","report_card",row.id)
    _commit(db)
    return _data(row)


@router.post("/school/report-cards/{report_card_id}/submit")
def submit_report_card(report_card_id:int,m=Depends(active_membership),
                       u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"create")
    row=_get(db,m,"report_card",report_card_id)
    if row.data.get("status")!="draft": raise HTTPException(409,"Only draft report cards can be submitted")
    row.data={**row.data,"status":"submitted","submitted_by":u.id,
              "submitted_at":datetime.now(timezone.utc).isoformat()}
    _audit(db,m,u,"school.report_card.submitted","report_card",row.id)
    _commit(db)
    return _data(row)


@router.post("/school/report-cards/{report_card_id}/decision")
def report_card_decision(report_card_id:int,payload:ReportCardDecisionIn,m=Depends(active_membership),
                         u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    row=_get(db,m,"report_card",report_card_id)
    data=dict(row.data)
    status=data.get("status","draft")
    if payload.decision=="approve":
        if status not in ("draft","submitted"): raise HTTPException(409,"Only draft/submitted cards can be approved")
        data.update(status="approved",approved_by=u.id,approved_at=datetime.now(timezone.utc).isoformat())
    elif payload.decision=="reject":
        if len(payload.reason.strip())<5: raise HTTPException(422,"A rejection reason is required")
        if status not in ("draft","submitted"): raise HTTPException(409,"Only draft/submitted cards can be rejected")
        data.update(status="rejected",rejection_reason=payload.reason.strip(),rejected_by=u.id)
    else:
        if status!="approved": raise HTTPException(409,"Only approved report cards can be published")
        data.update(status="published",published_by=u.id,published_at=datetime.now(timezone.utc).isoformat())
    row.data=data
    _audit(db,m,u,"school.report_card."+payload.decision,"report_card",row.id)
    _commit(db)
    return _data(row)


@router.get("/school/transcripts/{learner_id}")
def downloadable_transcript(learner_id:int,m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    learner=_learner(db,m,learner_id)
    cards=[x.data for x in _rows(db,m,"report_card") if x.data.get("learner_id")==learner_id and x.data.get("status")=="published"]
    transcript={"learner":{"admission_number":learner.admission_number,"first_name":learner.first_name,
                           "last_name":learner.last_name},"report_cards":cards}
    canonical=json.dumps(transcript,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return Response(content=canonical,media_type="application/json",
        headers={"Content-Disposition":f'attachment; filename="transcript-{learner.admission_number}.json"',
                 "X-Transcript-Algorithm":"SHA-256","X-Transcript-Digest":digest,
                 "Cache-Control":"no-store, private"})


@router.post("/school/notifications",status_code=201)
def create_guardian_notification(payload:dict[str,Any],m=Depends(active_membership),
                                 u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"create")
    learner_id=int(payload.get("learner_id",0))
    _learner(db,m,learner_id)
    message=str(payload.get("message","")).strip()
    category=str(payload.get("category","general"))
    if not message or len(message)>2000 or category not in {"academic","fees","attendance","general"}:
        raise HTTPException(422,"A valid message and notification category are required")
    links=[x for x in _rows(db,m,"guardian_link") if x.data.get("learner_id")==learner_id and x.data.get("active")]
    row=_create(db,m,u,"guardian_notification",{"learner_id":learner_id,"message":message,
        "category":category,"guardian_user_ids":[x.data["guardian_user_id"] for x in links],
        "status":"queued","created_at":datetime.now(timezone.utc).isoformat()})
    _audit(db,m,u,"school.guardian_notification.queued","guardian_notification",row.id)
    _commit(db)
    return _data(row)


@router.get("/school/dashboard")
def school_dashboard(m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    learners=[x for x in db.query(SchoolLearner).filter_by(organization_id=m.organization_id).all()
              if can_access_branch(m,x.branch_id)]
    classes=[x for x in db.query(SchoolClass).filter_by(organization_id=m.organization_id,is_active=True).all()
             if can_access_branch(m,x.branch_id)]
    class_ids={x.id for x in classes}
    assessments=db.query(SchoolAssessment).filter(
        SchoolAssessment.organization_id==m.organization_id,
        SchoolAssessment.class_id.in_(class_ids or {-1})).all()
    charges=_visible_rows(db,m,"fee_charge"); payments=_visible_rows(db,m,"fee_payment")
    total_due=sum((Decimal(x.data["balance"]) for x in charges),Decimal("0"))
    received=sum((Decimal(x.data["amount"]) for x in payments),Decimal("0"))
    published=sum(1 for x in _visible_rows(db,m,"report_card") if x.data.get("status")=="published")
    return {"learners":len(learners),"active_learners":sum(x.status=="active" for x in learners),
            "classes":len(classes),"assessments":len(assessments),"published_report_cards":published,
            "fee_charges":str(sum((Decimal(x.data["amount"]) for x in charges),Decimal("0"))),
            "fee_outstanding":str(total_due),"fee_collections":str(received),
            "fee_unallocated":str(received-sum((Decimal(x.data["amount"]) - Decimal(x.data["unallocated"]) for x in payments),Decimal("0")))}


@router.get("/school/reconciliation")
def school_reconciliation(m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    charges=_visible_rows(db,m,"fee_charge"); payments=_visible_rows(db,m,"fee_payment")
    errors=[]
    charge_total=sum((Decimal(x.data["amount"]) for x in charges),Decimal("0"))
    charge_balance=sum((Decimal(x.data["balance"]) for x in charges),Decimal("0"))
    payment_total=sum((Decimal(x.data["amount"]) for x in payments),Decimal("0"))
    unallocated=sum((Decimal(x.data["unallocated"]) for x in payments),Decimal("0"))
    allocated=payment_total-unallocated
    if charge_balance<0 or unallocated<0: errors.append("Negative fee balance detected")
    allocation_sum=sum((sum((Decimal(a["amount"]) for a in x.data.get("allocations",[])),Decimal("0")) for x in payments),Decimal("0"))
    if allocation_sum!=allocated: errors.append("Payment allocation ledger does not reconcile")
    if allocated>charge_total: errors.append("Allocated payments exceed billed charges")
    return {"status":"passed" if not errors else "failed","errors":errors,
            "charges":{"billed":str(charge_total),"outstanding":str(charge_balance)},
            "payments":{"received":str(payment_total),"allocated":str(allocated),"unallocated":str(unallocated)},
            "difference":str(payment_total-allocated-unallocated)}
