#!/usr/bin/env bash
# Switch only the three application services in the existing taskmanager stack.
# Database startup may update its schema. Rollback restores images, not the DB.
set -Eeuo pipefail
umask 077

fail() { printf '%s\n' "$*" >&2; exit 1; }
for tool in docker python3 git; do
  command -v "$tool" >/dev/null || fail "Missing required command: $tool"
done
docker compose version >/dev/null

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
existing_dir=/opt/taskmanager
project=taskmanager
env_file="$existing_dir/.env.production"
test -f "$env_file" || fail "Existing production settings not found: $env_file"
test -f "$source_dir/docker-compose.github.yml" || fail "Source build overlay is missing"
test "$(docker inspect zea_backend --format '{{index .Config.Labels "com.docker.compose.project"}}')" = "$project" || fail "Backend is not in project taskmanager"
test "$(docker inspect zea_backend --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}')" = "$existing_dir" || fail "Existing Compose folder differs from /opt/taskmanager"
docker exec zea_postgres postgres --version | grep -Eq 'PostgreSQL\) 15\.' || fail "Expected the existing PostgreSQL 15 installation"

config_csv="$(docker inspect zea_backend --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}')"
IFS=',' read -r -a config_files <<< "$config_csv"
test "${#config_files[@]}" -gt 0 || fail "Cannot identify the existing Compose files"
original=(docker compose --project-name "$project" --project-directory "$existing_dir" --env-file "$env_file")
for file in "${config_files[@]}"; do
  test -f "$file" || fail "Existing Compose file is missing: $file"
  original+=(-f "$file")
done

stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
backup="$existing_dir/backups/github-$stamp"
mkdir -p -- "$existing_dir/backups"
mkdir -- "$backup"
chmod 700 "$backup"
cp -p -- "$env_file" "$backup/production.env"
for i in "${!config_files[@]}"; do
  cp -p -- "${config_files[$i]}" "$backup/compose-$i.yml"
done
docker inspect zea_backend zea_frontend zea_presence zea_postgres zea_redis zea_celery_worker zea_reporting_worker > "$backup/containers.json"
if ! docker exec zea_backend python -c 'import os; from app.config import settings; print(os.path.abspath(settings.media_root))' > "$backup/media-path" 2> "$backup/media-path.err"; then
  fail "Cannot identify the existing media folder; details are in the private backup folder: $backup"
fi

export ZEAPLAY_SOURCE_DIR="$source_dir"
python3 - "$backup" "$existing_dir" "$stamp" <<'PY'
import json, pathlib, posixpath, subprocess, sys
backup, existing, stamp = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
containers = {c['Name'].lstrip('/'): c for c in json.loads((backup/'containers.json').read_text())}
approved = ['https://todoplay.urlfactory.website', 'https://play.zeacrm.com', 'https://playapi.zeacrm.com']
def env(name):
    return dict(item.split('=', 1) for item in containers[name]['Config'].get('Env', []) if '=' in item)
def origins(raw):
    if not raw.strip(): return []
    result = json.loads(raw) if raw.lstrip().startswith('[') else raw.split(',')
    if not isinstance(result, list) or not all(isinstance(v, str) for v in result):
        raise SystemExit('Invalid existing CORS configuration; no services changed')
    return list(dict.fromkeys([v.strip() for v in result if v.strip()] + approved))
backend, frontend, presence = env('zea_backend'), env('zea_frontend'), env('zea_presence')
backend_origins = origins(backend.get('VEE_CORS_ALLOW_ORIGINS', '')) or approved
presence_origins = origins(presence.get('PRESENCE_CORS_ORIGINS', presence.get('CORS_ORIGINS', ''))) or approved
media = (backup/'media-path').read_text().strip()
if not media.startswith('/') or media in ('/', '/app') or '\n' in media or posixpath.normpath(media) != media:
    raise SystemExit('Unexpected media path; no services changed')
if not any(m.get('Name') == 'taskmanager_postgres_data' and m['Destination'] == '/var/lib/postgresql/data' for m in containers['zea_postgres']['Mounts']):
    raise SystemExit('PostgreSQL volume differs from the confirmed taskmanager volume')
for name, code_path in [('zea_backend','/app/app'), ('zea_presence','/app/src'), ('zea_frontend','/usr/share/nginx/html')]:
    for mount in containers[name]['Mounts']:
        dest = mount['Destination'].rstrip('/') or '/'
        if code_path == dest or code_path.startswith(dest.rstrip('/')+'/') or dest.startswith(code_path+'/'):
            raise SystemExit('An existing mount covers application code in '+name+'; inspect it before switching')
