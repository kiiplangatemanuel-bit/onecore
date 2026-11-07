"""Canonical idempotency hashes for pharmacy and laboratory requests."""
import hashlib
import json
from decimal import Decimal


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def pharmacy_batch_hash(payload) -> str:
    return _canonical_hash({
        "medicine_id": payload.medicine_id,
        "branch_id": payload.branch_id,
        "batch_number": payload.batch_number.strip().upper(),
        "expiry_date": payload.expiry_date.isoformat(),
        "received_quantity": str(Decimal(payload.received_quantity)),
        "unit_cost": str(Decimal(payload.unit_cost).quantize(Decimal("0.01"))),
        "selling_price": str(Decimal(payload.selling_price).quantize(Decimal("0.01"))),
    })


def laboratory_order_hash(payload) -> str:
    return _canonical_hash({
        "encounter_id": payload.encounter_id,
        "test_ids": sorted(payload.test_ids),
    })
