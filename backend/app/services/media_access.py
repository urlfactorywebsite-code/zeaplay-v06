"""Tenant boundary for existing media records attributed to an uploader."""
from fastapi import HTTPException
from sqlalchemy import select

from ..models import User


def require_media_owner_tenant(db, *, owner_id: str, user: User) -> None:
    # Query current ownership, rather than trusting a previously loaded relation
    # or the globally shared department ID. Inactive owners retain their files.
    tenant = db.scalar(select(User.tenant_id).where(User.id == owner_id))
    if user.tenant_id is None or tenant != user.tenant_id:
        raise HTTPException(404, "Media not found")
