"""Run-owned real REST fixture; never importable against an installed database.

No Alembic command/upgrade runs. Initialize an empty test schema from current
models, with the existing auth trigger SQL installed as fixture schema DDL.
The production app/routes/authentication are imported unchanged; lifespan
startup (schema repair, seeding, workers) is deliberately not executed.
"""

import ast
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import sys
import threading
import uuid
from datetime import UTC, datetime, timedelta

run = os.environ["ZEA_PHASE2B_RUN"]
root = Path(os.environ["ZEA_PHASE2B_ROOT"]).resolve()
assert len(run) == 32 and Path.cwd().resolve() == root
assert (root / "owned.json").is_file()
assert json.loads((root / "owned.json").read_text())["run_id"] == run
assert os.environ["ZEA_ALEMBIC_MIGRATION"] == "1"
repo = Path(os.environ["ZEA_PHASE2B_REPO"]).resolve()
db_port, api_port = int(os.environ["ZEA_PHASE2B_DB_PORT"]), int(os.environ["ZEA_PHASE2B_API_PORT"])
pair_state = threading.local()
native_pair = socket.socketpair


def private_pair(*args, **kwargs):
    pair_state.active = True
    try:
        return native_pair(*args, **kwargs)
    finally:
        pair_state.active = False


socket.socketpair = private_pair


def guard(event, args):
    if event in {"socket.bind", "socket.connect"} and getattr(pair_state, "active", False):
        return
    if event == "socket.getaddrinfo" and args[0] not in ("127.0.0.1", "localhost"):
        raise RuntimeError("Fixture outbound DNS denied")
    if event == "socket.connect" and isinstance(args[1], tuple) and args[1][:2] != ("127.0.0.1", db_port):
        raise RuntimeError("Fixture outbound connection denied")
    if event == "socket.bind" and isinstance(args[1], tuple) and args[1][:2] != ("127.0.0.1", api_port):
        raise RuntimeError("Fixture listener denied")
    if event == "sqlite3.connect":
        raise RuntimeError("Unexpected fixture database")


sys.addaudithook(guard)
sys.path.insert(0, str(repo / "backend"))
from sqlalchemy.engine import make_url

url = make_url(os.environ["VEE_DATABASE_URL"])
assert url.host == "127.0.0.1" and url.port == db_port and url.database == "zea_phase2b" and url.username == "zea_phase2b"
from app.database import Base, engine
from app import models as m
from app.tickets import models as tm
from app.session_models import AuthSession, AuthRefreshToken
import app.backups.models
from sqlalchemy import inspect, text, update
from sqlalchemy.orm import Session


def ident(label):
    return str(uuid.uuid5(uuid.UUID(run), label))


def initialize():
    from app.auth import hash_password
    assert not inspect(engine).get_table_names(), "Refusing existing database"
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION pg_trgm"))
    Base.metadata.create_all(engine)
    # Read only the four literal CREATE statements. Do not import or execute a
    # migration module, stamp revisions or alter existing tables/data.
    statements = []
    for file in ("l2b4d6f8a0c2_auth_sessions.py", "m3c5e7f9a1d3_audit_tenant.py"):
        source = ast.parse((repo / "backend/alembic/versions" / file).read_text())
        upgrade = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
        statements.extend(n.args[0].value for n in ast.walk(upgrade)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "execute"
            and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
            and n.args[0].value.strip().startswith(("CREATE FUNCTION", "CREATE TRIGGER")))
    assert len(statements) == 4
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(text("CREATE TABLE phase2b_fixture_guard (run_id text PRIMARY KEY)"))
        connection.execute(text("INSERT INTO phase2b_fixture_guard VALUES (:run)"), {"run": run})
    accounts = json.loads((root / "broker.json").read_text())["accounts"]
    with Session(engine) as db:
        db.add_all([m.Department(id=ident("dept-a"), name="Synthetic A"), m.Department(id=ident("dept-peer"), name="Synthetic peer")])
        for alias, account in accounts.items():
            tenant = uuid.UUID(ident("tenant-b" if alias.startswith("b-") else "tenant-a"))
            role = m.RoleEnum.MANAGER if alias == "a-manager" else m.RoleEnum.OWNER if alias == "a-owner" else m.RoleEnum.USER
            db.add(m.User(id=ident(alias), tenant_id=tenant, name="PRIVATE_USER_SENTINEL " + alias,
                email=account["email"], hashed_password=hash_password(account["password"]),
                role=role, status=m.UserStatusEnum.ACTIVE, timezone="UTC",
                department_id=ident("dept-peer" if alias == "a-peer" else "dept-a")))
        db.flush()
        for label, creator, assignee, group in [
            ("a-main", "a-owner", "a-member", "group-a"),
            ("a-second", "a-owner", "a-member", "group-second"),
            ("a-peer-task", "a-peer", "a-peer", "group-a"),
            ("b-main", "b-member", "b-member", "group-b"),
        ]:
            db.add(m.Task(id=ident(label), title="Synthetic " + label + " /users/" + ident(assignee) + "/avatar-image?v=PRIVATE_MEDIA_SENTINEL",
                description="https://media.invalid/PRIVATE_MEDIA_SENTINEL tenant/PRIVATE_KEY_SENTINEL",
                attachments=["https://media.invalid/PRIVATE_MEDIA_SENTINEL", "tenant/PRIVATE_KEY_SENTINEL"],
                team="Synthetic //media.invalid/PRIVATE_MEDIA_SENTINEL", created_by_id=ident(creator), assigned_to_id=ident(assignee),
                task_group_id=ident(group), due_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2),
                estimated_hours=2.0))
        db.flush()
        for i in range(3):
            db.add(m.Subtask(id=ident("child-" + str(i)), task_id=ident("a-main"), title="Synthetic child " + str(i) + " /assets/task_templates/PRIVATE_MEDIA_SENTINEL.png", completed=False))
        db.commit()
    if os.environ.get('ZEA_MCP_PHASE4A_ISOLATED') == '1':
        from mcp_migrations.phase4a import apply_reviewed
        with engine.begin() as connection:
            apply_reviewed(connection, approved_sha256=os.environ['ZEA_MCP_SCHEMA_APPROVED'], owned_run_id=run)
        from app.mcp.models import Client
        from app.mcp.authority import now
        with Session(engine) as db:
            db.add(Client(id='zea-local-client', name='ZeaPlay isolated protocol client',
                redirect_uris=[os.environ['ZEA_MCP_BACKEND_ORIGIN'] + '/__phase4a__/callback'],
                scopes='tasks:read workload:read', enabled=True, created_at=now()))
            db.commit()
    from app.services.auth_sessions import require_session_schema
    require_session_schema(engine)
    from app.services.audit_security import require_audit_schema
    require_audit_schema(engine)
    (root / "fixtures.json").write_text(json.dumps({
        "users": {a: ident(a) for a in accounts},
        "tasks": {a: ident(a) for a in ("a-main", "a-second", "a-peer-task", "b-main")},
    }))


