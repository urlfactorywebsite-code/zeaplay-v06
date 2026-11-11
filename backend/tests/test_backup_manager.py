# ruff: noqa: SIM117
"""Disposable database and private temp files only. Never reads installed data."""

import csv
import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app import models
from backend.app.backups import service as svc
from backend.app.backups.models import BackupJob, ExportPreset
from backend.app.backups.registry import FIELDS
from backend.app.backups.router import router
from backend.app.database import Base, get_db
from backend.app.dependencies import get_current_active_user
from backend.app.routers import data_admin


@pytest.fixture
def harness(tmp_path, monkeypatch):
    test_url = os.environ.get("ZEA_BACKUP_TEST_URL")
    if test_url:
        assert (
            test_url.startswith("postgresql")
            and "127.0.0.1" in test_url
            and test_url.endswith("/zea_backup_disposable")
        ), "Only the named disposable database is allowed"
    engine = create_engine(
        test_url or f"sqlite:///{tmp_path / 'backup.db'}",
        connect_args={} if test_url else {"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        if not test_url:
            connection.create_function(
                "to_tsvector", 2, lambda _language, value: value, deterministic=True
            )
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")

    if test_url:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA public CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA public")
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    Base.metadata.create_all(engine)
    tenant = uuid.uuid4()
    with Session(engine) as db:
        db.add(models.Department(id="dept", name="=1+1, café\nteam"))
        db.add(
            models.User(
                id="owner",
                name="Owner",
                email="owner@example.com",
                tenant_id=tenant,
                hashed_password="NEVER_EXPORT_THIS_CREDENTIAL",
                role=models.RoleEnum.OWNER,
            )
        )
        db.flush()
        db.add(models.Task(id="task", title="Unicode café 🐾", created_by_id="owner"))
        db.flush()
        db.add(
            models.Subtask(id="sub", task_id="task", title="Subtask", completed=False)
        )
        db.commit()
    monkeypatch.setattr(svc, "ROOT", tmp_path / "private")
    monkeypatch.setattr(svc, "SessionLocal", sessionmaker(engine))
    identity = {"role": models.RoleEnum.OWNER, "tenant": tenant, "id": "owner"}
    app = FastAPI()
    app.include_router(router)
    app.include_router(data_admin.router)

    def db_session():
        with Session(engine) as db:
            yield db

    def actor():
        with Session(engine) as db:
            user = db.get(models.User, "owner")
            user.role = identity["role"]
            user.tenant_id = identity["tenant"]
            return user

    app.dependency_overrides[get_db] = db_session
    app.dependency_overrides[get_current_active_user] = actor
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client, engine=engine, tenant=tenant, identity=identity, app=app
        )
    engine.dispose()


BASE = "/admin/data/manager"


def export(h, **patch):
    payload = {
        "scope": "all",
        "datasets": [],
        "format": "csv",
        "packaging": "zip",
        "include_related": True,
        **patch,
    }
    response = h.client.post(BASE + "/exports", json=payload)
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    job = next(
        job for job in h.client.get(BASE + "/jobs").json() if job["id"] == job_id
    )
    assert job["status"] == "Completed", job
    ticket = h.client.post(f"{BASE}/jobs/{job_id}/download-ticket").json()["ticket"]
    response = h.client.get(f"{BASE}/jobs/{job_id}/download", params={"ticket": ticket})
    assert response.status_code == 200, response.text
    return job, response, ticket


def upload(h, content, name="backup.zip", dataset=None):
    response = h.client.post(
        BASE + "/imports/validate",
        files={"file": (name, content)},
        data={"dataset": dataset} if dataset else {},
    )
    return response


def confirm(h, job):
    return h.client.post(
        f"{BASE}/imports/{job['id']}/confirm",
        json={
            "confirmation": "RESTORE",
            "preview_token": job["report"]["preview_token"],
        },
    )


def test_entire_workspace_is_one_complete_zip_with_counts_checksums_and_safe_fields(
    harness,
):
    h = harness
    job, response, ticket = export(h)
    assert response.headers["content-type"] == "application/zip"
    assert "attachment;" in response.headers["content-disposition"]
    assert b"NEVER_EXPORT_THIS_CREDENTIAL" not in response.content
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["completion_status"] == "completed"
        assert len(manifest["selected_datasets"]) == len(FIELDS)
        assert {
            "users",
            "tasks",
            "departments",
            "achievements",
            "rewards",
            "user-rewards",
            "kanban-columns",
            "notifications",
            "tickets",
            "subtasks",
            "task-dependencies",
            "chat-messages",
        } <= set(manifest["files"])
        for entry in manifest["files"].values():
            raw = archive.read(entry["path"])
            assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
            assert len(rows) == entry["record_count"]
            assert "hashed_password" not in entry["fields"]
            assert b"NEVER_EXPORT_THIS_CREDENTIAL" not in raw
        rows = list(
            csv.DictReader(io.StringIO(archive.read("data/departments.csv").decode()))
        )
        assert rows[0]["name"].startswith('"=')
        assert json.loads(rows[0]["name"]) == "=1+1, café\nteam"
        assert manifest["files"]["users"]["record_count"] == 1
    assert (
        h.client.get(
            f"{BASE}/jobs/{job['id']}/download", params={"ticket": ticket}
        ).status_code
        == 403
    )


@pytest.mark.parametrize("fmt", ["csv", "json"])
def test_roundtrip_zip_preview_is_readonly_and_repeated_restore_is_idempotent(
    harness, fmt
):
    h = harness
    _, exported, _ = export(h, format=fmt)
    validated = upload(h, exported.content)
    assert validated.status_code == 200, validated.text
    job = validated.json()
    assert job["report"]["valid"], job
    with Session(h.engine) as db:
        assert (
            db.get(models.User, "owner").hashed_password
            == "NEVER_EXPORT_THIS_CREDENTIAL"
        )
        assert db.get(models.Task, "task").title == "Unicode café 🐾"
    result = confirm(h, job)
    assert result.status_code == 200, result.text
    assert confirm(h, job).status_code == 409
    with Session(h.engine) as db:
        assert len(db.scalars(select(models.Task)).all()) == 1
        assert (
            db.get(models.User, "owner").hashed_password
            == "NEVER_EXPORT_THIS_CREDENTIAL"
        )


def test_custom_selection_dependencies_and_presets_persist(harness):
    h = harness
    settings = {
        "scope": "custom",
        "datasets": ["departments"],
        "format": "json",
        "include_related": True,
    }
    first = h.client.post(
        BASE + "/presets", json={"name": "Weekly", "settings": settings}
    )
    assert first.status_code == 200, first.text
    preset_id = first.json()["id"]
    assert h.client.get(BASE + "/presets").json()[0]["name"] == "Weekly"
    assert (
        h.client.put(
            f"{BASE}/presets/{preset_id}",
            json={"name": "Renamed", "settings": settings},
        ).status_code
        == 200
    )
    assert h.client.post(f"{BASE}/presets/{preset_id}/run").status_code == 202
    with Session(h.engine) as db:
        assert db.get(ExportPreset, preset_id).name == "Renamed"
    _job, response, _ = export(h, **settings)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {"manifest.json", "data/departments.json"}
    assert h.client.delete(f"{BASE}/presets/{preset_id}").status_code == 204
    assert h.client.get(BASE + "/presets").json() == []
    bad = h.client.post(
        BASE + "/exports",
        json={"scope": "custom", "datasets": ["tasks"], "include_related": False},
    )
    assert bad.status_code == 422 and "dependencies" in bad.text


@pytest.mark.parametrize(
    "role", [models.RoleEnum.USER, models.RoleEnum.MANAGER, models.RoleEnum.ADMIN]
)
@pytest.mark.parametrize("endpoint", ["/catalog", "/jobs", "/presets"])
def test_unauthorized_owners_only(harness, role, endpoint):
    harness.identity["role"] = role
    assert harness.client.get(BASE + endpoint).status_code == 403


def test_cross_tenant_exports_imports_presets_and_downloads_are_blocked(harness):
    h = harness
    job, response, _ = export(h)
    h.identity["tenant"] = uuid.uuid4()
    empty_catalog = h.client.get(BASE + "/catalog")
    assert empty_catalog.status_code == 200
    assert (
        next(d for d in empty_catalog.json()["datasets"] if d["id"] == "users")["count"]
        == 0
    )
    assert h.client.post(f"{BASE}/jobs/{job['id']}/download-ticket").status_code == 404
    assert h.client.get(BASE + "/jobs").json() == []
    assert upload(h, response.content).status_code == 403
    h.identity["tenant"] = h.tenant
    with Session(h.engine) as db:
        db.add(
            models.User(
                id="foreign",
                name="Foreign",
                email="foreign@example.com",
                hashed_password="fixture",
                tenant_id=uuid.uuid4(),
            )
        )
        db.commit()
    catalog = h.client.get(BASE + "/catalog")
    assert catalog.status_code == 200
    assert (
        next(d for d in catalog.json()["datasets"] if d["id"] == "users")["count"] == 1
    )
    assert h.client.get("/admin/data/export").status_code == 403


def test_owner_export_and_restore_in_shared_database_are_workspace_scoped(harness):
    h = harness
    with Session(h.engine) as db:
        db.add(
            models.User(
                id="foreign",
                name="PRIVATE FOREIGN USER",
                email="foreign@example.com",
                hashed_password="fixture",
                tenant_id=uuid.uuid4(),
            )
        )
        db.flush()
        db.add(
            models.Task(
                id="foreign-task", title="PRIVATE FOREIGN TASK", created_by_id="foreign"
            )
        )
        db.get(models.Task, "task").assigned_to_id = "foreign"
        db.flush()
        db.add(
            models.Subtask(
                id="foreign-sub",
                task_id="foreign-task",
                title="PRIVATE FOREIGN SUBTASK",
            )
        )
        db.commit()
    catalog = h.client.get(BASE + "/catalog")
    assert catalog.status_code == 200, catalog.text
    counts = {d["id"]: d["count"] for d in catalog.json()["datasets"]}
    assert counts["users"] == counts["tasks"] == counts["subtasks"] == 1
    _, response, _ = export(h, format="json")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for name in archive.namelist():
            data = archive.read(name)
            assert b"PRIVATE FOREIGN" not in data
            assert b"foreign-task" not in data
        tasks = json.loads(archive.read("data/tasks.json"))
        assert tasks[0]["assigned_to_id"] is None
        assert len(json.loads(archive.read("data/users.json"))) == 1
    job = upload(h, response.content).json()
    assert job["report"]["valid"], job
    assert confirm(h, job).status_code == 200
    # Owner can still import shared reference/configuration records in this DB.
    job = upload(
        h, b"id,name\r\nnew,New department\r\n", "departments.csv", "departments"
    ).json()
    assert confirm(h, job).status_code == 200
    # Tenant-less records cannot be claimed by changing their primary/foreign keys.
    job = upload(
        h,
        b"id,title,created_by_id\r\nforeign-task,Hijacked,owner\r\n",
        "tasks.csv",
        "tasks",
    ).json()
    assert not job["report"]["valid"]
    assert any("outside this workspace" in error for error in job["report"]["errors"])
    assert confirm(h, job).status_code == 409
    job = upload(
        h,
        b"id,title,created_by_id,assigned_to_id\r\nnew-task,New,owner,foreign\r\n",
        "tasks.csv",
        "tasks",
    ).json()
    assert not job["report"]["valid"]
    assert any("Broken relationship" in error for error in job["report"]["errors"])
    with Session(h.engine) as db:
        assert db.get(models.Task, "foreign-task").title == "PRIVATE FOREIGN TASK"
        assert db.get(models.Task, "new-task") is None


@pytest.mark.parametrize(
    ("dataset", "payload"),
    [
        (
            "users",
            b"id,name,email,tenant_id\r\nforeign,Hijacked,foreign@example.com,{tenant}\r\n",
        ),
        (
            "subtasks",
            b"id,task_id,title,completed\r\nnew,foreign-task,Foreign parent,false\r\n",
        ),
        ("tasks", b"id,title,created_by_id\r\nnew,Foreign creator,foreign\r\n"),
    ],
)
def test_import_cannot_claim_foreign_identity_or_relationship(
    harness, dataset, payload
):
    h = harness
    with Session(h.engine) as db:
        db.add(
            models.User(
                id="foreign",
                name="Private",
                email="foreign@example.com",
                hashed_password="fixture",
                tenant_id=uuid.uuid4(),
            )
        )
        db.flush()
        db.add(models.Task(id="foreign-task", title="Private", created_by_id="foreign"))
        db.commit()
    payload = payload.replace(b"{tenant}", str(h.tenant).encode())
    result = upload(h, payload, dataset + ".csv", dataset)
    assert result.status_code == 200, result.text
    job = result.json()
    assert not job["report"]["valid"], job
    assert confirm(h, job).status_code == 409
    with Session(h.engine) as db:
        assert db.get(models.User, "foreign").name == "Private"
        assert db.get(models.User, "foreign").tenant_id != h.tenant
        assert db.get(models.Subtask, "new") is None
        assert db.get(models.Task, "new") is None


def test_owner_can_export_and_restore_legacy_shared_email_templates(harness):
    h = harness
    with h.engine.begin() as db:
        db.exec_driver_sql("DROP TABLE email_templates")
        db.exec_driver_sql(
            "CREATE TABLE email_templates (id VARCHAR(36) PRIMARY KEY, notification_type VARCHAR(100) NOT NULL UNIQUE, subject VARCHAR(255) NOT NULL, body TEXT NOT NULL, created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL)"
        )
        db.execute(
            models.EmailTemplate.__table__.insert().values(
                id="template",
                notification_type="welcome",
                subject="Hello",
                body="Welcome",
            )
        )
    catalog = h.client.get(BASE + "/catalog")
    assert catalog.status_code == 200, catalog.text
    assert (
        next(d for d in catalog.json()["datasets"] if d["id"] == "email-templates")[
            "count"
        ]
        == 1
    )
    _, response, _ = export(h, format="json")
    job = upload(h, response.content).json()
    assert job["report"]["valid"], job
    assert confirm(h, job).status_code == 200
    job = upload(
        h,
        b"id,notification_type,subject,body\r\nnew,reminder,Reminder,Body\r\n",
        "templates.csv",
        "email-templates",
    ).json()
    assert job["report"]["valid"], job
    assert confirm(h, job).status_code == 200
    job = upload(
        h,
        b"id,notification_type,subject,body\r\nnew,reminder,Changed,Body\r\n",
        "templates.csv",
        "email-templates",
    ).json()
    job = h.client.post(
        f"{BASE}/imports/{job['id']}/preview",
        json={"selected": ["email-templates"], "mode": "update"},
    ).json()
    assert job["report"]["valid"], job
    assert confirm(h, job).status_code == 200
    from sqlalchemy import inspect, text

    with h.engine.connect() as db:
        assert (
            db.scalar(text("SELECT subject FROM email_templates WHERE id='new'"))
            == "Changed"
        )
        assert "tenant_id" not in {
            column["name"] for column in inspect(db).get_columns("email_templates")
        }


def test_legacy_csv_preview_insert_and_update_require_confirmation(harness):
    h = harness
    result = upload(
        h, b"id,name\r\nnew,New department\r\n", "departments.csv", "departments"
    )
    assert result.status_code == 200, result.text
    job = result.json()
    assert job["report"]["impact"]["insert"] == 1
    with Session(h.engine) as db:
        assert db.get(models.Department, "new") is None
    assert (
        h.client.post(
            f"{BASE}/imports/{job['id']}/confirm",
            json={
                "confirmation": "WRONG",
                "preview_token": job["report"]["preview_token"],
            },
        ).status_code
        == 422
    )
    assert confirm(h, job).status_code == 200
    with Session(h.engine) as db:
        assert db.get(models.Department, "new").name == "New department"
    job = upload(
        h, b"id,name\r\nnew,Changed name\r\n", "departments.csv", "departments"
    ).json()
    assert confirm(h, job).status_code == 200
    with Session(h.engine) as db:
        assert db.get(models.Department, "new").name == "New department"
    job = upload(
        h, b"id,name\r\nnew,Changed name\r\n", "departments.csv", "departments"
    ).json()
    job = h.client.post(
        f"{BASE}/imports/{job['id']}/preview",
        json={"selected": ["departments"], "mode": "update"},
    ).json()
    assert confirm(h, job).status_code == 200
    with Session(h.engine) as db:
        assert db.get(models.Department, "new").name == "Changed name"


def test_changes_since_preview_are_not_silently_overwritten(harness):
    h = harness
    job = upload(
        h, b"id,name\r\ndept,Incoming\r\n", "departments.csv", "departments"
    ).json()
    job = h.client.post(
        f"{BASE}/imports/{job['id']}/preview", json={"mode": "update"}
    ).json()
    with Session(h.engine) as db:
        db.get(models.Department, "dept").name = "Concurrent change"
        db.commit()
    result = confirm(h, job)
    assert result.status_code == 409, result.text
    with Session(h.engine) as db:
        assert db.get(models.Department, "dept").name == "Concurrent change"


@pytest.mark.parametrize(
    "payload,expected",
    [
        (b"name\r\nMissing ID\r\n", "headers"),
        (b"id,name\r\nx,One\r\nx,Two\r\n", "Duplicate identifier"),
        (b"id,name\r\nx,One,Extra\r\n", "structure"),
        (b"id,id,name\r\nx,x,One\r\n", "headers"),
    ],
)
def test_invalid_legacy_csv(harness, payload, expected):
    result = upload(harness, payload, "departments.csv", "departments")
    assert result.status_code == 422, result.text
    assert expected.lower() in result.text.lower()


def test_legacy_hashes_are_discarded_and_missing_users_require_provisioning(harness):
    h = harness
    payload = {
        "scope": "users",
        "users": [{"id": "owner", "name": "Owner", "hashedPassword": "UNTRUSTED_HASH"}],
    }
    result = upload(h, json.dumps(payload).encode(), "legacy.json")
    assert result.status_code == 200, result.text
    job = result.json()
    assert "discarded" in str(job["report"]["warnings"])
    assert confirm(h, job).status_code == 200
    with Session(h.engine) as db:
        assert (
            db.get(models.User, "owner").hashed_password
            == "NEVER_EXPORT_THIS_CREDENTIAL"
        )
    payload["users"][0]["id"] = "missing"
    job = upload(h, json.dumps(payload).encode(), "legacy.json").json()
    assert not job["report"]["valid"]
    assert "provisioned" in str(job["report"]["errors"])
    assert confirm(h, job).status_code == 409
    assert (
        h.client.post(
            "/admin/data/import", json={"scope": "departments", "departments": []}
        ).status_code
        == 409
    )


def zip_bytes(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for key, value in entries:
            archive.writestr(key, value)
    return output.getvalue()


@pytest.mark.parametrize(
    "entries",
    [
        [("../evil", "x")],
        [("manifest.json", "{}"), ("manifest.json", "{}")],
        [("data/users.csv", "x")],
    ],
)
def test_zip_paths_duplicates_and_missing_manifests(harness, entries):
    assert upload(harness, zip_bytes(entries)).status_code == 422


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("checksum", "checksum"),
        ("version", "version"),
        ("tenant", "another workspace"),
        ("missing", "required dataset"),
    ],
)
def test_tampered_zip_validation(harness, mutation, expected):
    _, exported, _ = export(harness, scope="custom", datasets=["departments"])
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["manifest.json"])
    if mutation == "checksum":
        entries["data/departments.csv"] += b"x"
    if mutation == "version":
        manifest["backup_schema_version"] = 999
    if mutation == "tenant":
        manifest["workspace_id"] = str(uuid.uuid4())
    if mutation == "missing":
        entries.pop("data/departments.csv")
    entries["manifest.json"] = json.dumps(manifest)
    result = upload(harness, zip_bytes(entries.items()))
    assert result.status_code in (403, 422), result.text
    assert expected in result.text


