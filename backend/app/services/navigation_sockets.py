"""Recheck module access for existing domain sockets, including active sessions."""
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from ..database import SessionLocal
from ..models import User, UserStatusEnum
from .navigation import enforce_pages


def bind_socket(socket, user, db, pages):
    try:
        enforce_pages(db, user, pages)
    except HTTPException:
        return False
    socket.state.navigation_identity = (str(user.id), str(user.tenant_id))
    return True


def socket_allowed(socket, pages):
    identity = getattr(socket.state, "navigation_identity", None)
    if not identity:
        return False
    try:
        with SessionLocal() as db:
            user = db.get(User, identity[0])
            if not user or user.status != UserStatusEnum.ACTIVE or str(user.tenant_id) != identity[1]:
                return False
            enforce_pages(db, user, pages)
            return True
    except (HTTPException, SQLAlchemyError):
        return False
