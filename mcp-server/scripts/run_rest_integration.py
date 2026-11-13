"""Own an empty local PostgreSQL cluster, REST app and MCP server; clean only ours."""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import secrets
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres-bin",type=Path,required=True)
    parser.add_argument("--backend-python",type=Path,required=True)
    parser.add_argument("--management-check", action="store_true",
                        help="Also exercise management with real isolated backend sessions")
    parser.add_argument('--oauth-schema-approved', help='Explicitly approved disposable Phase4A SQL SHA256')
    args = parser.parse_args()
    if args.oauth_schema_approved and args.management_check:
        raise SystemExit('Use separate Phase3 and Phase4A contract runs')
    repo = Path(__file__).resolve().parents[2]
    pg = args.postgres_bin.resolve()
    backend_python = args.backend_python.resolve()
    for exe in ("postgres","initdb","pg_ctl","createdb"):
        if not (pg/(exe+".exe")).is_file():
            raise SystemExit("Missing PostgreSQL test binaries")
    root = Path(tempfile.mkdtemp(prefix="zea-phase2b-integration-")).resolve()
    if os.name == "nt":
        who = subprocess.run(["whoami","/user","/fo","csv","/nh"],capture_output=True,text=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        sid = next(csv.reader([who.stdout.strip()]))[1]
        if not re.fullmatch(r"S-1-[0-9-]+",sid):
            raise SystemExit("Could not identify test-directory owner")
        subprocess.run(["icacls",str(root),"/inheritance:r","/grant:r",f"*{sid}:(OI)(CI)F"],capture_output=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        root.chmod(0o700)
    run = uuid.uuid4().hex
    (root/"owned.json").write_text(json.dumps({"run_id":run}))
    env = {k:v for k,v in os.environ.items() if k.upper() in {"SYSTEMROOT","WINDIR","PATH","TEMP","TMP","COMSPEC"}}
    db_pass = secrets.token_urlsafe(32)
    db_port,api_port,mcp_port = port(),port(),port()
    assert len({db_port,api_port,mcp_port}) == 3
    env.update(PGPASSWORD=db_pass,PGSSLMODE="disable")
    config = {"mode":"isolated-test","run_id":run,"backend_origin":f"http://127.0.0.1:{api_port}",
        "attestation_secret":secrets.token_hex(32),"accounts":{a:{"email":a+"@phase2b.example.com",
        "password":secrets.token_urlsafe(24),"capability":secrets.token_urlsafe(32)}
        for a in ("a-member","a-peer","a-manager","a-owner","b-member")}}
    if args.oauth_schema_approved:
        approved_sql = repo/'backend/mcp_migrations/phase4a.sql'
        if hashlib.sha256(approved_sql.read_bytes()).hexdigest() != args.oauth_schema_approved:
            raise SystemExit('Schema differs from explicit approval')
        config['oauth_service_secret'] = secrets.token_urlsafe(48)
    (root/"broker.json").write_text(json.dumps({k:v for k,v in config.items() if k != 'oauth_service_secret'}))
    (root/"pg-password.txt").write_text(db_pass)
    children=[]; logs=[]; started=False; exit_code=1; command_count=0
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    def command(argv, child_env=env):
        nonlocal command_count
        command_count+=1
        output=root/("setup-"+str(command_count)+".log")
        # A daemon can inherit Windows PIPE handles after pg_ctl exits. Use
        # owned files so waiting on the setup command cannot wait on the DB.
        with output.open("w") as log:
            result=subprocess.run([str(v) for v in argv],env=child_env,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=120,creationflags=flags)
        if result.returncode:
            (root/"setup-error.txt").write_text(output.read_text(errors="replace").replace(db_pass,"[REDACTED]"))
            raise RuntimeError("Disposable setup command failed; see restricted run evidence")
        return result
    def spawn(argv,child_env,name):
        log=(root/name).open("w");logs.append(log)
        child=subprocess.Popen([str(v) for v in argv],cwd=root,env=child_env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
        children.append(child);return child
    try:
        command([pg/"initdb.exe","-D",root/"data","-U","zea_phase2b","-A","scram-sha-256","--pwfile",root/"pg-password.txt","--encoding=UTF8","--no-locale"])
        command([pg/"pg_ctl.exe","-D",root/"data","-l",root/"postgres.log","-o",f"-h 127.0.0.1 -p {db_port} -F -c timezone=UTC -c max_connections=30","-w","start"])
        started=True
        command([pg/"createdb.exe","-h","127.0.0.1","-p",str(db_port),"-U","zea_phase2b","zea_phase2b"])
        backend_env={**env,"TEMP":str(root),"TMP":str(root),"PYTHONDONTWRITEBYTECODE":"1",
            "VEE_DATABASE_URL":f"postgresql+psycopg2://zea_phase2b:{db_pass}@127.0.0.1:{db_port}/zea_phase2b",
            "VEE_JWT_SECRET_KEY":secrets.token_hex(48),"VEE_JWT_REFRESH_SECRET_KEY":secrets.token_hex(48),
            "VEE_AI_WEBHOOK_URL":"","VEE_ENABLE_N8N_FORWARDING":"false","VEE_MEDIA_ROOT":str(root/"media"),
            "VEE_CORS_ALLOW_ORIGINS":'["http://127.0.0.1"]',
            "VEE_ENVIRONMENT":"phase2b-isolated","ZEA_ALEMBIC_MIGRATION":"1",
            "ZEA_PHASE2B_RUN":run,"ZEA_PHASE2B_ROOT":str(root),"ZEA_PHASE2B_REPO":str(repo),
            "ZEA_PHASE2B_DB_PORT":str(db_port),"ZEA_PHASE2B_API_PORT":str(api_port),
            "ZEA_PHASE2B_ATTESTATION":config["attestation_secret"]}
        if args.oauth_schema_approved:
            backend_env.update(ZEA_MCP_PHASE4A_ISOLATED='1', ZEA_MCP_SCHEMA_APPROVED=args.oauth_schema_approved,
                ZEA_MCP_BACKEND_ORIGIN=config['backend_origin'], ZEA_MCP_RESOURCE_ORIGIN=f'http://127.0.0.1:{mcp_port}',
                ZEA_MCP_FRONTEND_ORIGIN=config['backend_origin'], ZEA_MCP_SERVICE_SECRET=config['oauth_service_secret'])
        fixture=repo/"backend/security_tests/mcp_phase2b_backend.py"
        command([backend_python,"-I","-B",fixture,"init"],backend_env)
        backend=spawn([backend_python,"-I","-B",fixture,"serve"],backend_env,"backend.log")
        # Readiness touches only this run's reserved origin and attestation path.
        ready=False
        for _ in range(100):
            if backend.poll() is not None:break
            try:
                with urllib.request.urlopen(config["backend_origin"]+"/__phase2b__/attest?nonce="+"0"*64,timeout=1) as response:
                    ready=json.loads(response.read())["run_id"] == run
                if ready:break
            except Exception:time.sleep(.1)
        if not ready:raise RuntimeError("Disposable REST backend not ready")
        if args.management_check:
            management = subprocess.run([backend_python, "-I", "-B",
                str(repo/"backend/security_tests/mcp_phase3_http.py"), str(root)],
                cwd=root, env=backend_env, capture_output=True, text=True,
                timeout=90, creationflags=flags)
            (root/"management-client.txt").write_text(management.stdout+management.stderr)
            print(management.stdout.strip(), flush=True)
            if management.returncode:
                raise RuntimeError("Isolated MCP management checks failed")
        mcp_env={k:v for k,v in env.items() if not k.startswith("PG")}
        mcp_env.update(ZEAPLAY_MCP_TIMEOUT_SECONDS="5",PYTHONDONTWRITEBYTECODE="1")
        http=spawn([sys.executable,"-I","-B","-m","zeaplay_mcp","--mode","rest","--isolated-test",
            "--broker-config",root/"broker.json","--transport","http","--port",str(mcp_port)],mcp_env,"mcp-http.jsonl")
        http_origin=f"http://127.0.0.1:{mcp_port}"
        ready=False
        for _ in range(200):
            if http.poll() is not None:break
            try:
                urllib.request.urlopen(http_origin+"/mcp",timeout=1)
            except urllib.error.HTTPError as exc:
                if exc.code == 401:ready=True;break
            except Exception:pass
            time.sleep(.1)
        if not ready:raise RuntimeError("Disposable MCP HTTP server not ready")
        result=subprocess.run([sys.executable,"-I","-B",str(Path(__file__).with_name("exercise_rest.py")),str(root),http_origin],cwd=root,env=mcp_env,capture_output=True,text=True,timeout=180,creationflags=flags)
        (root/"protocol-client.txt").write_text(result.stdout+result.stderr)
        print(result.stdout.strip(),flush=True)
        exit_code=result.returncode
        if args.oauth_schema_approved and exit_code == 0:
            http.terminate(); http.wait(timeout=15)
            oauth_config = {'mode': 'isolated-oauth', 'backend_origin': config['backend_origin'],
                'resource_origin': http_origin, 'frontend_origin': config['backend_origin'],
                'service_secret': config['oauth_service_secret']}
            (root/'oauth.json').write_text(json.dumps(oauth_config))
            oauth = spawn([sys.executable, '-I', '-B', '-m', 'zeaplay_mcp', '--mode', 'oauth', '--isolated-test',
                '--oauth-config', root/'oauth.json', '--transport', 'http', '--port', str(mcp_port)], mcp_env, 'mcp-oauth.jsonl')
            for _ in range(100):
                if oauth.poll() is not None: break
                try:
                    with urllib.request.urlopen(http_origin+'/.well-known/oauth-protected-resource/mcp', timeout=1) as response:
                        if json.loads(response.read())['resource'] == http_origin+'/mcp': break
                except Exception: time.sleep(.1)
            result = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).with_name('exercise_oauth.py')),
                str(root), http_origin], cwd=root, env=mcp_env, capture_output=True, text=True, timeout=240, creationflags=flags)
            (root/'oauth-client.txt').write_text(result.stdout+result.stderr)
            print(result.stdout.strip(), flush=True)
            exit_code=result.returncode
    except BaseException as exc:
        print(json.dumps({"result":"FAIL","failure_type":type(exc).__name__,"evidence":str(root)}),flush=True)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=15)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        for log in logs:log.close()
        assert json.loads((root/"owned.json").read_text())["run_id"] == run
        pidfile=root/"data/postmaster.pid"
        if pidfile.exists():
            lines=pidfile.read_text().splitlines()
            assert Path(lines[1]).resolve()==(root/"data").resolve() and int(lines[3])==db_port
            command([pg/"pg_ctl.exe","-D",root/"data","-m","fast","-w","stop"])
        cluster_stopped=not pidfile.exists()
        sensitive=[db_pass,config["attestation_secret"],*(x[k] for x in config["accounts"].values() for k in ("password","capability"))]
        sensitive.append(config.get('oauth_service_secret', ''))
        sensitive.extend(locals().get("backend_env",{}).get(k,"") for k in ("VEE_JWT_SECRET_KEY","VEE_JWT_REFRESH_SECRET_KEY"))
        redactions=0
        for artifact in root.iterdir():
            if artifact.is_file() and artifact.suffix in {".log",".txt",".jsonl"} and artifact.name!="pg-password.txt":
                content=artifact.read_text(errors="replace")
                for secret in sensitive:
                    if secret:
                        redactions+=content.count(secret)
                        content=content.replace(secret,"[REDACTED]")
                content,number=re.subn(r"mcp_(?:at|rt|dt)\.[A-Za-z0-9_-]{43}|eyJ[\w-]+\.[\w-]+\.[\w-]+|\$2[aby]\$\d{2}\$[A-Za-z0-9./]{53}","[REDACTED_CREDENTIAL]",content)
                redactions+=number
                artifact.write_text(content)
        # Never remove supplied binaries or another run's files. Keep redacted
        # diagnostics; scrub this run's passwords/capabilities and empty DB only.
        for path in (root/"broker.json",root/"pg-password.txt",root/'oauth.json'):
            path.unlink(missing_ok=True)
        target=(root/"data").resolve()
        assert target.is_relative_to(root) and root.parent==Path(tempfile.gettempdir()).resolve()
        if target.exists():shutil.rmtree(target)
        (root/"cleanup.json").write_text(json.dumps({"run_id":run,"owned_children_stopped":all(c.poll() is not None for c in children),"owned_cluster_stopped":cluster_stopped,"database_removed":not target.exists(),"credential_files_removed":not(root/"broker.json").exists(),"artifact_credential_redactions":redactions,"binaries_untouched":str(pg),"loopback_ports":{"database":db_port,"backend":api_port,"mcp":mcp_port}},indent=2))
        print("Run-owned processes stopped; empty fixture database and credential files removed. Evidence: "+str(root),flush=True)
    return exit_code


if __name__=="__main__":
    raise SystemExit(main())
