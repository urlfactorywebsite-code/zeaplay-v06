"""The published task contract must describe the first runtime route."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers import tasks
from backend.app.tickets import workflow_router


@pytest.mark.parametrize("path,method", [
    ("/api/tasks/{task_id}", "patch"),
    ("/api/tasks/{task_id}/complete", "post"),
])
def test_openapi_describes_canonical_task_response_not_shadowed_ticket_route(path, method):
    # Match the actual application registration order without starting its
    # seeds, maintenance or external services.
    source = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert source.index('app.include_router(tasks.router, prefix="/api")') < source.index("app.include_router(tickets_workflow_router.router)")
    app = FastAPI()
    app.include_router(tasks.router)
    app.include_router(tasks.router, prefix="/api")
    app.include_router(workflow_router.router)
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    response = schema["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]
    assert response == {"$ref": "#/components/schemas/TaskRead"}
    # Hiding unreachable duplicate documentation must not remove ticket APIs.
    assert "/api/tickets/{ticket_id}/tasks" in schema["paths"]