covered = any(media == m['Destination'].rstrip('/') or media.startswith(m['Destination'].rstrip('/')+'/') for m in containers['zea_backend']['Mounts'])
settings = {'services': {
    'backend': {'environment': {'VEE_CORS_ALLOW_ORIGINS':json.dumps(backend_origins), 'VEE_MEDIA_ROOT':media}},
    'presence': {'environment': {'PRESENCE_CORS_ORIGINS':','.join(presence_origins)}}}}
rollback = {'services': {}}
for service in ['backend','frontend','presence']:
    tag = 'zeaplay-rollback/'+service+':'+stamp
    subprocess.run(['docker','image','tag',containers['zea_'+service]['Image'],tag],check=True)
    rollback['services'][service] = {'image':tag}
if not covered:
    media_store = existing/'source-data'/('github-'+stamp)/'media'
    media_store.mkdir(parents=True, exist_ok=False)
    mount = {'type':'bind','source':str(media_store),'target':media}
    settings['services']['backend']['volumes'] = [mount]
    rollback['services']['backend']['volumes'] = [mount]
    rollback['services']['backend']['environment'] = {'VEE_MEDIA_ROOT':media}
    (backup/'media-store').write_text(str(media_store))
presence_url = frontend.get('PRESENCE_URL', '').strip()
if not presence_url:
    raise SystemExit('Existing frontend PRESENCE_URL is empty; confirm its endpoint before switching')
chat_url = frontend.get('CHAT_URL', '').strip() or presence_url
settings['services']['frontend'] = {
    'environment': {'PRESENCE_URL':presence_url,'CHAT_URL':chat_url},
    # The live API serves /health and /auth directly; /api/health returns 404.
    'build': {'args': {'VITE_API_BASE_URL':'https://playapi.zeacrm.com',
                       'VITE_API_URL':'https://playapi.zeacrm.com',
                       'VITE_PRESENCE_URL':presence_url,'VITE_CHAT_URL':chat_url}}}
for filename, data in [('source-runtime.json', settings), ('rollback.json', rollback)]:
    (backup/filename).write_text(json.dumps(data, indent=2))
print('PASS: existing volume, source mounts, CORS and rollback image checks')
PY

source_compose=("${original[@]}" -f "$source_dir/docker-compose.github.yml" -f "$backup/source-runtime.json")
rollback_compose=("${original[@]}" -f "$backup/rollback.json")
{
  printf '#!/usr/bin/env bash\nset -Eeuo pipefail\n'
  printf 'export ZEAPLAY_SOURCE_DIR=%q\n' "$source_dir"
  printf '%q ' "${rollback_compose[@]}" up -d --no-deps --no-build --pull never backend frontend presence
  printf '\n'
} > "$backup/rollback.sh"
chmod 700 "$backup/rollback.sh"

"${source_compose[@]}" config --quiet
"${source_compose[@]}" config --format json > "$backup/planned.json"
python3 - "$backup" <<'PY'
import json, pathlib, sys
b = pathlib.Path(sys.argv[1])
planned = json.loads((b/'planned.json').read_text())
actual = {c['Name'].lstrip('/'):c for c in json.loads((b/'containers.json').read_text())}
pg = planned['services']['postgres']
if pg.get('image') != actual['zea_postgres']['Config']['Image']:
    raise SystemExit('Existing Compose PostgreSQL image differs from its running container; no services changed')
def postgres_volume(p):
    source=p.get('source', '')
    return planned.get('volumes',{}).get(source,{}).get('name',source)
if not any(p.get('type')=='volume' and p.get('target')=='/var/lib/postgresql/data' and postgres_volume(p)=='taskmanager_postgres_data' for p in pg.get('volumes',[])):
    raise SystemExit('Existing Compose PostgreSQL volume differs from taskmanager_postgres_data; no services changed')
for service in ['backend','frontend','presence']:
    mounts = planned['services'][service].get('volumes', [])
    def address(value): return '*' if value in ('', None, '0.0.0.0', '::') else value
    expected_ports = {(str(p['target']),p.get('protocol','tcp'),str(p['published']),address(p.get('host_ip'))) for p in planned['services'][service].get('ports',[]) if p.get('published')}
    current_ports = set()
    for target, bindings in actual['zea_'+service].get('NetworkSettings',{}).get('Ports',{}).items():
        number, protocol = target.split('/')
        for binding in bindings or []:
            current_ports.add((number,protocol,binding['HostPort'],address(binding.get('HostIp'))))
    if expected_ports != current_ports:
        raise SystemExit('Existing '+service+' port bindings differ from its Compose files; no services changed')
    for m in actual['zea_'+service]['Mounts']:
        def same(p):
            if p['target'] != m['Destination'] or p['type'] != m['Type']: return False
            source = p.get('source', '')
            if m['Type']=='volume': source=planned.get('volumes',{}).get(source,{}).get('name',source)
            return source == (m.get('Name') if m['Type']=='volume' else m['Source'])
        if not any(same(p) for p in mounts):
            raise SystemExit('Existing '+service+' data mount is missing from its Compose files; no services changed')