def serve():
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT run_id FROM phase2b_fixture_guard")) == run
    (root / "assets").mkdir(exist_ok=True)
    from app.main import app
    from fastapi import Header, HTTPException
    secret = os.environ["ZEA_PHASE2B_ATTESTATION"]

    if os.environ.get('ZEA_MCP_PHASE4A_ISOLATED') == '1':
        from fastapi import Request
        @app.post('/__phase4a__/mutate')
        async def mutate(request: Request, x_fixture_control: str = Header('')):
            if not hmac.compare_digest(x_fixture_control, secret):
                raise HTTPException(403)
            body = await request.json()
            from app.mcp.models import Authorization, Credential, Grant, Client, Policy, Audit
            from app.mcp.authority import digest, now
            with Session(engine) as db:
                if body.get('action') in ('role', 'tenant', 'status'):
                    if body.get('alias') not in ('a-member', 'b-member'):
                        raise HTTPException(400)
                    user = db.get(m.User, ident(body['alias']))
                    if body['action'] == 'role': user.role = m.RoleEnum(body['value'])
                    if body['action'] == 'status': user.status = m.UserStatusEnum(body['value'])
                    if body['action'] == 'tenant': user.tenant_id = uuid.UUID(ident('tenant-' + body['value']))
                elif body.get('action') in ('credential_expired', 'wrong_issuer', 'wrong_audience'):
                    row = db.get(Credential, digest(body['credential']))
                    if row is None: raise HTTPException(404)
                    if body['action'] == 'credential_expired':
                        row.created_at, row.expires_at = now() - timedelta(minutes=2), now() - timedelta(minutes=1)
                    elif body['action'] == 'wrong_issuer': row.issuer = 'https://wrong.invalid'
                    else: row.audience = 'https://wrong.invalid'
                elif body.get('action') == 'grant_expired':
                    row = db.get(Grant, body['grant_id'])
                    row.created_at, row.expires_at = now() - timedelta(minutes=2), now() - timedelta(minutes=1)
                elif body.get('action') == 'disclosure_title':
                    row = db.get(m.Task, ident('a-main'))
                    row.title = body['value']
                elif body.get('action') == 'authorization_expired':
                    row = db.get(Authorization, body['request_id'])
                    row.created_at, row.expires_at = now() - timedelta(minutes=6), now() - timedelta(minutes=5)
                elif body.get('action') == 'code_expired':
                    from sqlalchemy import select
                    row = db.scalar(select(Authorization).where(Authorization.code_digest == digest(body['code'])))
                    row.code_expires_at = now() - timedelta(seconds=1)
                elif body.get('action') == 'storage_check':
                    from sqlalchemy import select
                    raw_secrets = body['secrets']
                    values = [str(value) for model in (Authorization, Credential, Grant, Client, Policy, Audit)
                              for row in db.execute(select(model.__table__)) for value in row]
                    return {'raw_secrets_found': any(secret in value for secret in raw_secrets for value in values)}
                else:
                    raise HTTPException(400)
                db.commit()
            return {'changed': True}

        @app.get('/__phase4a__/callback')
        def callback(): return {'callback': 'received'}

    @app.get("/__phase2b__/attest")
    def attest(nonce: str):
        if len(nonce) != 64 or any(c not in "0123456789abcdef" for c in nonce):
            raise HTTPException(400)
        return {"run_id": run, "proof": hmac.new(secret.encode(), (run + ":" + nonce).encode(), hashlib.sha256).hexdigest()}

    @app.post("/__phase2b__/revoke/{alias}")
    def revoke(alias: str, x_fixture_control: str = Header("")):
        if not hmac.compare_digest(x_fixture_control, secret) or alias not in {"a-member", "a-peer", "a-manager", "a-owner", "b-member"}:
            raise HTTPException(403)
        with Session(engine) as db:
            db.execute(update(m.User).where(m.User.id == ident(alias)).values(auth_epoch=m.User.auth_epoch + 1))
            db.commit()
        return {"revoked": True}

    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=api_port, lifespan="off", access_log=False, log_level="critical", proxy_headers=False)


if __name__ == "__main__":
    {"init": initialize, "serve": serve}[sys.argv[1]]()
