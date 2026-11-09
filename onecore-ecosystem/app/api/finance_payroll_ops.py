"""Multi-currency ledger posting/revaluation and statutory payroll remittance workflows.

FX rates are explicitly sourced and tenant-owned. Payroll remittance batches are
calculated from approved payroll snapshots and require maker/checker/payment roles.
This API records externally confirmed remittances; it does not claim to file with KRA,
NSSF, SHA or initiate bank transfers.
"""
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.authorization import can_access_branch
from app.core.database import get_db
from app.core.models import AccountingAccount, AuditEvent, Organization, Branch
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.hr_payroll_models import PayrollRun, PayrollPayslip, PayrollAccountingLink
from app.core.finance_ops_models import AccountingFxRate, AccountingFxPosting, AccountingFxRevaluation, PayrollStatutoryBatch
from app.api.routes import _accounting_make_journal, _accounting_assert_period_open

router = APIRouter(tags=["finance-fx-statutory"])
CENT = Decimal("0.01")


def money(v):
    return Decimal(str(v)).quantize(CENT, rounding=ROUND_HALF_UP)


def _payload_hash(payload):
    canonical=json.dumps(payload.model_dump(mode="json"),sort_keys=True,separators=(",",":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_finance(membership):
    if (membership.role or "").lower() not in {"org_admin","accountant"}:
        raise HTTPException(403,"Foreign-currency accounting requires an organization administrator or accountant")


def _audit(db, user, org_id, action, kind, rid, detail=""):
    db.add(AuditEvent(actor_user_id=user.id, organization_id=org_id, action=action,
                      resource_type=kind, resource_id=str(rid), detail=detail))


def _branch_or_404(db, membership, branch_id):
    if branch_id is None:
        return
    branch=db.query(Branch).filter_by(id=branch_id,organization_id=membership.organization_id,is_active=True).first()
    if not branch or not can_access_branch(membership,branch_id):
        raise HTTPException(404,"Branch not found")


def _accounts(db, org_id, ids):
    rows = db.query(AccountingAccount).filter(
        AccountingAccount.organization_id == org_id, AccountingAccount.id.in_(set(ids))
    ).all()
    result = {x.id: x for x in rows}
    if len(result) != len(set(ids)):
        raise HTTPException(404, "One or more ledger accounts were not found")
    return result


class FxRateIn(BaseModel):
    currency: str = Field(pattern="^[A-Z]{3}$")
    rate_date: date
    units_per_base: Decimal = Field(gt=0, max_digits=20, decimal_places=10)
    source: str = Field(min_length=2, max_length=80)
    reference: str = Field(default="", max_length=120)


class FxPostingIn(BaseModel):
    rate_id: int = Field(gt=0)
    entry_date: date
    foreign_amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    debit_account_id: int = Field(gt=0)
    credit_account_id: int = Field(gt=0)
    reference: str = Field(min_length=1, max_length=120)
    memo: str = Field(default="", max_length=500)
    branch_id: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def distinct_accounts(self):
        if self.debit_account_id == self.credit_account_id:
            raise ValueError("Debit and credit accounts must differ")
        return self


class FxPosition(BaseModel):
    account_id: int = Field(gt=0)
    position_type: str = Field(pattern="^(asset|liability)$")
    foreign_balance: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    carrying_base_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class FxRevaluationIn(BaseModel):
    currency: str = Field(pattern="^[A-Z]{3}$")
    valuation_date: date
    closing_rate: Decimal = Field(gt=0, max_digits=20, decimal_places=10)
    fx_gain_account_id: int = Field(gt=0)
    fx_loss_account_id: int = Field(gt=0)
    positions: list[FxPosition] = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=100)
    branch_id: str | None = None

    @model_validator(mode="after")
    def unique_positions(self):
        ids=[x.account_id for x in self.positions]
        if len(ids)!=len(set(ids)):
            raise ValueError("Each foreign-currency ledger account may appear only once per revaluation")
        return self


class StatutoryBatchIn(BaseModel):
    payroll_run_ids: list[int] = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def unique_runs(self):
        if len(self.payroll_run_ids) != len(set(self.payroll_run_ids)):
            raise ValueError("Payroll run IDs must be unique")
        return self


class StatutoryPaymentIn(BaseModel):
    payment_reference: str = Field(min_length=3, max_length=120)
    payment_date: date
    bank_account_id: int = Field(gt=0)
    paye_payable_account_id: int = Field(gt=0)
    nssf_payable_account_id: int = Field(gt=0)
    shif_payable_account_id: int = Field(gt=0)
    housing_levy_payable_account_id: int = Field(gt=0)
    pension_payable_account_id: int = Field(gt=0)

    @model_validator(mode="after")
    def unique_accounts(self):
        ids=[self.bank_account_id,self.paye_payable_account_id,self.nssf_payable_account_id,self.shif_payable_account_id,self.housing_levy_payable_account_id,self.pension_payable_account_id]
        if len(ids)!=len(set(ids)):
            raise ValueError("Each statutory control and bank account must be distinct")
        return self


@router.get("/api/v1/accounting/fx/rates")
def list_fx_rates(membership=Depends(active_membership), db: Session=Depends(get_db)):
    _require_finance(membership)
    rows = db.query(AccountingFxRate).filter_by(organization_id=membership.organization_id).order_by(AccountingFxRate.rate_date.desc(), AccountingFxRate.id.desc()).limit(250).all()
    return [{"id":x.id,"currency":x.currency,"rate_date":x.rate_date.date().isoformat(),"units_per_base":str(x.units_per_base),"source":x.source,"reference":x.reference} for x in rows]


@router.post("/api/v1/accounting/fx/rates", status_code=201)
def create_fx_rate(payload: FxRateIn, membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    _require_finance(membership)
    org = db.query(Organization).filter_by(id=membership.organization_id, is_active=True).first()
    if not org:
        raise HTTPException(404, "Organization not found")
    if payload.currency == org.currency:
        raise HTTPException(422, "Do not configure an FX rate for the organization's base currency")
    if db.query(AccountingFxRate).filter_by(organization_id=org.id, currency=payload.currency, rate_date=datetime.combine(payload.rate_date,time.min,tzinfo=timezone.utc), source=payload.source).first():
        raise HTTPException(409, "An exchange rate from this source already exists for this currency and date")
    row=AccountingFxRate(organization_id=org.id,currency=payload.currency,
        rate_date=datetime.combine(payload.rate_date,time.min,tzinfo=timezone.utc),
        units_per_base=payload.units_per_base,source=payload.source,reference=payload.reference,created_by=user.id)
    db.add(row); db.flush()
    _audit(db,user,org.id,"accounting.fx_rate.created","accounting_fx_rate",row.id,f"{row.currency} {row.units_per_base} from {row.source}")
    db.commit()
    return {"id":row.id,"currency":row.currency,"rate_date":payload.rate_date.isoformat(),"units_per_base":str(row.units_per_base),"source":row.source}


@router.post("/api/v1/accounting/fx/postings", status_code=201)
def post_fx_transaction(payload: FxPostingIn, membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    _require_finance(membership)
    prior=db.query(AccountingFxPosting).filter_by(organization_id=membership.organization_id,idempotency_key=payload.idempotency_key).first()
    request_hash=_payload_hash(payload)
    if prior:
        if prior.payload_hash!=request_hash: raise HTTPException(409,"Idempotency key was already used with a different FX posting payload")
        return {"id":prior.id,"journal_id":prior.journal_id,"currency":prior.currency,"foreign_amount":str(prior.foreign_amount),"base_amount":str(prior.base_amount),"replayed":True}
    org=db.query(Organization).filter_by(id=membership.organization_id,is_active=True).first()
    rate=db.query(AccountingFxRate).filter_by(id=payload.rate_id,organization_id=membership.organization_id).first()
    if not org or not rate or rate.currency==org.currency or rate.rate_date.date()>payload.entry_date:
        raise HTTPException(422,"A tenant-owned exchange rate dated on or before the posting date is required")
    _branch_or_404(db,membership,payload.branch_id)
    _accounting_assert_period_open(db,org.id,payload.entry_date)
    _accounts(db,org.id,[payload.debit_account_id,payload.credit_account_id])
    base_amount=money(payload.foreign_amount / Decimal(rate.units_per_base))
    if base_amount <= 0:
        raise HTTPException(422,"Converted base amount rounds to zero")
    journal=_accounting_make_journal(db,membership,user,payload.entry_date,payload.reference,
        payload.memo or f"Foreign currency posting {payload.foreign_amount} {rate.currency}",
        [{"account_id":payload.debit_account_id,"description":f"Debit {payload.foreign_amount} {rate.currency}","debit":base_amount,"credit":0},
         {"account_id":payload.credit_account_id,"description":f"Credit {payload.foreign_amount} {rate.currency}","debit":0,"credit":base_amount}],payload.branch_id)
    row=AccountingFxPosting(organization_id=org.id,journal_id=journal.id,rate_id=rate.id,
        currency=rate.currency,foreign_amount=payload.foreign_amount,base_amount=base_amount,
        idempotency_key=payload.idempotency_key,payload_hash=request_hash,reference=payload.reference,created_by=user.id)
    db.add(row); db.flush()
    _audit(db,user,org.id,"accounting.fx_posted","accounting_fx_posting",row.id,f"{payload.foreign_amount} {rate.currency} at {rate.units_per_base}; base {base_amount} {org.currency}")
    db.commit()
    return {"id":row.id,"journal_id":journal.id,"currency":rate.currency,"foreign_amount":str(row.foreign_amount),"rate":str(rate.units_per_base),"base_currency":org.currency,"base_amount":str(base_amount),"replayed":False}


@router.post("/api/v1/accounting/fx/revaluations", status_code=201)
def create_fx_revaluation(payload: FxRevaluationIn, membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    _require_finance(membership)
    request_hash=_payload_hash(payload)
    prior=db.query(AccountingFxRevaluation).filter_by(organization_id=membership.organization_id,idempotency_key=payload.idempotency_key).first()
    if prior:
        if prior.payload_hash!=request_hash: raise HTTPException(409,"Idempotency key was already used with a different FX revaluation payload")
        return {"id":prior.id,"journal_id":prior.journal_id,"total_gain":str(prior.total_gain),"total_loss":str(prior.total_loss),"replayed":True}
    org=db.query(Organization).filter_by(id=membership.organization_id,is_active=True).first()
    if not org or payload.currency==org.currency:
        raise HTTPException(422,"Revaluation currency must differ from the organization's base currency")
    _branch_or_404(db,membership,payload.branch_id)
    ids=[x.account_id for x in payload.positions]+[payload.fx_gain_account_id,payload.fx_loss_account_id]
    accounts=_accounts(db,org.id,ids)
    if accounts[payload.fx_gain_account_id].account_type!="revenue" or accounts[payload.fx_loss_account_id].account_type!="expense":
        raise HTTPException(422,"FX gain account must be revenue and FX loss account must be expense")
    lines=[]; snapshot=[]; total_gain=Decimal("0.00"); total_loss=Decimal("0.00")
    for pos in payload.positions:
        account=accounts[pos.account_id]
        if account.account_type != ("asset" if pos.position_type=="asset" else "liability"):
            raise HTTPException(422,"Position type must match the selected ledger account")
        target=money(pos.foreign_balance / payload.closing_rate)
        delta=money(target-pos.carrying_base_amount)
        snapshot.append({"account_id":pos.account_id,"position_type":pos.position_type,"foreign_balance":str(pos.foreign_balance),"carrying_base_amount":str(pos.carrying_base_amount),"closing_base_amount":str(target),"difference":str(delta)})
        if delta==0: continue
        # An asset increase is a gain; a liability increase is a loss.
        gain = (delta>0 and pos.position_type=="asset") or (delta<0 and pos.position_type=="liability")
        amount=abs(delta)
        if gain:
            total_gain+=amount
            if pos.position_type=="asset":
                lines.extend([{"account_id":pos.account_id,"description":f"{payload.currency} asset revaluation","debit":amount,"credit":0},{"account_id":payload.fx_gain_account_id,"description":"Unrealized FX gain","debit":0,"credit":amount}])
            else:
                lines.extend([{"account_id":pos.account_id,"description":f"{payload.currency} liability revaluation","debit":amount,"credit":0},{"account_id":payload.fx_gain_account_id,"description":"Unrealized FX gain","debit":0,"credit":amount}])
        else:
            total_loss+=amount
            if pos.position_type=="asset":
                lines.extend([{"account_id":payload.fx_loss_account_id,"description":"Unrealized FX loss","debit":amount,"credit":0},{"account_id":pos.account_id,"description":f"{payload.currency} asset revaluation","debit":0,"credit":amount}])
            else:
                lines.extend([{"account_id":payload.fx_loss_account_id,"description":"Unrealized FX loss","debit":amount,"credit":0},{"account_id":pos.account_id,"description":f"{payload.currency} liability revaluation","debit":0,"credit":amount}])
    if not lines:
        raise HTTPException(422,"No revaluation difference exists; no journal was created")
    journal=_accounting_make_journal(db,membership,user,payload.valuation_date,f"FX-REVAL-{payload.currency}-{payload.valuation_date.isoformat()}","Foreign currency period-end revaluation",lines,payload.branch_id)
    row=AccountingFxRevaluation(organization_id=org.id,journal_id=journal.id,currency=payload.currency,
        valuation_date=datetime.combine(payload.valuation_date,time.min,tzinfo=timezone.utc),closing_rate=payload.closing_rate,
        total_gain=total_gain,total_loss=total_loss,position_snapshot=snapshot,idempotency_key=payload.idempotency_key,payload_hash=request_hash,created_by=user.id)
    db.add(row);db.flush()
    _audit(db,user,org.id,"accounting.fx_revaluation.posted","accounting_fx_revaluation",row.id,f"gain {total_gain}; loss {total_loss}")
    db.commit()
    return {"id":row.id,"journal_id":journal.id,"currency":payload.currency,"closing_rate":str(payload.closing_rate),"total_gain":str(total_gain),"total_loss":str(total_loss),"positions":snapshot,"replayed":False}


def _load_statutory_batch(db,membership,batch_id):
    batch=db.query(PayrollStatutoryBatch).filter_by(id=batch_id,organization_id=membership.organization_id).first()
    if not batch:
        raise HTTPException(404,"Statutory batch not found")
    runs=db.query(PayrollRun).filter(PayrollRun.organization_id==membership.organization_id,PayrollRun.id.in_(batch.source_run_ids)).all()
    if len(runs)!=len(batch.source_run_ids) or any(not can_access_branch(membership,run.branch_id) for run in runs):
        raise HTTPException(404,"Statutory batch not found")
    return batch


def _statutory_payload(batch):
    return {"id":batch.id,"period_start":batch.period_start.date().isoformat(),"period_end":batch.period_end.date().isoformat(),"currency":batch.currency,"status":batch.status,"totals":batch.totals,"source_run_ids":batch.source_run_ids,"payment_reference":batch.payment_reference,"payment_journal_id":batch.payment_journal_id,"created_by":batch.created_by,"submitted_by":batch.submitted_by,"approved_by":batch.approved_by,"paid_by":batch.paid_by}


@router.get("/api/v1/payroll/statutory-batches")
def list_statutory_batches(membership=Depends(active_membership),db:Session=Depends(get_db)):
    role=(membership.role or "").lower()
    if role not in {"org_admin","payroll_manager","payroll_approver","payroll_payment","accountant","hr_admin"}:
        raise HTTPException(403,"Payroll statutory access is restricted")
    rows=db.query(PayrollStatutoryBatch).filter_by(organization_id=membership.organization_id).order_by(PayrollStatutoryBatch.id.desc()).limit(100).all()
    visible=[]
    for row in rows:
        try: _load_statutory_batch(db,membership,row.id); visible.append(_statutory_payload(row))
        except HTTPException: continue
    return visible


@router.post("/api/v1/payroll/statutory-batches",status_code=201)
def create_statutory_batch(payload:StatutoryBatchIn,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    if (membership.role or "").lower() not in {"org_admin","payroll_manager"}:
        raise HTTPException(403,"Only payroll managers can prepare statutory remittances")
    request_hash=_payload_hash(payload)
    prior=db.query(PayrollStatutoryBatch).filter_by(organization_id=membership.organization_id,idempotency_key=payload.idempotency_key).first()
    if prior:
        if prior.payload_hash!=request_hash: raise HTTPException(409,"Idempotency key was already used with a different statutory batch payload")
        _load_statutory_batch(db,membership,prior.id)
        return {**_statutory_payload(prior),"replayed":True}
    runs=db.query(PayrollRun).filter(PayrollRun.organization_id==membership.organization_id,PayrollRun.id.in_(payload.payroll_run_ids)).with_for_update().all()
    if len(runs)!=len(payload.payroll_run_ids) or any(x.status!="approved" or not can_access_branch(membership,x.branch_id) for x in runs):
        raise HTTPException(409,"Every source payroll run must exist in this tenant, be within branch scope and be approved")
    links=db.query(PayrollAccountingLink).filter(PayrollAccountingLink.organization_id==membership.organization_id,PayrollAccountingLink.payroll_run_id.in_(payload.payroll_run_ids)).all()
    if len(links)!=len(runs) or any(x.reversal_journal_id for x in links):
        raise HTTPException(409,"Every payroll run must have a valid, unreversed accounting accrual")
    currencies={x.currency for x in runs}
    if len(currencies)!=1: raise HTTPException(422,"A statutory batch cannot mix payroll currencies")
    org=db.query(Organization).filter_by(id=membership.organization_id,is_active=True).first()
    if not org or currencies!={org.currency}:
        raise HTTPException(422,"Statutory remittance batches must use the organization's base currency")
    periods={(x.period_start.date(),x.period_end.date()) for x in runs}
    if len(periods)!=1:
        raise HTTPException(422,"A statutory batch must contain payroll runs from exactly one pay period")
    prior_batches=db.query(PayrollStatutoryBatch).filter_by(organization_id=membership.organization_id).all()
    selected=set(payload.payroll_run_ids)
    if any(selected.intersection(set(batch.source_run_ids or [])) for batch in prior_batches):
        raise HTTPException(409,"One or more payroll runs already belong to a statutory remittance batch")
    slips=db.query(PayrollPayslip).filter(PayrollPayslip.organization_id==membership.organization_id,PayrollPayslip.payroll_run_id.in_(payload.payroll_run_ids)).all()
    if not slips: raise HTTPException(409,"No payroll payslips exist for the selected runs")
    totals={"PAYE":Decimal("0"),"NSSF_EMPLOYEE":Decimal("0"),"NSSF_EMPLOYER":Decimal("0"),"SHIF":Decimal("0"),"HOUSING_LEVY_EMPLOYEE":Decimal("0"),"HOUSING_LEVY_EMPLOYER":Decimal("0"),"PENSION":Decimal("0")}
    employee_lines=[]
    for slip in slips:
        values={"PAYE":Decimal(slip.paye),"NSSF_EMPLOYEE":Decimal(slip.nssf_employee),"NSSF_EMPLOYER":Decimal(slip.nssf_employer),"SHIF":Decimal(slip.shif_employee),"HOUSING_LEVY_EMPLOYEE":Decimal(slip.housing_levy_employee),"HOUSING_LEVY_EMPLOYER":Decimal(slip.housing_levy_employer),"PENSION":Decimal(slip.pension_employee)}
        for key,value in values.items(): totals[key]+=value
        employee_lines.append({"employee_id":slip.employee_id,"employee_number":slip.employee_number,"employee_name":slip.employee_name,**{key:str(money(value)) for key,value in values.items()}})
    totals={k:str(money(v)) for k,v in totals.items()}
    start=min(x.period_start for x in runs); end=max(x.period_end for x in runs)
    batch=PayrollStatutoryBatch(organization_id=membership.organization_id,period_start=start,period_end=end,currency=next(iter(currencies)),totals=totals,employee_lines=employee_lines,source_run_ids=payload.payroll_run_ids,idempotency_key=payload.idempotency_key,payload_hash=request_hash,created_by=user.id)
    db.add(batch);db.flush();_audit(db,user,membership.organization_id,"payroll.statutory_batch.created","payroll_statutory_batch",batch.id,str(totals));db.commit()
    return {**_statutory_payload(batch),"replayed":False}


@router.post("/api/v1/payroll/statutory-batches/{batch_id}/submit")
def submit_statutory_batch(batch_id:int,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    if (membership.role or "").lower() not in {"org_admin","payroll_manager"}: raise HTTPException(403,"Payroll manager role required")
    row=_load_statutory_batch(db,membership,batch_id)
    row=db.query(PayrollStatutoryBatch).filter_by(id=row.id,organization_id=membership.organization_id).with_for_update().first()
    if row.status!="draft": raise HTTPException(409,"Only draft statutory batches can be submitted")
    row.status="pending_approval";row.submitted_by=user.id;row.submitted_at=datetime.now(timezone.utc)
    _audit(db,user,membership.organization_id,"payroll.statutory_batch.submitted","payroll_statutory_batch",row.id);db.commit();return _statutory_payload(row)


@router.post("/api/v1/payroll/statutory-batches/{batch_id}/approve")
def approve_statutory_batch(batch_id:int,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    if (membership.role or "").lower() not in {"org_admin","payroll_approver"}: raise HTTPException(403,"Payroll approver role required")
    row=db.query(PayrollStatutoryBatch).filter_by(id=batch_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Statutory batch not found")
    if row.status!="pending_approval": raise HTTPException(409,"Only submitted statutory batches can be approved")
    if user.id in {row.created_by,row.submitted_by}: raise HTTPException(409,"Preparer or submitter cannot approve the statutory batch")
    row.status="approved";row.approved_by=user.id;row.approved_at=datetime.now(timezone.utc)
    _audit(db,user,membership.organization_id,"payroll.statutory_batch.approved","payroll_statutory_batch",row.id);db.commit();return _statutory_payload(row)


@router.post("/api/v1/payroll/statutory-batches/{batch_id}/record-payment")
def record_statutory_payment(batch_id:int,payload:StatutoryPaymentIn,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    if (membership.role or "").lower() not in {"org_admin","payroll_payment"}: raise HTTPException(403,"Payroll payment role required")
    row=db.query(PayrollStatutoryBatch).filter_by(id=batch_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Statutory batch not found")
    if row.status!="approved": raise HTTPException(409,"Only approved statutory batches can be marked remitted")
    if user.id in {row.created_by,row.submitted_by,row.approved_by}: raise HTTPException(409,"Preparer, submitter or approver cannot record remittance")
    org=db.query(Organization).filter_by(id=membership.organization_id,is_active=True).first()
    if not org or row.currency!=org.currency:
        raise HTTPException(422,"Statutory settlement must use the organization's base currency; configure an approved FX settlement workflow for foreign-currency payroll")
    account_ids=[payload.bank_account_id,payload.paye_payable_account_id,payload.nssf_payable_account_id,payload.shif_payable_account_id,payload.housing_levy_payable_account_id,payload.pension_payable_account_id]
    account_map=_accounts(db,membership.organization_id,account_ids)
    if account_map[payload.bank_account_id].account_type!="asset":
        raise HTTPException(422,"Statutory settlement bank account must be an asset")
    for account_id in account_ids[1:]:
        if account_map[account_id].account_type!="liability":
            raise HTTPException(422,"Statutory control accounts must be liabilities")
    totals=row.totals
    obligations=[
        (payload.paye_payable_account_id,Decimal(totals["PAYE"]),"PAYE"),
        (payload.nssf_payable_account_id,Decimal(totals["NSSF_EMPLOYEE"])+Decimal(totals["NSSF_EMPLOYER"]),"NSSF"),
        (payload.shif_payable_account_id,Decimal(totals["SHIF"]),"SHIF"),
        (payload.housing_levy_payable_account_id,Decimal(totals["HOUSING_LEVY_EMPLOYEE"])+Decimal(totals["HOUSING_LEVY_EMPLOYER"]),"Housing Levy"),
        (payload.pension_payable_account_id,Decimal(totals["PENSION"]),"Pension"),
    ]
    lines=[]; grand_total=Decimal("0.00")
    for account_id,amount,label in obligations:
        amount=money(amount)
        if amount>0:
            lines.append({"account_id":account_id,"description":f"{label} statutory remittance","debit":amount,"credit":0})
            grand_total+=amount
    if grand_total<=0: raise HTTPException(409,"There are no statutory amounts to remit")
    lines.append({"account_id":payload.bank_account_id,"description":"Statutory remittance bank settlement","debit":0,"credit":grand_total})
    journal=_accounting_make_journal(db,membership,user,payload.payment_date,payload.payment_reference,"Statutory payroll remittance settlement",lines)
    row.payment_journal_id=journal.id
    row.status="remitted";row.paid_by=user.id;row.payment_reference=payload.payment_reference;row.paid_at=datetime.now(timezone.utc)
    _audit(db,user,membership.organization_id,"payroll.statutory_batch.remitted","payroll_statutory_batch",row.id,f"{payload.payment_reference}; journal {journal.id}; amount {grand_total}")
    db.commit();return _statutory_payload(row)


@router.get("/api/v1/payroll/statutory-batches/{batch_id}/return")
def statutory_return(batch_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    if (membership.role or "").lower() not in {"org_admin","payroll_manager","payroll_approver","payroll_payment","accountant","hr_admin"}: raise HTTPException(403,"Payroll statutory access is restricted")
    row=_load_statutory_batch(db,membership,batch_id)
    return {"schema_version":"onecore.statutory-return.v1","batch":_statutory_payload(row),"employee_lines":row.employee_lines,"filing_status":"not_filed","provider_submission_id":None,"notice":"Export is a calculation schedule, not a statutory filing receipt. Submit through the approved authority channel and record the resulting reference."}
