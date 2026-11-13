"""Own a disposable full stack. start -> browser -> stop; label-checked cleanup."""
from pathlib import Path
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[2]


def docker(*args, check=True, timeout=60):
    return subprocess.run(['docker', *args], capture_output=True, text=True, check=check, timeout=timeout)


def save(state):
    Path(state['scratch'], 'state.json').write_text(json.dumps(state, indent=2))


def cleanup(state):
    for name in reversed(state['containers']):
        found = docker('inspect', '--format', '{{json .Config.Labels}}', name, check=False)
        if found.returncode:
            continue
        assert json.loads(found.stdout).get('zea.phase15') == state['run']
        docker('rm', '-f', name)
    for network in (state['network'], state.get('ingress')):
        if not network:
            continue
        found = docker('network', 'inspect', network, check=False)
        if found.returncode == 0:
            assert json.loads(found.stdout)[0]['Labels'].get('zea.phase15') == state['run']
            docker('network', 'rm', network)
    state['cleaned'] = True
    # Keep non-secret provenance; remove disposable passwords after cleanup.
    state.pop('password', None)
    save(state)
    print('CLEANUP: only this run\'s labeled containers/network removed; no named volumes created')


def start():
    run_id = uuid.uuid4().hex
    scratch = Path(tempfile.mkdtemp(prefix='zea-phase15-stack-'))
    state = {'run': run_id, 'scratch': str(scratch), 'network': 'zea-phase15-' + run_id,
             'ingress': 'zea-phase15-ingress-' + run_id,
             'containers': [], 'password': secrets.token_urlsafe(20)}
    evidence = REPO/'backend/checks'/('phase1-5-' + run_id)
    evidence.mkdir()
    state['evidence'] = str(evidence)
    state['started_at'] = datetime.now(timezone.utc).isoformat()
    save(state)
    try:
        for image in ('postgres:16-alpine', 'redis:7-alpine', 'nginx:alpine', 'zeaplay_v1-backend:latest', 'zeaplay_v1-presence:latest'):
            docker('image', 'inspect', image)
        docker('network', 'create', '--internal', '--label', 'zea.phase15=' + run_id, state['network'])
        docker('network', 'create', '--label', 'zea.phase15=' + run_id, state['ingress'])
        def run(role, image, *args, alias=None, env=None, command=(), network=None):
            name = state['network'] + '-' + role
            state['containers'].append(name)
            save(state)
            env_args = [item for k, v in (env or {}).items() for item in ('-e', k + '=' + v)]
            docker('run', '-d', '--name', name, '--label', 'zea.phase15=' + run_id,
                '--network', network or state['network'], '--network-alias', alias or role,
                *args, *env_args, image, *command)
            return name
        db_pass = secrets.token_hex(24)
        database = run('postgres', 'postgres:16-alpine', '--tmpfs', '/var/lib/postgresql/data',
            env={'POSTGRES_USER': 'zea_fixture', 'POSTGRES_DB': 'zea_phase15', 'POSTGRES_PASSWORD': db_pass})
        run('redis', 'redis:7-alpine', '--read-only', '--tmpfs', '/data', command=('redis-server', '--save', '', '--appendonly', 'no'))
        for _ in range(80):
            if docker('exec', database, 'pg_isready', '-U', 'zea_fixture', '-d', 'zea_phase15', check=False).returncode == 0:
                break
            time.sleep(.25)
        jwt_secret = secrets.token_hex(48)
        env = {'VEE_DATABASE_URL': f'postgresql+psycopg2://zea_fixture:{db_pass}@postgres:5432/zea_phase15',
            'VEE_REDIS_URL': 'redis://redis:6379/0', 'VEE_CACHE_REDIS_URL': 'redis://redis:6379/0',
            'VEE_JWT_SECRET_KEY': jwt_secret, 'VEE_JWT_REFRESH_SECRET_KEY': secrets.token_hex(48),
            'VEE_ACCESS_TOKEN_EXPIRE_MINUTES': '1', 'VEE_REFRESH_TOKEN_EXPIRE_MINUTES': '2',
            'VEE_ENVIRONMENT': 'phase15-isolated', 'VEE_AI_WEBHOOK_URL': '', 'VEE_ENABLE_N8N_FORWARDING': 'false',
            'VEE_CORS_ALLOW_ORIGINS': '["http://localhost"]', 'VEE_MEDIA_ROOT': '/scratch/media',
            'ZEA_PHASE15_RUN': run_id, 'ZEA_PHASE15_PASSWORD': state['password'],
            'PYTHONDONTWRITEBYTECODE': '1', 'ZEA_ALEMBIC_MIGRATION': '1'}
        mounts = []
        for source, target in (('backend/app', '/source/app'), ('backend/alembic', '/migrations'), ('backend/security_tests', '/tests')):
            mounts += ['--mount', f'type=bind,src={REPO/source},dst={target},readonly']
        backend = run('backend', 'zeaplay_v1-backend:latest', '--read-only', '--tmpfs', '/scratch', '--tmpfs', '/tmp',
            '--workdir', '/scratch', *mounts, '--entrypoint', 'sleep', env=env, command=('infinity',))
        state['backend'] = backend
        init = docker('exec', backend, 'python', '-B', '/tests/mcp_phase1_5_backend.py', 'init', timeout=120)
        state['fixture'] = json.loads(init.stdout.strip().splitlines()[-1])
        # A separate foreground app process retains the normal container env.
        docker('exec', '-d', backend, 'sh', '-c', 'exec python -B /tests/mcp_phase1_5_backend.py serve > /scratch/backend.log 2>&1')
        run('presence', 'zeaplay_v1-presence:latest', '--read-only', '--tmpfs', '/tmp',
            '--mount', f'type=bind,src={REPO/"presence-server/src"},dst=/app/src,readonly',
            '--mount', f'type=bind,src={REPO/"presence-server/package.json"},dst=/app/package.json,readonly',
            env={'PRESENCE_PORT': '7212', 'PRESENCE_REDIS_URL': 'redis://redis:6379/0',
                 'PRESENCE_JWT_SECRET': jwt_secret, 'PRESENCE_SESSION_VALIDATION_URL': 'http://backend:7211/auth/presence/validate',
                 'PRESENCE_CORS_ORIGINS': 'http://localhost'}, command=('node', 'src/server.js'))
        www = scratch/'www'
        www.mkdir()
        build_env = {k: v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','PATH','TEMP','TMP','COMSPEC')}
        build_env.update(VITE_API_BASE_URL='/api', VITE_API_URL='/api', VITE_PRESENCE_URL='', VITE_CHAT_URL='',
                         VITE_WS_URL='', VITE_TICKET_CHAT_WS_URL='')
        # Programmatic envDir prevents Vite's implicit root .env loading too.
        # The unchanged config's explicit loadEnv('.') reads only the empty cwd.
        build_script = 'import {build} from ' + json.dumps((REPO/'frontend/node_modules/vite/dist/node/index.js').as_uri()) + '; await build(' + json.dumps({
            'root': str(REPO/'frontend'), 'configFile': str(REPO/'frontend/vite.config.ts'),
            'envDir': str(scratch), 'mode': 'phase15', 'build': {'outDir': str(www)}}) + ');'
        with (evidence/'build.txt').open('w', encoding='utf-8') as log:
            built = subprocess.run(['node', '--input-type=module', '-e', build_script],
                env=build_env, cwd=scratch, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        assert built.returncode == 0, 'Isolated frontend build failed'
        (www/'runtime-config.js').write_text('window.__RUNTIME_CONFIG__={PRESENCE_URL:window.location.origin,CHAT_URL:window.location.origin};')
        config = (REPO/'frontend/nginx.conf').read_text()
        config = config.replace('  location /ws/ {', '''  location /socket.io/ {
    proxy_pass http://presence:7212;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
  }
  location /ws/ {''')
        (scratch/'nginx.conf').write_text(config)
        frontend = run('frontend', 'nginx:alpine', '--read-only', '--tmpfs', '/var/cache/nginx', '--tmpfs', '/var/run',
            '-p', '127.0.0.1::80', '--mount', f'type=bind,src={www},dst=/usr/share/nginx/html,readonly',
            '--mount', f'type=bind,src={scratch/"nginx.conf"},dst=/etc/nginx/conf.d/default.conf,readonly',
            '--entrypoint', 'sleep', command=('infinity',), network=state['ingress'])
        docker('network', 'connect', state['network'], frontend)
        docker('exec', '-d', frontend, 'nginx', '-g', 'daemon off;')
        mapping = docker('port', frontend, '80/tcp').stdout.strip()
        assert mapping.startswith('127.0.0.1:')
        state['origin'] = 'http://' + mapping
        save(state)
        for _ in range(120):
            try:
                with urllib.request.urlopen(state['origin']+'/api/health', timeout=2) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(.5)
        else:
            raise RuntimeError('Disposable backend failed readiness')
        print('ISOLATED_STACK_READY ' + str(scratch/'state.json'), flush=True)
        print('Only loopback frontend published; private internal network; fresh tmpfs PostgreSQL/Redis; current source', flush=True)
        return 0
    except Exception as exc:
        # Do not print command arguments containing generated credentials.
        print('STACK_SETUP_FAILED ' + type(exc).__name__, flush=True)
        detail = getattr(exc, 'stderr', '') or str(exc) if not isinstance(exc, subprocess.SubprocessError) else getattr(exc, 'stderr', '') or type(exc).__name__
        for secret in (state.get('password'), locals().get('db_pass'), locals().get('jwt_secret')):
            if secret:
                detail = detail.replace(secret, '[REDACTED]')
        detail = re.sub(r'\$2[aby]\$[^\s\x27\x22,]+', '[REDACTED_HASH]', detail)
        (evidence/'setup-failure.txt').write_text(detail, encoding='utf-8')
        for name in state['containers']:
            if name.endswith('-backend'):
                result = docker('exec', name, 'tail', '-60', '/scratch/backend.log', check=False)
                (evidence/'startup-failure.txt').write_text(result.stdout, encoding='utf-8')
        cleanup(state)
        return 1


if __name__ == '__main__':
    if sys.argv[1:] == ['start']:
        raise SystemExit(start())
    if len(sys.argv) == 3 and sys.argv[1] == 'stop':
        state = json.loads(Path(sys.argv[2]).read_text())
        cleanup(state)
    else:
        raise RuntimeError('Use start or stop <owned-state.json>')
