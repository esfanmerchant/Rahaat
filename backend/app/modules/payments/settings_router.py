"""Department payment settings for admins: the amount above which a second officer must release a payment.

Lowering the limit below the standard Rs 12,000 payment is how the demo shows maker-checker on every payment.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.contracts.common import Strict
from app.core import audit
from app.core.deps import Principal, get_db
from app.core.errors import NotFound
from app.core.policy import Policy
from app.db import models
from app.modules.payments import rules

# Included by payments/router.py (prefix /v1), so the full path is /v1/admin/payment-settings.
router = APIRouter(prefix="/admin/payment-settings", tags=["payments"])
_read = Policy("payment_settings:read", ["admin", "officer", "auditor"], description="Read the department's payment settings")
_write = Policy("payment_settings:write", ["admin"], description="Change the four-eyes limit for payments")


class PaymentSettingsOut(BaseModel):
    four_eyes_limit_pkr: int = Field(description="Payments above this amount need a second officer to release them")


class PaymentSettingsIn(Strict):
    four_eyes_limit_pkr: int = Field(ge=0, le=1_000_000)
    reason: str = Field(min_length=5, max_length=500)


def _tenant(db: Session, principal: Principal) -> models.Tenant:
    tenant = db.get(models.Tenant, principal.tenant_id)
    if tenant is None:
        raise NotFound("Department not found.")
    return tenant


@router.get("", response_model=PaymentSettingsOut, summary="The department's payment settings")
def read_settings(principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> PaymentSettingsOut:
    return PaymentSettingsOut(four_eyes_limit_pkr=rules.four_eyes_limit(_tenant(db, principal).config))


@router.put("", response_model=PaymentSettingsOut, summary="Change the four-eyes limit (audited)")
def change_settings(body: PaymentSettingsIn, principal: Principal = Depends(_write), db: Session = Depends(get_db)) -> PaymentSettingsOut:
    tenant = _tenant(db, principal)
    old = rules.four_eyes_limit(tenant.config)
    tenant.config = {**(tenant.config or {}), "payment_four_eyes_limit_pkr": body.four_eyes_limit_pkr}  # assign: JSON is not tracked
    audit.write(
        db, tenant_id=principal.tenant_id, action="payments.four_eyes_limit_changed", actor_id=principal.user_id,
        actor_role=principal.role, object_type="tenant", object_id=tenant.id, reason=body.reason,
        details={"from_pkr": old, "to_pkr": body.four_eyes_limit_pkr},
    )  # fmt: skip
    db.commit()
    return PaymentSettingsOut(four_eyes_limit_pkr=body.four_eyes_limit_pkr)
