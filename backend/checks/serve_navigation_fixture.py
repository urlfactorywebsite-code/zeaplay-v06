"""Local-only disposable server for browser security validation."""
import os
import sys
import tempfile
from pathlib import Path

if os.environ.get("VEE_DATABASE_URL") != "sqlite:///:memory:" or os.environ.get("VEE_ENVIRONMENT") != "test":
    raise RuntimeError("Set isolated VEE_DATABASE_URL and VEE_ENVIRONMENT=test before running")
# Never sign disposable browser sessions with a workstation/production secret.
os.environ['VEE_JWT_SECRET_KEY'] = 'fixture-only-navigation-access-signing-key'
os.environ['VEE_JWT_REFRESH_SECRET_KEY'] = 'fixture-only-navigation-refresh-signing-key'
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.checks.navigation_fixture_app import create_fixture_app
import uvicorn

scratch = Path(tempfile.mkdtemp(prefix="zea-navigation-browser-"))
app = create_fixture_app(scratch / "browser.db")
print(f"Disposable browser fixture database: {scratch}")
uvicorn.run(app, host="127.0.0.1", port=6321, log_level="warning")