def test_relationship_validation_and_transaction_rollback(harness, monkeypatch):
    h = harness
    data = {
        "subtasks": [
            {"id": "broken", "taskId": "missing", "title": "Broken", "completed": False}
        ]
    }
    job = upload(h, json.dumps(data).encode(), "legacy.json").json()
    assert not job["report"]["valid"]
    assert "Broken relationship" in str(job["report"]["errors"])
    job = upload(
        h, b"id,name\r\nx,New department\r\n", "departments.csv", "departments"
    ).json()
    original = svc.restore

    def broken_restore(db, job):
        original(db, job)
        from sqlalchemy.exc import IntegrityError

        raise IntegrityError("fixture failure", {}, None)

    monkeypatch.setattr(svc, "restore", broken_restore)
    result = confirm(h, job)
    assert result.status_code == 409
    with Session(h.engine) as db:
        assert db.get(models.Department, "x") is None
        assert db.get(BackupJob, job["id"]).status == "Failed"


def test_export_failure_never_publishes_partial_archive(harness, monkeypatch):
    def broken_export(db, job, check, progress):
        svc.path_for(job.id, ".part").write_bytes(b"partial")
        raise RuntimeError("fixture")

    monkeypatch.setattr(svc, "export_archive", broken_export)
    response = harness.client.post(BASE + "/exports", json={})
    job_id = response.json()["id"]
    job = harness.client.get(BASE + "/jobs").json()[0]
    assert job["status"] == "Failed"
    assert not svc.path_for(job_id, ".part").exists()
    assert not svc.path_for(job_id, ".zip").exists()
    assert (
        harness.client.post(f"{BASE}/jobs/{job_id}/download-ticket").status_code == 409
    )


