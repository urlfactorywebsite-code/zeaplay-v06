"""Build a historical-bootstrap negative control only under an owned stack's www.

No checkout edit. The rest of the current app, auth coordinator and backend remain
unchanged. Vite loader substitutes only getCurrentUser from Git HEAD; provenance
is recorded so the negative control cannot be confused with the tested current UI.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import shutil

repo = Path(__file__).resolve().parents[2]
state = json.loads(Path(sys.argv[1]).read_text())
assert subprocess.check_output(["docker", "inspect", "--format", '{{index .Config.Labels "zea.phase15"}}',
    state["backend"]], text=True).strip() == state["run"]
scratch = Path(state["scratch"]).resolve()
assert scratch.name.startswith("zea-phase15-stack-") and (scratch / "state.json").is_file()
out = (scratch / "www" / "audit-legacy").resolve()
assert out.parent == scratch / "www" and not out.exists()
current = (repo / "frontend/services/mockApi.ts").read_text(encoding="utf8")
historical = subprocess.check_output(["git", "show", "HEAD:frontend/services/mockApi.ts"], cwd=repo, text=True)
def bootstrap(text):
    start = text.index("async getCurrentUser():")
    end = text.index("async getPresenceToken():", start)
    return start, end, text[start:end]
start, end, _ = bootstrap(current)
_, _, old = bootstrap(historical)
assert "clearTokens();" in old and "ECONNABORTED" in old and "sessionIdentity" not in old
substituted = current[:start] + old + current[end:]
source = scratch / "negative-control-mockApi.ts.txt"
source.write_text(substituted, encoding="utf8")
script = "import {readFileSync} from 'node:fs'; import {build} from " + json.dumps((repo / "frontend/node_modules/vite/dist/node/index.js").as_uri()) + "; await build(" + json.dumps({
    "root": str(repo / "frontend"), "configFile": str(repo / "frontend/vite.config.ts"),
    "envDir": str(scratch), "mode": "phase15", "base": "/audit-legacy/",
    "build": {"outDir": str(out)},
})[:-1] + ",plugins:[{name:'historical-bootstrap-negative-control',enforce:'pre',load(id){if(id.replaceAll('\\\\','/').endsWith('/frontend/services/mockApi.ts'))return readFileSync(" + json.dumps(str(source)) + ",'utf8')}}]});"
env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC"}}
env.update(VITE_API_BASE_URL="/api", VITE_API_URL="/api", VITE_PRESENCE_URL="", VITE_CHAT_URL="", VITE_WS_URL="", VITE_TICKET_CHAT_WS_URL="")
with (Path(state["evidence"]) / "negative-control-build.txt").open("w", encoding="utf8") as log:
    result = subprocess.run(["node", "--input-type=module", "-e", script], env=env, cwd=scratch,
        stdout=log, stderr=subprocess.STDOUT, timeout=180)
assert result.returncode == 0
shutil.copyfile(scratch / "www/runtime-config.js", out / "runtime-config.js")
(Path(state["evidence"]) / "negative-control-source.json").write_text(json.dumps({
    "control": "Only historical getCurrentUser substituted in a disposable build; no checkout edit",
    "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
    "historical_bootstrap_sha256": hashlib.sha256(old.encode()).hexdigest(),
    "current_source_sha256": hashlib.sha256(current.encode()).hexdigest(),
    "control_source_sha256": hashlib.sha256(substituted.encode()).hexdigest(),
    "base": "/audit-legacy/", "output_under_owned_www": True,
}, indent=2))
print("PASS: historical bootstrap control built under owned scratch; source unchanged")
