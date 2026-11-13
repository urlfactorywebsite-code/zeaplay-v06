"""The published task contract must describe the first runtime route."""
from pathlib import Path
from collections import Counter

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

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
    assert source.index('app.include_router(tasks.router, prefix="/api")') < source.index("app.include_router(tickets_workflow_router.application_router)")
    app = FastAPI()
    app.include_router(tasks.router)
    app.include_router(tasks.router, prefix="/api")
    app.include_router(workflow_router.application_router)
    matches = [route for route in app.routes if isinstance(route, APIRoute)
               and route.path == path and method.upper() in route.methods]
    assert len(matches) == 1
    assert matches[0].endpoint is (tasks.update_task if method == 'patch' else tasks.complete_task)
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    response = schema["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]
    assert response == {"$ref": "#/components/schemas/TaskRead"}
    # Removing shadowed registrations must not remove ticket APIs.
    assert "/api/tickets/{ticket_id}/tasks" in schema["paths"]


def test_combined_application_has_unique_http_and_websocket_dispatch():
    from backend.app.main import app
    from fastapi.routing import APIWebSocketRoute
    http = Counter((route.path, method) for route in app.routes if isinstance(route, APIRoute)
                   for method in route.methods)
    sockets = Counter(route.path for route in app.routes if isinstance(route, APIWebSocketRoute))
    assert all(count == 1 for count in http.values())
    assert all(count == 1 for count in sockets.values())


def test_standalone_ticket_compatibility_preserves_both_legacy_handlers():
    routes = {route.endpoint: route for route in workflow_router.router.routes}
    assert routes[workflow_router.update_ticket_task_handler].path == '/api/tasks/{task_id}'
    assert routes[workflow_router.complete_ticket_task_handler].path == '/api/tasks/{task_id}/complete'
    omitted = {route.endpoint for route in workflow_router.router.routes} - {
        route.endpoint for route in workflow_router.application_router.routes}
    assert omitted == {workflow_router.update_ticket_task_handler, workflow_router.complete_ticket_task_handler}
