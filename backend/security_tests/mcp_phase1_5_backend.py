"""Disposable full-stack bootstrap/control. Never usable against an existing DB."""
from pathlib import Path
import json
import os
import socket
import sys
import uuid
from datetime import datetime, timezone

assert Path('/.dockerenv').exists() and Path.cwd() == Path('/scratch')
run_id = os.environ['ZEA_PHASE15_RUN']
assert len(run_id) == 32
sys.path.insert(0, '/source')
from sqlalchemy.engine import make_url
target = make_url(os.environ['VEE_DATABASE_URL'])
assert target.host == 'postgres' and target.database == 'zea_phase15' and target.username == 'zea_fixture'
assert os.environ['VEE_REDIS_URL'] == os.environ['VEE_CACHE_REDIS_URL'] == 'redis://redis:6379/0'
allowed = {row[4][0] for host in ('postgres', 'redis') for row in socket.getaddrinfo(host, None)}


def guard(event, args):
    if event.startswith('sqlite3.connect'):
        raise RuntimeError('SQLite forbidden')
    if event == 'socket.getaddrinfo' and args[0] not in ('postgres', 'redis', '127.0.0.1', 'localhost', '0.0.0.0'):
        raise RuntimeError('External DNS forbidden')
    if event == 'socket.connect':
        addr = args[1]
        if isinstance(addr, tuple) and not (addr[0] in allowed and addr[1] in (5432, 6379)):
            raise RuntimeError('External connection forbidden')


sys.addaudithook(guard)
from app.config import get_settings
settings = get_settings()
assert settings.database_url == os.environ['VEE_DATABASE_URL']
assert not any((settings.enable_n8n_forwarding, settings.n8n_webhook_url, settings.gemini_api_keys,
                settings.vapid_private_key, settings.webex_bot_token, settings.minio_access_key,
                settings.google_client_secret, settings.supabase_service_role_key))
from app.database import Base, engine
from app import models as m
from app.tickets import models as tm
from app.session_models import AuthSession, AuthRefreshToken
import app.backups.models  # noqa: F401
from sqlalchemy import select, text, func, inspect
from sqlalchemy.orm import Session


def ident(name):
    return str(uuid.uuid5(uuid.UUID(run_id), name))


def fixture_info():
    return {'tenant': ident('tenant-a'), 'foreign': ident('tenant-b'), 'department': ident('department'),
            'ticket': ident('ticket-a'), 'foreign_ticket': ident('ticket-b'),
            'users': {name: ident(name) for name in ('owner', 'member', 'peer', 'watcher', 'manager', 'foreign', 'life', 'renew')}}


def verify():
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT current_database()')) == 'zea_phase15'
        assert conn.scalar(text('SELECT run_id FROM phase15_fixture_guard')) == run_id


def initialize():
    from alembic import command
    from alembic.config import Config
    from app.auth import hash_password
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")) == 0
        conn.execute(text('CREATE EXTENSION pg_trgm'))
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values() if not t.info.get('alembic_only')])
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE users DROP COLUMN auth_epoch'))
        conn.execute(text('ALTER TABLE audit_logs DROP COLUMN tenant_id CASCADE'))
    cfg = Config()
    cfg.set_main_option('script_location', '/migrations')
    command.stamp(cfg, 'k1a3c5e7f9b1')
    command.upgrade(cfg, 'm3c5e7f9a1d3')
    info = fixture_info()
    tenant, foreign = uuid.UUID(info['tenant']), uuid.UUID(info['foreign'])
    with Session(engine) as db:
        db.execute(text('CREATE TABLE phase15_fixture_guard (run_id text PRIMARY KEY)'))
        db.execute(text('INSERT INTO phase15_fixture_guard VALUES (:run)'), {'run': run_id})
        db.add(m.Department(id=info['department'], name='Shared synthetic department'))
        hashed = hash_password(os.environ['ZEA_PHASE15_PASSWORD'])
        for name, user_id in info['users'].items():
            role = m.RoleEnum.OWNER if name in ('owner', 'foreign') else m.RoleEnum.MANAGER if name == 'manager' else m.RoleEnum.USER
            db.add(m.User(id=user_id, tenant_id=foreign if name == 'foreign' else tenant,
                email=f'{name}@phase15.example.com', name=f'Fixture {name}', role=role,
                status=m.UserStatusEnum.ACTIVE, hashed_password=hashed, department_id=info['department']))
        db.flush()
        for task_id, creator, assignee, group in (('assigned', 'owner', 'member', 'shared'),
                ('sibling', 'owner', 'peer', 'shared'), ('foreign-task', 'foreign', 'foreign', 'foreign-group')):
            db.add(m.Task(id=task_id, title=f'Synthetic {task_id}', created_by_id=info['users'][creator],
                assigned_to_id=info['users'][assignee], task_group_id=group))
        db.flush()
        assigned = db.get(m.Task, 'assigned')
        assigned.followers.append(db.get(m.User, info['users']['watcher']))
        for tid, ten, who in ((info['ticket'], tenant, 'member'), (info['foreign_ticket'], foreign, 'foreign')):
            db.add(tm.Ticket(id=uuid.UUID(tid), tenant_id=ten, title=f'Synthetic {who} ticket', description='Only synthetic data',
                created_by=info['users'][who], owner_id=info['users'][who], department_id=uuid.UUID(info['department'])))
        db.flush()
        db.add(m.Task(id='ticket-private', title='Synthetic linked task', ticket_id=uuid.UUID(info['ticket']),
            created_by_id=info['users']['member'], assigned_to_id=info['users']['member'], task_group_id='ticket-only'))
        db.add(tm.TicketAuditLog(tenant_id=tenant, ticket_id=uuid.UUID(info['ticket']), actor_user_id=info['users']['member'],
            event_type='fixture.private', summary='Synthetic private ticket log', created_at_utc=datetime.now(timezone.utc)))
        for key, ten, actor, task in (('audit-a', tenant, 'member', 'assigned'), ('audit-b', foreign, 'foreign', 'foreign-task')):
            db.add(m.AuditLog(id=key, tenant_id=ten, actor_id=info['users'][actor], action='PHASE15_FIXTURE',
                category=m.AuditLogCategoryEnum.AUTOMATION, entity_type='task', entity_id=task))
        db.add(m.Notification(id='notice-foreign', tenant_id=foreign, user_id=info['users']['member'],
            type=m.NotificationTypeEnum.TICKET_UPDATED, message='Synthetic foreign notice',
            entity_type=m.NotificationEntityTypeEnum.TICKET, entity_id=info['foreign_ticket']))
        db.commit()
    print(json.dumps(info))