def test_expiry_cleanup_and_cancellation(harness):
    h = harness
    job, _, _ = export(h)
    with Session(h.engine) as db:
        db.get(BackupJob, job["id"]).expires_at = datetime.now(UTC).replace(
            tzinfo=None
        ) - timedelta(seconds=1)
        db.commit()
    h.client.get(BASE + "/jobs")
    assert not svc.path_for(job["id"], ".zip").exists()
    assert h.client.post(f"{BASE}/jobs/{job['id']}/download-ticket").status_code == 410
    staged = upload(
        h, b"id,name\r\nx,New department\r\n", "departments.csv", "departments"
    ).json()
    assert h.client.post(f"{BASE}/jobs/{staged['id']}/cancel").status_code == 200
    assert confirm(h, staged).status_code == 409


def test_reset_requires_owner_expiring_otp_and_attempt_limits(harness, monkeypatch):
    h = harness
    h.identity["role"] = models.RoleEnum.USER
    assert h.client.post("/admin/data/reset/request").status_code == 403
    h.identity["role"] = models.RoleEnum.OWNER
    assert (
        h.client.post(
            "/admin/data/reset/confirm",
            json={"otp": "123456", "confirmation": "RESET WORKSPACE"},
        ).status_code
        == 400
    )
    with Session(h.engine) as db:
        db.add(
            models.OwnerResetToken(
                owner_id="owner",
                otp_hash="fixture",
                expires_at=datetime.now(UTC).replace(tzinfo=None)
                - timedelta(minutes=1),
                attempts=0,
            )
        )
        db.commit()
    assert (
        "expired"
        in h.client.post(
            "/admin/data/reset/confirm",
            json={"otp": "123456", "confirmation": "RESET WORKSPACE"},
        ).text
    )
    with Session(h.engine) as db:
        token = db.get(models.OwnerResetToken, "owner")
        token.expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)
        token.attempts = 5
        db.commit()
    assert (
        h.client.post(
            "/admin/data/reset/confirm",
            json={"otp": "123456", "confirmation": "RESET WORKSPACE"},
        ).status_code
        == 429
    )
    with Session(h.engine) as db:
        assert db.get(models.Task, "task") is not None


