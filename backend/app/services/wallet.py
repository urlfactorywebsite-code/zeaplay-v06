"""Atomic deltas for the existing user wallet; no alternate balance or formula."""

from fastapi import HTTPException
from sqlalchemy import func, update
from sqlalchemy.orm import attributes

from .. import models


def adjust(db, user, delta, *, require_nonnegative=False):
    query = update(models.User).where(
        models.User.id == user.id, models.User.tenant_id == user.tenant_id
    )
    amount = func.coalesce(models.User.points, 0) + delta
    if require_nonnegative:
        query = query.where(amount >= 0)
    value = db.scalar(
        query.values(points=amount).returning(models.User.points),
        execution_options={"synchronize_session": False},
    )
    if value is None:
        raise HTTPException(
            409, "Wallet changed or has insufficient points; reload before retrying"
        )
    attributes.set_committed_value(user, "points", value)
    return value
