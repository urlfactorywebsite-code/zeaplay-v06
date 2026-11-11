"""Versioned organization navigation policy; personal layout stays in the browser."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_active_user
from ..navigation_registry import BY_ID
from ..permissions import NAVIGATION_MANAGERS
from ..services.navigation import load_policy, public_policy

router = APIRouter(prefix="/navigation", tags=["navigation"])


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    hidden: StrictBool
    allowedRoles: list[models.RoleEnum]


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Annotated[int, Field(strict=True, ge=0)]
    pages: dict[str, Rule]


@router.get("")
def read_navigation(db: Session = Depends(get_db), user: models.User = Depends(get_current_active_user)):
    return public_policy(db, user)


@router.put("")
def update_navigation(payload: PolicyUpdate, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_active_user)):
    if user.role not in NAVIGATION_MANAGERS:
        raise HTTPException(403, "Navigation management requires Admin or Owner access.")
    if set(payload.pages) != set(BY_ID):
        raise HTTPException(422, "Provide exactly the registered page IDs.")
    row, before = load_policy(db, user.tenant_id)
    if payload.version != (row.version if row else 0):
        raise HTTPException(409, "Navigation changed in another session. Discard and reload before saving.")
    after = {}
    for key, rule in payload.pages.items():
        roles = [role.value for role in rule.allowedRoles]
        entry = BY_ID[key]
        if len(roles) != len(set(roles)) or not set(roles).issubset(entry["permittedRoles"]):
            raise HTTPException(422, f"Invalid roles for {key}. Existing permissions cannot be expanded.")
        value = dict(enabled=rule.enabled, hidden=rule.hidden, allowedRoles=sorted(roles))
        if entry["isSystemProtected"] and (not rule.enabled or rule.hidden or set(roles) != set(entry["permittedRoles"])):
            raise HTTPException(422, f"{key} is a protected recovery page.")
        if user.role != models.RoleEnum.OWNER and (rule.enabled != before[key]["enabled"] or set(roles) != set(before[key]["allowedRoles"])):
            raise HTTPException(403, "Only the Owner can change module availability or role access. Admins can hide navigation only.")
        after[key] = value
    now = datetime.now(timezone.utc)
    values = dict(pages=after, version=payload.version + 1, updated_by=str(user.id), updated_at=now)
    try:
        if row:
            result = db.execute(update(models.NavigationPolicy).where(
                models.NavigationPolicy.tenant_id == str(user.tenant_id),
                models.NavigationPolicy.version == payload.version).values(**values))
            if result.rowcount != 1:
                db.rollback()
                raise HTTPException(409, "Navigation changed in another session. Discard and reload before saving.")
        else:
            db.add(models.NavigationPolicy(tenant_id=str(user.tenant_id), **values))
            try:
                db.flush()
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(409, "Navigation changed in another session. Discard and reload before saving.") from exc
        # Use the existing audit table in the SAME transaction, so a save cannot
        # succeed without its audit record. No asynchronous best-effort logging.
        db.add(models.AuditLog(actor_id=str(user.id), actor_role=user.role.value,
            action="NAVIGATION_POLICY_UPDATED", category=models.AuditLogCategoryEnum.SYSTEM,
            entity_type="navigation_policy", entity_id=str(user.tenant_id),
            before=before, after=after, metadata_payload={"tenant_id": str(user.tenant_id), "version": values["version"]},
            source=models.AuditLogSourceEnum.API, route=request.url.path, method=request.method))
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(503, "Navigation could not be saved with its audit record. No changes were committed.") from exc
    db.expire_all()
    return public_policy(db, user)