@pytest.mark.parametrize("fmt", ["csv", "json"])
def test_streamed_export_50000_records_has_bounded_python_memory(harness, fmt):
    import tracemalloc

    h = harness
    with h.engine.begin() as connection:
        for offset in range(0, 50_000, 500):
            connection.execute(
                models.Department.__table__.insert(),
                [
                    {
                        "id": f"bulk-{number}",
                        "name": f"Department {number} " + "x" * 180,
                    }
                    for number in range(offset, offset + 500)
                ],
            )
    job = SimpleNamespace(
        id=str(uuid.uuid4()),
        tenant_id=str(h.tenant),
        settings={
            "scope": "custom",
            "datasets": ["departments"],
            "format": fmt,
            "include_related": True,
        },
    )
    tracemalloc.start()
    try:
        with h.engine.connect() as connection:
            manifest, count, part = svc.export_archive(connection, job)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert count == 50_001
    assert manifest["files"]["departments"]["record_count"] == count
    assert peak < 24 * 1024**2, f"Peak Python allocations: {peak / 1024**2:.1f} MiB"
    assert part.stat().st_size > 0
    part.unlink()


def test_migration_adds_only_job_and_preset_tables(harness):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    module = importlib.import_module(
        "backend.alembic.versions.d4f6a8b0c2e4_backup_manager"
    )
    with harness.engine.begin() as connection:
        ExportPreset.__table__.drop(connection)
        BackupJob.__table__.drop(connection)
        before = set(inspect(connection).get_table_names())
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        assert set(inspect(connection).get_table_names()) - before == {
            "backup_jobs",
            "export_presets",
        }
        assert (
            connection.scalar(
                select(models.User.hashed_password).where(models.User.id == "owner")
            )
            == "NEVER_EXPORT_THIS_CREDENTIAL"
        )


