"""Read only synthetic browser-audit state inside the guarded run-owned stack."""
import json
import sys

import mcp_phase1_5_backend as fixture
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app import models as m
from app.session_models import AuthSession, AuthRefreshToken
import redis

fixture.verify()
user_id = sys.argv[1]
with Session(fixture.engine) as db:
    user = db.get(m.User, user_id)
    assert user and user.email.startswith("phase2a1-audit-") and user.email.endswith("@phase15.example.com")
    assert str(user.tenant_id) == fixture.ident("tenant-a")
    sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all()
    result = {"epoch": user.auth_epoch, "status": user.status.value, "sessions": [
        {"id": s.id, "revoked": s.revoked_at is not None, "reason": s.revocation_reason,
         "refresh_count": db.scalar(select(func.count()).select_from(AuthRefreshToken).where(AuthRefreshToken.session_id == s.id)),
         "consumed_count": db.scalar(select(func.count()).select_from(AuthRefreshToken).where(
             AuthRefreshToken.session_id == s.id, AuthRefreshToken.consumed_at.is_not(None)))}
        for s in sessions]}
    client = redis.Redis.from_url(fixture.settings.redis_url, decode_responses=True)
    result["presence_sockets"] = client.scard(f"presence:tenant:{user.tenant_id}:user:{user.id}:sockets")
    print(json.dumps(result))