print('PASS: application data mounts and PostgreSQL image preserved')
PY

printf '%s\n' 'Building source images; the existing application is still running.'
"${source_compose[@]}" build backend frontend presence

printf '%s\n' 'Backing up PostgreSQL before the switch.'
docker exec zea_postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup/database.dump"
test -s "$backup/database.dump" || fail "Database backup is empty; no services changed"
docker exec -i zea_postgres pg_restore --list < "$backup/database.dump" > /dev/null

phase=stopping
recover() {
  result=$?
  trap - ERR
  printf 'Deployment failed. Backup: %s\n' "$backup" >&2
  if test "$phase" = recreating; then
    bash "$backup/rollback.sh" || printf 'Automatic image rollback failed; run: bash %q\n' "$backup/rollback.sh" >&2
    printf '%s\n' 'Image rollback does not undo database schema changes. The database dump is available for manual recovery.' >&2
  else
    "${original[@]}" start backend frontend presence || true
  fi
  exit "$result"
}
trap recover ERR
"${original[@]}" stop backend frontend presence
media_path="$(cat "$backup/media-path")"
docker cp "zea_backend:$media_path" "$backup/backend-media"
if test -f "$backup/media-store"; then
  docker cp "zea_backend:$media_path/." "$(cat "$backup/media-store")/"
fi
phase=recreating
"${source_compose[@]}" up -d --no-deps --no-build --pull never backend frontend presence

healthy=0
for attempt in $(seq 1 60); do
  if docker exec zea_backend python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:6211/health",timeout=5)' > /dev/null 2>&1 &&
     docker exec zea_presence node -e 'fetch("http://127.0.0.1:6212/health",{signal:AbortSignal.timeout(5000)}).then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))' > /dev/null 2>&1 &&
     docker exec zea_frontend wget -T 5 -q -O /dev/null http://127.0.0.1/ > /dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 2
done
test "$healthy" = 1
docker exec -i zea_backend python - <<'PY'
import urllib.request, urllib.error
for origin in ['https://todoplay.urlfactory.website','https://play.zeacrm.com']:
    request=urllib.request.Request('http://127.0.0.1:6211/health',method='OPTIONS',headers={'Origin':origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type'})
    with urllib.request.urlopen(request,timeout=5) as response:
        assert response.status==200 and response.headers.get('Access-Control-Allow-Origin')==origin
print('PASS: running source backend CORS for both frontend domains')
PY
docker exec zea_presence node -e '(async()=>{for(const origin of ["https://todoplay.urlfactory.website","https://play.zeacrm.com"]){const r=await fetch("http://127.0.0.1:6212/socket.io/?EIO=4&transport=polling",{method:"OPTIONS",headers:{Origin:origin,"Access-Control-Request-Method":"GET"},signal:AbortSignal.timeout(5000)});if(!r.ok||r.headers.get("access-control-allow-origin")!==origin)throw new Error("Presence CORS check failed");}console.log("PASS: running source presence CORS for both frontend domains")})().catch(e=>{console.error(e.message);process.exit(1)})'
python3 - "$backup" <<'PY'
import json, pathlib, subprocess, sys
before={c['Name'].lstrip('/'):c['Id'] for c in json.loads((pathlib.Path(sys.argv[1])/'containers.json').read_text())}
for name in ['zea_postgres','zea_redis','zea_celery_worker','zea_reporting_worker']:
    current=subprocess.check_output(['docker','inspect',name,'--format','{{.Id}}'],text=True).strip()
    assert before[name]==current, name+' was unexpectedly recreated'
print('PASS: PostgreSQL, Redis and existing workers were not recreated')
PY
trap - ERR
"${source_compose[@]}" ps backend frontend presence
printf '\nBackup: %s\nImage rollback: bash %q\n' "$backup" "$backup/rollback.sh"
printf '%s\n' 'Keep this private backup folder: it also contains deployment settings used by the running services.'
printf '%s\n' 'The existing unhealthy worker images were not changed. External HTTPS/reverse-proxy checks remain separate.'
