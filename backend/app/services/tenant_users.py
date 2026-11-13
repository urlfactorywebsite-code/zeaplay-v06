"""Validate relationship grants before making any business mutations."""

from fastapi import HTTPException
from sqlalchemy import select

from .. import models


def require_tenant_users(db, tenant_id, user_ids, *, allow_inactive=()):
    ids = {str(value) for value in user_ids if value}
    if not ids:
        return {}
    # Refresh identity-map state; a previously loaded User is not authority.
    users = db.scalars(select(models.User).where(
        models.User.id.in_(ids), models.User.tenant_id == tenant_id,
    ).execution_options(populate_existing=True)).all()
    by_id = {str(user.id): user for user in users}
    if set(by_id) != ids:
        raise HTTPException(404, "Related user not found in this tenant")
    retained = {str(value) for value in allow_inactive}
    if any(user.status != models.UserStatusEnum.ACTIVE and key not in retained
           for key, user in by_id.items()):
        raise HTTPException(400, "Related user must be active")
    return by_id


def ensure_transfer_scope(task, actor, source, target):
    from .task_access import ensure_task_update_access
    ensure_task_update_access(task, actor)
    if not source or not target or source.tenant_id != actor.tenant_id or target.tenant_id != actor.tenant_id:
        raise HTTPException(404, "Related user not found in this tenant")
    if actor.role == models.RoleEnum.MANAGER and (
        not actor.department_id
        or source.department_id != actor.department_id
        or target.department_id != actor.department_id
    ):
        raise HTTPException(403, "Transfer requires authorized department membership")
