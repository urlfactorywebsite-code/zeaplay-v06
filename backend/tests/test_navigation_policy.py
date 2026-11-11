"""Real SQLite transactions; no shared database, application startup, or network."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.database import get_db
from backend.app.dependencies import get_current_active_user
from backend.app.navigation_guard import enforce_navigation_policy
from backend.app.navigation_registry import BY_ID, default_rules
from backend.app.routers import support
from backend.app.routers.navigation import router


@pytest.fixture
def harness(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'policy.db'}", connect_args={"check_same_thread": False})
    # Existing audit actor FK resolves to the real users table, but does not need
    # the rest of this legacy application's schema for isolated policy tests.
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
    models.NavigationPolicy.__table__.create(engine)
    models.AuditLog.__table__.create(engine)
    identity = SimpleNamespace(id="fixture-owner", tenant_id=uuid.uuid4(), role=models.RoleEnum.OWNER, status=models.UserStatusEnum.ACTIVE)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users(id) VALUES ('fixture-owner')"))
    app = FastAPI(dependencies=[Depends(enforce_navigation_policy)])
    app.include_router(router)
    app.include_router(router, prefix="/api")
    app.include_router(support.router)
    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_active_user] = lambda: identity
    async def current_user(token, db):
        return identity
    monkeypatch.setattr("backend.app.navigation_guard.get_current_user", current_user)
    for path in ("/tickets", "/api/tickets", "/tool-library/tools", "/config/api", "/media/list", "/tasks", "/tasks/calendar/tasks", "/tasks/kanban", "/logs/audit"):
        app.get(path)(lambda: {"data": "fixture"})
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer fixture"
        yield client, identity, engine
    engine.dispose()


def policy(client):
    response = client.get("/navigation")
    assert response.status_code == 200
    return response.json()


def payload(client):
    value = policy(client)
    return {"version": value["version"], "pages": {page["id"]: {key: page[key] for key in ("enabled", "hidden", "allowedRoles")} for page in value["pages"]}}


def test_defaults_and_registry_are_safe_and_unique(harness):
    client, user, _ = harness
    value = policy(client)
    assert value["version"] == 0 and value["tenantId"] == str(user.tenant_id)
    assert len(value["pages"]) == len(BY_ID)
    # The sidebar parent and its protected default tab intentionally share /tasks.
    assert len({page["route"] for page in value["pages"]}) == len(BY_ID) - 1
    assert BY_ID["tasks.list"]["route"] == BY_ID["tasks"]["route"] == "/tasks"
    assert len([page for page in value["pages"] if page["navigationLocation"] == "settings-tab"]) == 7


@pytest.mark.parametrize("role", list(models.RoleEnum))
def test_api_and_management_ceilings_cannot_be_bypassed(harness, role):
    client, user, _ = harness
    user.role = role
    pages = {page["id"]: page for page in policy(client)["pages"]}
    assert pages["settings.api"]["visible"] == (role in (models.RoleEnum.OWNER, models.RoleEnum.ADMIN))
    assert pages["settings.sidebar-management"]["visible"] == (role in (models.RoleEnum.ADMIN, models.RoleEnum.OWNER))
    assert pages["settings.profile"]["access"] == "allowed"


def test_atomic_persistence_metadata_audit_and_fresh_session(harness):
    client, user, engine = harness
    value = payload(client)
    value["pages"]["tickets"]["enabled"] = False
    response = client.put("/navigation", json=value)
    assert response.status_code == 200
    assert response.json()["version"] == 1 and response.json()["updatedBy"] == user.id
    assert response.json()["updatedAt"]
    with Session(engine) as independent_session:
        assert independent_session.get(models.NavigationPolicy, str(user.tenant_id)).pages["tickets"]["enabled"] is False
        event = independent_session.scalars(select(models.AuditLog)).one()
        assert event.action == "NAVIGATION_POLICY_UPDATED"
        assert event.before["tickets"]["enabled"] is True
        assert event.after["tickets"]["enabled"] is False
        assert event.metadata_payload["tenant_id"] == str(user.tenant_id)


def test_cross_tenant_reads_and_updates_are_isolated(harness):
    client, user, _ = harness
    tenant_a = user.tenant_id
    value = payload(client)
    value["pages"]["tickets"]["enabled"] = False
    assert client.put("/navigation", json=value).status_code == 200
    user.tenant_id = uuid.uuid4()
    other = policy(client)
    assert other["version"] == 0
    assert next(page for page in other["pages"] if page["id"] == "tickets")["enabled"] is True
    other_update = payload(client)
    other_update["pages"]["reports"]["hidden"] = True
    assert client.put("/navigation", json=other_update).status_code == 200
    user.tenant_id = tenant_a
    own = {page["id"]: page for page in policy(client)["pages"]}
    assert own["tickets"]["enabled"] is False and own["reports"]["hidden"] is False


@pytest.mark.parametrize("key", ["settings", "settings.profile", "settings.sidebar-management", "tasks.list"])
@pytest.mark.parametrize("change", ["disable", "hide", "narrow"])
def test_protected_recovery_pages_cannot_be_modified(harness, key, change):
    client, _, _ = harness
    value = payload(client)
    value["pages"][key][{"disable": "enabled", "hide": "hidden", "narrow": "allowedRoles"}[change]] = {"disable": False, "hide": True, "narrow": []}[change]
    assert client.put("/navigation", json=value).status_code == 422
    assert policy(client)["version"] == 0


def test_task_registry_consolidates_navigation_and_preserves_ceilings(harness):
    client, _, _ = harness
    entries = {page["id"]: page for page in policy(client)["pages"]}
    assert entries["tasks"]["navigationLocation"] == "sidebar"
    tabs = [page for page in entries.values() if page["navigationLocation"] == "task-tab"]
    assert [page["id"] for page in tabs] == ["tasks.list", "kanban", "gantt", "calendar"]
    assert all(page["parentId"] == "tasks" for page in tabs)
    assert {page["route"] for page in tabs} == {"/tasks", "/tasks/kanban", "/tasks/gantt", "/tasks/calendar"}
    assert entries["gantt"]["permittedRoles"] == ["manager", "admin", "owner"]
    assert entries["tasks.list"]["isSystemProtected"]


def test_existing_task_policy_ids_keep_their_rules_without_database_migration(harness):
    client, user, engine = harness
    legacy = default_rules()
    legacy.pop("tasks.list")
    legacy["kanban"]["enabled"] = False
    legacy["gantt"]["hidden"] = True
    legacy["calendar"]["allowedRoles"] = ["owner"]
    with Session(engine) as db:
        db.add(models.NavigationPolicy(tenant_id=str(user.tenant_id), pages=legacy, version=7, updated_by=user.id, updated_at=datetime.now(timezone.utc)))
        db.commit()
    value = policy(client)
    entries = {page["id"]: page for page in value["pages"]}
    assert value["version"] == 7
    assert entries["kanban"]["access"] == "disabled"
    assert entries["gantt"]["hidden"]
    assert entries["calendar"]["allowedRoles"] == ["owner"]
    assert entries["tasks.list"]["access"] == "allowed"


def test_task_parent_restrictions_apply_to_all_nested_tabs(harness):
    client, _, _ = harness
    value = payload(client)
    value["pages"]["tasks"]["enabled"] = False
    assert client.put("/navigation", json=value).status_code == 200
    entries = {page["id"]: page for page in policy(client)["pages"]}
    assert all(entries[key]["access"] == "disabled" for key in ("tasks.list", "kanban", "gantt", "calendar"))
    assert client.get("/tasks/kanban").status_code == 403
    assert client.get("/tasks/calendar/tasks").status_code == 403


def test_gantt_role_ceiling_cannot_be_expanded_by_task_visibility(harness):
    client, user, _ = harness
    value = payload(client)
    value["pages"]["gantt"]["allowedRoles"].append("user")
    assert client.put("/navigation", json=value).status_code == 422
    user.role = models.RoleEnum.USER
    entries = {page["id"]: page for page in policy(client)["pages"]}
    assert entries["gantt"]["access"] == "forbidden"
    assert entries["tasks.list"]["access"] == "allowed"


@pytest.mark.parametrize("change", ["unknown-page", "unknown-role", "escalation", "duplicate-role", "extra-field", "missing-page", "boolean-coercion"])
def test_invalid_configuration_is_rejected_without_partial_save(harness, change):
    client, _, _ = harness
    value = payload(client)
    value["pages"]["tickets"]["enabled"] = False
    if change == "unknown-page": value["pages"]["made-up"] = value["pages"]["tickets"]
    if change == "unknown-role": value["pages"]["tickets"]["allowedRoles"] = ["superuser"]
    if change == "escalation": value["pages"]["settings.api"]["allowedRoles"] = ["owner", "user"]
    if change == "duplicate-role": value["pages"]["tickets"]["allowedRoles"] = ["owner", "owner"]
    if change == "extra-field": value["tenant_id"] = str(uuid.uuid4())
    if change == "missing-page": del value["pages"]["reports"]
    if change == "boolean-coercion": value["pages"]["tickets"]["enabled"] = "false"
    assert client.put("/navigation", json=value).status_code == 422
    assert policy(client)["version"] == 0


@pytest.mark.parametrize("role", [models.RoleEnum.USER, models.RoleEnum.MANAGER])
def test_nonadministrators_cannot_update(harness, role):
    client, user, _ = harness
    value = payload(client)
    user.role = role
    assert client.put("/navigation", json=value).status_code == 403


def test_admin_can_hide_but_cannot_change_availability_or_roles(harness):
    client, user, _ = harness
    user.role = models.RoleEnum.ADMIN
    value = payload(client)
    value["pages"]["tickets"]["hidden"] = True
    assert client.put("/navigation", json=value).status_code == 200
    value = payload(client)
    value["pages"]["tickets"]["enabled"] = False
    assert client.put("/navigation", json=value).status_code == 403
    value = payload(client)
    value["pages"]["tickets"]["allowedRoles"] = ["admin"]
    assert client.put("/navigation", json=value).status_code == 403


def test_stale_and_first_save_conflicts_do_not_overwrite(harness):
    client, _, _ = harness
    old = payload(client)
    assert client.put("/navigation", json=old).status_code == 200
    old["pages"]["tickets"]["enabled"] = False
    assert client.put("/navigation", json=old).status_code == 409
    newer = payload(client)
    assert client.put("/navigation", json=newer).status_code == 200
    assert client.put("/navigation", json=newer).status_code == 409
    assert next(page for page in policy(client)["pages"] if page["id"] == "tickets")["enabled"] is True


def test_api_aliases_and_direct_requests_respect_disable_hidden_and_forbidden(harness):
    client, user, _ = harness
    value = payload(client)
    value["pages"]["tickets"]["enabled"] = False
    value["pages"]["tool-library"]["hidden"] = True
    value["pages"]["settings.logs"]["allowedRoles"] = ["owner"]
    assert client.put("/navigation", json=value).status_code == 200
    user.role = models.RoleEnum.ADMIN
    for path in ("/tickets", "/api/tickets"):
        response = client.get(path)
        assert response.status_code == 403 and response.json()["detail"]["code"] == "module_disabled"
    assert client.get("/tool-library/tools").status_code == 200
    assert client.get("/logs/audit").json()["detail"]["code"] == "module_forbidden"


def test_shared_task_views_do_not_break_and_specific_endpoints_are_guarded(harness):
    client, _, _ = harness
    value = payload(client)
    value["pages"]["calendar"]["enabled"] = False
    value["pages"]["kanban"]["enabled"] = False
    assert client.put("/navigation", json=value).status_code == 200
    assert client.get("/tasks").status_code == 200
    assert client.get("/tasks/calendar/tasks").status_code == 403
    assert client.get("/tasks/kanban").status_code == 403
    value = payload(client)
    for key in ("tasks", "gantt", "dashboard"): value["pages"][key]["enabled"] = False
    assert client.put("/navigation", json=value).status_code == 200
    assert client.get("/tasks").status_code == 403


def test_parent_disable_blocks_child_and_hidden_parent_only_hides_navigation(harness):
    client, _, _ = harness
    value = payload(client)
    value["pages"]["achievements"]["hidden"] = True
    assert client.put("/navigation", json=value).status_code == 200
    child = next(page for page in policy(client)["pages"] if page["id"] == "levels")
    assert child["access"] == "allowed" and child["visible"] is False
    value = payload(client)
    value["pages"]["achievements"]["enabled"] = False
    assert client.put("/navigation", json=value).status_code == 200
    assert next(page for page in policy(client)["pages"] if page["id"] == "levels")["access"] == "disabled"


def test_independent_credentials_permissions_are_not_granted_by_page_rules(harness):
    client, user, _ = harness
    value = payload(client)
    value["pages"]["settings.api"]["enabled"] = False
    assert client.put("/navigation", json=value).status_code == 200
    user.role = models.RoleEnum.ADMIN
    assert client.get("/config/api").status_code == 403


def test_unavailable_policy_storage_fails_closed(harness):
    client, _, engine = harness
    models.NavigationPolicy.__table__.drop(engine)
    assert client.get("/navigation").status_code == 503
    assert client.get("/tickets").status_code == 503


def test_migration_upgrade_and_downgrade_on_disposable_database(monkeypatch):
    import importlib
    migration = importlib.import_module("backend.alembic.versions.a8d6e4f2c0b1_add_navigation_policies")
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        operations = Operations(MigrationContext.configure(conn))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()
        conn.execute(text("SELECT tenant_id, pages, version, updated_by, updated_at FROM navigation_policies"))
        migration.downgrade()
        assert "navigation_policies" not in __import__('sqlalchemy').inspect(conn).get_table_names()
    engine.dispose()


def test_policy_and_audit_rollback_together_on_audit_failure(harness):
    client, _, engine = harness
    with engine.begin() as conn:
        conn.execute(text("CREATE TRIGGER reject_audit BEFORE INSERT ON audit_logs BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"))
    value = payload(client)
    value["pages"]["tickets"]["enabled"] = False
    assert client.put("/navigation", json=value).status_code == 503
    assert policy(client)["version"] == 0


def test_navigation_audit_records_never_cross_tenants(harness):
    from backend.app.routers.logs import _apply_scope_filters
    client, user, engine = harness
    assert client.put("/navigation", json=payload(client)).status_code == 200
    tenant_a = user.tenant_id
    user.tenant_id = uuid.uuid4()
    assert client.put("/navigation", json=payload(client)).status_code == 200
    with Session(engine) as db:
        records = db.scalars(_apply_scope_filters(select(models.AuditLog), current_user=user, db=db)).all()
        assert len(records) == 1 and records[0].entity_id == str(user.tenant_id)
    user.tenant_id = tenant_a


def test_support_proxy_preserves_payload_and_authenticates_sender(harness, monkeypatch):
    client, user, _ = harness
    captured = {}
    class Upstream:
        def __init__(self, **kwargs): captured.update(options=kwargs)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json):
            captured.update(url=url, body=json)
            return SimpleNamespace(is_success=True)
    monkeypatch.setattr(support.httpx, "Client", Upstream)
    body = {"name": "Fixture", "email": "fixture@example.test", "subject": "Help", "category": "Bug", "priority": "Low", "description": "Fixture request", "submittedAt": "2026-10-29T00:00:00Z", "user_id": "spoofed"}
    assert client.post("/support", json=body).status_code == 200
    assert captured["body"]["user_id"] == user.id
    assert captured["body"]["subject"] == "Help"
    assert captured["url"] == support.WEBHOOK_URL
    assert captured["options"]["follow_redirects"] is False
    value = payload(client)
    value["pages"]["settings.support"]["enabled"] = False
    assert client.put("/navigation", json=value).status_code == 200
    captured.clear()
    assert client.post("/support", json=body).status_code == 403
    assert not captured


def test_frontend_safe_registry_fixture_matches_authoritative_registry():
    import json
    from pathlib import Path

    from backend.app.navigation_registry import PAGES
    assert json.loads((Path(__file__).parents[2] / "frontend/checks/navigation-registry.fixture.json").read_text()) == PAGES


def test_postgres_migration_sql_compiles_without_a_database(monkeypatch):
    import importlib
    import io
    migration = importlib.import_module("backend.alembic.versions.a8d6e4f2c0b1_add_navigation_policies")
    buffer = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buffer})
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    sql = buffer.getvalue()
    assert "CREATE TABLE navigation_policies" in sql and "TIMESTAMP WITH TIME ZONE" in sql


def test_simultaneous_updates_have_exactly_one_winner(harness, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from backend.app.routers import navigation
    client, _, _ = harness
    assert client.put("/navigation", json=payload(client)).status_code == 200
    first = payload(client)
    second = payload(client)
    first["pages"]["tickets"]["enabled"] = False
    second["pages"]["reports"]["hidden"] = True
    original = navigation.load_policy
    both_read = Barrier(2, timeout=10)
    def overlapping_read(db, tenant):
        result = original(db, tenant)
        both_read.wait()
        return result
    monkeypatch.setattr(navigation, "load_policy", overlapping_read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda value: client.put("/navigation", json=value), [first, second]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert policy(client)["version"] == 2


@pytest.mark.parametrize("method,path", [("GET", "/navigation"), ("PUT", "/navigation"), ("POST", "/support")])
def test_signed_out_navigation_and_support_requests_are_rejected(method, path):
    app = FastAPI()
    app.include_router(router)
    app.include_router(support.router)
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as client:
        assert client.request(method, path, json={}).status_code == 401