def test_zip_restores_missing_task_and_subtask_in_dependency_order(harness):
    from sqlalchemy import delete

    h = harness
    _, exported, _ = export(h)
    with Session(h.engine) as db:
        db.execute(delete(models.Subtask))
        db.execute(delete(models.Task))
        db.commit()
    validated = upload(h, exported.content)
    assert validated.status_code == 200, validated.text
    job = validated.json()
    assert job["report"]["valid"], job
    assert confirm(h, job).status_code == 200
    with Session(h.engine) as db:
        assert db.get(models.Task, "task").created_by_id == "owner"
        assert db.get(models.Subtask, "sub").task_id == "task"


def test_legacy_subtask_import_does_not_invent_creation_time(harness):
    payload = {"subtasks": [{"id": "historical-child", "taskId": "task",
                            "title": "Unknown historical date", "completed": True}]}
    response = upload(harness, json.dumps(payload).encode(), "legacy.json")
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["report"]["valid"], job
    result = confirm(harness, job)
    assert result.status_code == 200, result.text
    with Session(harness.engine) as db:
        child = db.get(models.Subtask, "historical-child")
        assert child.created_at is None
        assert child.point_policy_version == "legacy" and child.completed
        assert db.scalar(select(models.AuditEvent).where(models.AuditEvent.subtask_id==child.id)) is None


@pytest.mark.parametrize("fmt", ["csv", "json"])
def test_pre_phase1_zip_fields_remain_importable(harness, fmt):
    from sqlalchemy import delete

    from backend.app.backups.registry import LEGACY_TASK_AUDIT_FIELDS

    _, response, _ = export(harness, format=fmt)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["manifest.json"])
    for table, profile in LEGACY_TASK_AUDIT_FIELDS.items():
        key = table.replace("_", "-")
        fields = profile.split()
        name = manifest["files"][key]["path"]
        if fmt == "json":
            rows = json.loads(entries[name])
            raw = json.dumps([{field: row[field] for field in fields} for row in rows]).encode()
        else:
            rows = list(csv.DictReader(io.StringIO(entries[name].decode("utf-8-sig"))))
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            raw = stream.getvalue().encode()
        entries[name] = raw
        manifest["files"][key].update(fields=fields, sha256=hashlib.sha256(raw).hexdigest())
    entries["manifest.json"] = json.dumps(manifest).encode()
    with Session(harness.engine) as db:
        db.execute(delete(models.Subtask))
        db.commit()
    response = upload(harness, zip_bytes(entries.items()))
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["report"]["valid"], job
    result = confirm(harness, job)
    assert result.status_code == 200, result.text
    with Session(harness.engine) as db:
        child = db.get(models.Subtask, "sub")
        assert child.created_at is None and child.point_policy_version == "legacy"


