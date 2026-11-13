"""Additional application-wide API guard, including legacy /api aliases."""
from fastapi import Depends, HTTPException
import os
from starlette.requests import HTTPConnection
from sqlalchemy.orm import Session
from .database import get_db
from .dependencies import get_current_user
from .models import UserStatusEnum
from .navigation_registry import api_pages
from .services.navigation import enforce_pages


async def enforce_navigation_policy(connection: HTTPConnection, db: Session = Depends(get_db)):
    # FastAPI app dependencies also run on WebSocket routes. Their existing
    # socket guards authenticate separately; an HTTP Request dependency would
    # break the handshake before those guards can run.
    if connection.scope['type'] != 'http':
        return
    pages = api_pages(connection.url.path, connection.scope['method'])
    if not pages:
        return
    authorization = connection.headers.get("authorization", "").split()
    if len(authorization) != 2 or authorization[0].lower() != "bearer":
        raise HTTPException(401, "Not authenticated")
    if authorization[1].startswith('mcp_dt.') and os.environ.get('ZEA_MCP_PHASE4A_ISOLATED') == '1':
        from .mcp.authority import downstream_user
        downstream_user(db, authorization[1], connection)
    user = await get_current_user(authorization[1], db)
    if user.status != UserStatusEnum.ACTIVE:
        raise HTTPException(403, "User is inactive")
    enforce_pages(db, user, pages)
