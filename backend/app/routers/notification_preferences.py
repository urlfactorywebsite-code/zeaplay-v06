from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_active_user

router = APIRouter(prefix="/notification/preferences", tags=["notifications"])

MODULES: list[schemas.NotificationModule] = [
    "tasks",
    "tickets",
    "users",
    "departments",
    "comments",
    "chat",
]


@router.get("", response_model=list[schemas.NotificationPreferenceRead])
def list_preferences(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> list[schemas.NotificationPreferenceRead]:
    prefs = db.execute(
        select(models.NotificationPreference).where(models.NotificationPreference.user_id == current_user.id)
    ).scalars().all()
    pref_map = {pref.module: pref for pref in prefs}
    response: list[schemas.NotificationPreferenceRead] = []
    for module in MODULES:
        pref = pref_map.get(module)
        response.append(
            schemas.NotificationPreferenceRead(
                module=module,
                push_enabled=pref.push_enabled if pref else True,
                updated_at=pref.updated_at if pref else None,
                **({key: getattr(pref, key) for key in (
                    "sound_enabled", "near_deadline_hours", "productive_capacity_hours",
                    "overtime_threshold_minutes", "quiet_start", "quiet_end"
                )} if pref else {}),
            )
        )
    return response


@router.post("", response_model=list[schemas.NotificationPreferenceRead])
def update_preferences(
    payload: schemas.NotificationPreferenceBatchUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> list[schemas.NotificationPreferenceRead]:
    now = datetime.now(timezone.utc)
    # Serialize first-time inserts and partial preference updates across tabs.
    # Reuse the activity system's SQLite write admission / user-row lock pattern.
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    db.execute(select(models.User.id).where(models.User.id == current_user.id).with_for_update()).one()
    prefs = db.execute(
        select(models.NotificationPreference).where(models.NotificationPreference.user_id == current_user.id)
    ).scalars().all()
    pref_map = {pref.module: pref for pref in prefs}

    for update in payload.preferences:
        existing = pref_map.get(update.module)
        values = update.model_dump(exclude_unset=True, exclude={"module"})
        # Null clears only optional overrides, never required policy defaults.
        for key in ("sound_enabled", "near_deadline_hours", "overtime_threshold_minutes"):
            if values.get(key, False) is None:
                values.pop(key)
        start = values.get("quiet_start", existing.quiet_start if existing else None)
        end = values.get("quiet_end", existing.quiet_end if existing else None)
        if bool(start) != bool(end):
            raise HTTPException(422, "Enter both quiet-hour times or clear both")
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.updated_at = now
        else:
            existing = models.NotificationPreference(
                    user_id=str(current_user.id),
                    module=update.module,
                    **values,
                    updated_at=now,
                )
            db.add(existing)
            pref_map[update.module] = existing
    db.commit()
    from ..services.task_events import publish_task_event
    for kind in ("notifications.changed", "work.changed"):
        try:
            publish_task_event({"type": kind, "tenant_id": str(current_user.tenant_id), "user_id": current_user.id})
        except Exception:  # noqa: BLE001 -- committed preferences survive an unavailable optional stream
            pass  # Existing foreground/reconnect refetch remains authoritative.
    return list_preferences(db=db, current_user=current_user)