def test_immutable_task_history_allows_unchanged_backup_replay(harness):
    from backend.app.services import audit_logger as repo

    with Session(harness.engine) as db:
        row = repo.record_manual_work(db, actor_id="owner", task_id="task", data={
            "started_at":"2026-11-02T01:00:00Z", "ended_at":"2026-11-02T01:30:00Z",
            "request_id":"backup-interval"})
        key, event_id = row.id, row.activity_event_id
        db.commit()
    _, response, _ = export(harness, format="json")
    job = upload(harness, response.content).json()
    response = harness.client.post(f"{BASE}/imports/{job['id']}/preview", json={"mode":"update"})
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["report"]["valid"], job
    response = confirm(harness, job)
    assert response.status_code == 200, response.text
    with Session(harness.engine) as db:
        assert db.get(models.TaskWorkInterval, key).activity_event_id == event_id
        assert db.get(models.AuditEvent, event_id).audit_schema_version == 2


def test_fresh_restore_preserves_managed_subtasks_manual_work_and_reversal_order(harness,tmp_path,monkeypatch):
    from sqlalchemy import event as sa_event

    from backend.app.services import audit_logger as audit
    from backend.app.services import subtasks as workflow
    from backend.app.tickets.models import XpLedger

    with Session(harness.engine) as db:
        db.add(models.TaskWorkflowSettings(tenant_id=harness.tenant,enabled=True,point_policy_version="v2",activated_at=models.utc_now()-timedelta(hours=1)))
        db.commit()
        child=workflow.create(db,actor_id="owner",task_id="task",data={"title":"Managed","planned_start_date":"2026-11-02","planned_end_date":"2026-11-03"})
        child_id=child.id
        event=audit.record_task_activity(db,actor_id="owner",task_id="task",subtask_id=child_id,data={"event_type":"subtask.points_changed"})
        original=audit.append_point_adjustment(db,actor_id="owner",task_id="task",subtask_id=child_id,data={"user_id":"owner","component_type":"BONUS","points":7,"policy_version":"v2","idempotency_key":"original","activity_event_id":event.id,"reason":"Fixture"})
        reversal=audit.append_point_adjustment(db,actor_id="owner",task_id="task",subtask_id=child_id,data={"user_id":"owner","component_type":"REVERSAL","points":-7,"policy_version":"v2","idempotency_key":"reversal","activity_event_id":event.id,"reason":"Reversal fixture","reversal_of_id":original.id})
        ids={str(original.id):"ffffffff-ffff-4fff-bfff-ffffffffffff",str(reversal.id):"00000000-0000-4000-8000-000000000000"}
        original_id,reversal_id=str(original.id),str(reversal.id)
        interval=audit.record_manual_work(db,actor_id="owner",task_id="task",subtask_id=child_id,data={"started_at":"2026-11-02T10:00:00+05:30","ended_at":"2026-11-02T10:30:00+05:30","request_id":"restore-work"})
        interval_id=interval.id
        workflow.edit(db,actor_id="owner",task_id="task",subtask_id=child_id,data={"expected_version":1,"action":"START"})
        workflow.edit(db,actor_id="owner",task_id="task",subtask_id=child_id,data={"expected_version":2,"actual_start_at":"2026-11-02T10:00:00+05:30","actual_end_at":"2026-11-02T10:45:00+05:30","confirm_actual_times":True})
        workflow.edit(db,actor_id="owner",task_id="task",subtask_id=child_id,data={"expected_version":3,"action":"COMPLETE"})
        db.commit()
    _,response,_=export(harness,format="json")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        entries={name:archive.read(name) for name in archive.namelist()}
    manifest=json.loads(entries["manifest.json"])
    name=manifest["files"]["xp-ledger"]["path"]
    rows=json.loads(entries[name])
    for row in rows:
        row["id"]=ids[row["id"]]
        if row["reversal_of_id"]: row["reversal_of_id"]=ids[row["reversal_of_id"]]
    entries[name]=json.dumps(rows).encode()
    manifest["files"]["xp-ledger"]["sha256"]=hashlib.sha256(entries[name]).hexdigest()
    entries["manifest.json"]=json.dumps(manifest).encode()

    target=create_engine(f"sqlite:///{tmp_path / 'fresh-restored.db'}")
    @sa_event.listens_for(target,"connect")
    def configure(connection,_):
        connection.create_function("to_tsvector",2,lambda lang,value:value,deterministic=True)
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(target)
    with Session(target) as db:
        db.add(models.User(id="owner",tenant_id=harness.tenant,name="Owner",email="owner@example.com",hashed_password="fixture-destination",role=models.RoleEnum.OWNER,points=77))
        db.commit()
    def target_session():
        with Session(target) as db: yield db
    harness.app.dependency_overrides[get_db]=target_session
    monkeypatch.setattr(svc,"SessionLocal",sessionmaker(target))
    response=upload(harness,zip_bytes(entries.items()))
    assert response.status_code==200,response.text
    job=response.json()
    assert job["report"]["valid"],job
    response=confirm(harness,job)
    assert response.status_code==200,response.text
    with Session(target) as db:
        child=db.get(models.Subtask,child_id)
        assert child.completed and child.status=="COMPLETED" and child.actual_start_at.hour==4
        assert db.get(models.TaskWorkInterval,interval_id).subtask_id==child_id
        assert db.scalar(select(models.User.points).where(models.User.id=="owner"))==77
        assert db.scalar(select(XpLedger.points).where(XpLedger.id==uuid.UUID(ids[original_id])))==7
        assert db.scalar(select(XpLedger.points).where(XpLedger.id==uuid.UUID(ids[reversal_id])))==-7
        assert db.scalar(select(XpLedger.reversal_of_id).where(XpLedger.id==uuid.UUID(ids[reversal_id])))==uuid.UUID(ids[original_id])
    target.dispose()