def control(action, payload):
    verify()
    with Session(engine) as db:
        user = db.get(m.User, ident(payload.get('user', 'life')))
        if action == 'tenant':
            assert payload['tenant'] in ('tenant-a', 'tenant-b')
            user.tenant_id = uuid.UUID(ident(payload['tenant']))
            db.commit()
        elif action == 'sessions':
            sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all()
            result = [{'id': s.id, 'revoked': s.revoked_at is not None, 'reason': s.revocation_reason,
                       'epoch': s.auth_epoch, 'tenant': str(s.tenant_id),
                       'refresh_count': db.scalar(select(func.count()).select_from(AuthRefreshToken).where(AuthRefreshToken.session_id == s.id)),
                       'consumed_count': db.scalar(select(func.count()).select_from(AuthRefreshToken).where(AuthRefreshToken.session_id == s.id, AuthRefreshToken.consumed_at.is_not(None)))} for s in sessions]
            print(json.dumps({'epoch': user.auth_epoch, 'sessions': result}))
            return
        elif action == 'presence':
            import redis
            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            count = client.scard(f'presence:tenant:{user.tenant_id}:user:{user.id}:sockets')
            print(json.dumps({'redis_ping': client.ping(), 'sockets': count, 'online': client.sismember(f'presence:tenant:{user.tenant_id}:online_users', user.id)}))
            return
        elif action == 'inspect':
            import redis
            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            inspector = inspect(engine)
            schema = {name: {
                'columns': {column['name']: str(column['type']) for column in inspector.get_columns(name)
                            if column['name'] in ('id', 'name', 'tenant_id', 'department_id', 'auth_epoch')},
                'department_foreign_keys': [key for key in inspector.get_foreign_keys(name)
                                            if 'department_id' in key['constrained_columns']],
            } for name in ('departments', 'users', 'tickets', 'ticket_sla_policies', 'task_templates', 'media_files')}
            denied = False
            try:
                socket.create_connection(('203.0.113.1', 443), timeout=1)
            except RuntimeError:
                denied = True
            assert denied, 'Network safety guard must reject non-fixture connections'
            print(json.dumps({
                'postgres_version': db.scalar(text('SHOW server_version')),
                'alembic_revision': db.scalar(text('SELECT version_num FROM alembic_version')),
                'security_triggers': [dict(row) for row in db.execute(text(
                    "SELECT tgname, tgenabled FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'zea%'")).mappings()],
                'schema': schema, 'redis_version': client.info('server')['redis_version'],
                'redis_ping': client.ping(), 'redis_presence_keys': len(list(client.scan_iter('presence:*'))),
                'external_connection_guard': denied,
                'auth_sessions': db.scalar(select(func.count()).select_from(AuthSession)),
                'revoked_sessions': db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.revoked_at.is_not(None))),
                'consumed_refresh_records': db.scalar(select(func.count()).select_from(AuthRefreshToken).where(AuthRefreshToken.consumed_at.is_not(None))),
            }))
            return
        else:
            raise RuntimeError('Unknown fixture control action')
        print(json.dumps({'committed': True, 'epoch': user.auth_epoch}))


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'init':
        initialize()
    elif mode == 'serve':
        verify()
        Path('/scratch/assets').mkdir(exist_ok=True)
        import uvicorn
        # Actual main application startup, workers, dependencies and routers.
        uvicorn.run('app.main:app', host='0.0.0.0', port=7211, access_log=False)
    else:
        control(mode, json.loads(sys.argv[2]))