def test_missing_archive_fields_do_not_match_a_previous_reward_profile(harness):
    _,response,_=export(harness,format='json')
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        entries={name:archive.read(name) for name in archive.namelist()}
    manifest=json.loads(entries['manifest.json'])
    manifest['files']['departments'].pop('fields')
    entries['manifest.json']=json.dumps(manifest).encode()
    result=upload(harness,zip_bytes(entries.items()))
    assert result.status_code==422,result.text
    assert 'headers' in result.text.lower()


def test_reward_policy_snapshot_and_ledger_restore_never_recredits_wallet(harness, tmp_path, monkeypatch):
    from backend.app.services import subtask_rewards as rewards
    from backend.app.services import subtasks
    from backend.app.tickets.models import XpLedger
    with Session(harness.engine) as db:
        owner=db.get(models.User,'owner')
        owner.timezone='UTC'
        db.get(models.Task,'task').assigned_to_id='owner'
        db.get(models.Task,'task').priority=models.TaskPriorityEnum.HIGH
        rewards.configure(db,actor=owner,enabled=True,expected_version=0)
        db.commit()
        children=[subtasks.create(db,actor_id='owner',task_id='task',data={'title':f'Child {i}','planned_start_date':'2026-11-02','planned_end_date':'2026-11-02'}) for i in range(2)]
        child=children[1]
        for change in ({'action':'START'},{'actual_start_at':'2026-11-02T00:00:00Z','actual_end_at':'2026-11-02T12:00:00Z','confirm_actual_times':True},{'action':'COMPLETE'}):
            subtasks.edit(db,actor_id='owner',task_id='task',subtask_id=child.id,data={'expected_version':child.version,**change})
        child_id=child.id
        db.commit()
        assert db.get(models.User,'owner').points==45
    _,response,_=export(harness,format='json')
    target=create_engine(f"sqlite:///{tmp_path / 'reward-restored.db'}")
    @event.listens_for(target,'connect')
    def configure(connection,_):
        connection.create_function('to_tsvector',2,lambda lang,value:value,deterministic=True)
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(target)
    with Session(target) as db:
        db.add(models.User(id='owner',tenant_id=harness.tenant,name='Owner',email='owner@example.com',hashed_password='fixture',role=models.RoleEnum.OWNER,points=77))
        db.commit()
    def target_session():
        with Session(target) as db: yield db
    harness.app.dependency_overrides[get_db]=target_session
    monkeypatch.setattr(svc,'SessionLocal',sessionmaker(target))
    job=upload(harness,response.content)
    assert job.status_code==200,job.text
    assert job.json()['report']['valid'],job.text
    result=confirm(harness,job.json())
    assert result.status_code==200,result.text
    with Session(target) as db:
        assert db.get(models.User,'owner').points==77
        assert db.get(models.Subtask,child_id).reward_timezone=='UTC'
        entries=list(db.scalars(select(XpLedger).where(XpLedger.ref_type==rewards.POLICY)))
        assert len(entries)==2 and sum(row.points for row in entries)==45
        assert entries[0].calculation_inputs['algorithm']==rewards.POLICY
        assert db.get(models.TaskWorkflowSettings,(harness.tenant,rewards.POLICY)).reward_policy_data['config']['Other']['HIGH']['base']==30
    target.dispose()


def test_export_uses_one_consistent_snapshot_across_files(harness):
    h = harness
    job = SimpleNamespace(
        id=str(uuid.uuid4()),
        tenant_id=str(h.tenant),
        settings={
            "scope": "custom",
            "datasets": ["achievements", "departments"],
            "format": "json",
            "include_related": True,
        },
    )

    def concurrent_edit(count, completed, total):
        if completed == 1:
            with Session(h.engine) as db:
                db.get(
                    models.Department, "dept"
                ).name = "Concurrent edit after snapshot"
                db.commit()

    with h.engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
        if h.engine.dialect.name == "postgresql"
        else "SERIALIZABLE"
    ) as connection:
        with connection.begin():
            if h.engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN")
            _, _, part = svc.export_archive(connection, job, progress=concurrent_edit)
    with zipfile.ZipFile(part) as archive:
        assert (
            json.loads(archive.read("data/departments.json"))[0]["name"]
            == "=1+1, café\nteam"
        )
    part.unlink()


def test_legacy_json_export_excludes_hashes(harness):
    response = harness.client.get("/admin/data/export")
    assert response.status_code == 200, response.text
    assert "hashed_password" not in response.text
    assert "NEVER_EXPORT_THIS_CREDENTIAL" not in response.text


@pytest.mark.parametrize(
    "endpoint", ["/exports", "/imports/validate", "/imports/unknown/confirm"]
)
def test_unauthorized_mutations_are_rejected(harness, endpoint):
    harness.identity["role"] = models.RoleEnum.ADMIN
    if endpoint.endswith("/validate"):
        response = harness.client.post(
            BASE + endpoint, files={"file": ("legacy.json", b"{}")}
        )
    else:
        response = harness.client.post(
            BASE + endpoint,
            json={"confirmation": "RESTORE", "preview_token": "fixture"}
            if endpoint.endswith("confirm")
            else {},
        )
    assert response.status_code == 403, response.text


def test_restore_timeout_changes_no_business_data(harness, monkeypatch):
    h = harness
    job = upload(
        h, b"id,name\r\nnew,New department\r\n", "departments.csv", "departments"
    ).json()
    monkeypatch.setattr(svc, "TIMEOUT", -1)
    response = confirm(h, job)
    assert response.status_code == 408, response.text
    with Session(h.engine) as db:
        assert db.get(models.Department, "new") is None


def test_missing_migration_returns_actionable_error(harness):
    with harness.engine.begin() as connection:
        ExportPreset.__table__.drop(connection)
    response = harness.client.get(BASE + "/catalog")
    assert response.status_code == 503
    assert "migration is required" in response.text


def test_owner_can_explicitly_provision_inactive_users_and_restore_their_relationships(
    harness,
):
    from backend.app.auth import verify_password
    from backend.app.routers import users as users_router

    h = harness
    content = {
        "users": [
            {
                "id": "recovered",
                "name": "Recovered",
                "email": "recovered@example.com",
                "role": "owner",
                "status": "ACTIVE",
                "hashedPassword": "UNTRUSTED_HASH",
                "employerId": "untrusted-scope",
            }
        ],
        "tasks": [
            {
                "id": "recovered-task",
                "title": "Recovered task",
                "createdById": "recovered",
            }
        ],
    }
    job = upload(h, json.dumps(content).encode(), "legacy.json").json()
    assert not job["report"]["valid"]
    with Session(h.engine) as db:
        assert db.get(models.User, "recovered") is None
    response = h.client.post(
        f"{BASE}/imports/{job['id']}/preview", json={"provision_users": True}
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["report"]["valid"], job
    assert job["report"]["impact"]["provision"] == 1
    result = confirm(h, job)
    assert result.status_code == 200, result.text
    with Session(h.engine) as db:
        user = db.get(models.User, "recovered")
        assert user.role == models.RoleEnum.USER
        assert user.status == models.UserStatusEnum.DEACTIVATED
        assert user.hashed_password != "UNTRUSTED_HASH"
        assert user.tenant_id == h.tenant
        assert user.employer_id == db.get(models.User, "owner").employer_id
        assert db.get(models.Task, "recovered-task").created_by_id == user.id
    # Reuse the existing authorized recovery endpoint; provisioning adds no auth API.
    h.app.include_router(users_router.router)
    response = h.client.post(
        "/users/recovered/reset-password",
        json={"new_password": "fixture-recovery-password"},
    )
    assert response.status_code == 204, response.text
    with Session(h.engine) as db:
        user = db.get(models.User, "recovered")
        assert verify_password("fixture-recovery-password", user.hashed_password)
        assert user.status == models.UserStatusEnum.DEACTIVATED


def test_account_provisioning_rejects_duplicate_email_and_bad_email(harness):
    h = harness
    for email in ("owner@example.com", "invalid-email"):
        content = {"users": [{"id": "recovered", "name": "Recovered", "email": email}]}
        job = upload(h, json.dumps(content).encode(), "legacy.json").json()
        job = h.client.post(
            f"{BASE}/imports/{job['id']}/preview", json={"provision_users": True}
        ).json()
        assert not job["report"]["valid"], job
        assert confirm(h, job).status_code == 409
    with Session(h.engine) as db:
        assert db.get(models.User, "recovered") is None


def test_user_updates_never_import_authentication_or_authorization(harness):
    h = harness
    content = {
        "users": [
            {
                "id": "owner",
                "name": "Updated profile",
                "email": "other@example.com",
                "role": "user",
                "status": "DEACTIVATED",
                "hashedPassword": "UNTRUSTED_HASH",
                "employerId": "untrusted-scope",
            }
        ]
    }
    job = upload(h, json.dumps(content).encode(), "legacy.json").json()
    job = h.client.post(
        f"{BASE}/imports/{job['id']}/preview",
        json={"mode": "update", "provision_users": True},
    ).json()
    assert job["report"]["valid"], job
    assert confirm(h, job).status_code == 200
    with Session(h.engine) as db:
        user = db.get(models.User, "owner")
        assert user.name == "Updated profile"
        assert user.role == models.RoleEnum.OWNER
        assert user.status == models.UserStatusEnum.ACTIVE
        assert user.email == "owner@example.com"
        assert user.hashed_password == "NEVER_EXPORT_THIS_CREDENTIAL"
        assert user.employer_id is None


@pytest.mark.parametrize("chunked", [False, True])
def test_oversized_upload_is_rejected_before_parsing_or_job_creation(
    harness, monkeypatch, chunked
):
    monkeypatch.setattr(svc, "MAX_UPLOAD", 16)
    headers = {"Content-Type": "multipart/form-data; boundary=fixture"}
    if chunked:
        headers["Transfer-Encoding"] = "chunked"
        content = iter([b"x" * 65536 for _ in range(17)])
    else:
        headers["Content-Length"] = str(2 * 1024**2)
        content = b""
    response = harness.client.post(
        BASE + "/imports/validate", content=content, headers=headers
    )
    assert response.status_code == 413, response.text
    with Session(harness.engine) as db:
        assert db.scalar(select(BackupJob.id)) is None


def test_migration_adopts_startup_created_metadata_without_changing_records(harness):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    module = importlib.import_module(
        "backend.alembic.versions.d4f6a8b0c2e4_backup_manager"
    )
    created = harness.client.post(
        BASE + "/presets",
        json={
            "name": "Preserved",
            "settings": {"scope": "custom", "datasets": ["departments"]},
        },
    )
    assert created.status_code == 200, created.text
    with harness.engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.upgrade()
        assert (
            connection.scalar(
                select(ExportPreset.name).where(ExportPreset.id == created.json()["id"])
            )
            == "Preserved"
        )


def test_migration_refuses_incompatible_metadata_layout(harness):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    module = importlib.import_module(
        "backend.alembic.versions.d4f6a8b0c2e4_backup_manager"
    )
    with harness.engine.begin() as connection:
        BackupJob.__table__.drop(connection)
        connection.exec_driver_sql("CREATE TABLE backup_jobs (id INTEGER PRIMARY KEY)")
        with (
            Operations.context(MigrationContext.configure(connection)),
            pytest.raises(RuntimeError, match="incompatible backup metadata"),
        ):
            module.upgrade()
        assert (
            connection.scalar(select(models.User.id).where(models.User.id == "owner"))
            == "owner"
        )
