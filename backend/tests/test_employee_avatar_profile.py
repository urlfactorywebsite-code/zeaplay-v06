"""Isolated SQLite API coverage. Never starts or migrates the installed app."""

import base64
import json
import uuid
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.avatar_utils import load_avatar_image, set_user_avatar_from_data_url
from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.dependencies import get_current_active_user
from backend.app.routers import avatars, users


def picture(fmt="PNG", size=(80, 60)):
    output = BytesIO()
    Image.new("RGB", size, "red").save(output, format=fmt)
    return output.getvalue()


def data_url(data=None, mime="image/png"):
    return (
        f"data:{mime};base64,"
        + base64.b64encode(data if data is not None else picture()).decode()
    )


@pytest.fixture
def harness(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "media_root", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "minio_access_key", None)
    monkeypatch.setattr(settings, "minio_secret_key", None)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'profiles.db'}",
        connect_args={"check_same_thread": False},
    )
    for table in (
        models.Department,
        models.User,
        models.AvatarAsset,
        models.MediaFile,
        models.RewardClaim,
        models.AuditEvent,
    ):
        table.__table__.create(engine, checkfirst=True)
    tenant, other_tenant = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as db:
        for name, group in (
            ("self", tenant),
            ("colleague", tenant),
            ("foreign", other_tenant),
        ):
            db.add(
                models.User(
                    id=name,
                    name=name,
                    email=f"{name}@example.com",
                    tenant_id=group,
                    hashed_password="fixture",
                )
            )
        db.commit()
    identity = {"id": "self"}
    app = FastAPI()
    app.include_router(users.router)
    app.include_router(avatars.router)

    def session():
        with Session(engine) as db:
            yield db

    def actor():
        with Session(engine) as db:
            return db.get(models.User, identity["id"])

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_active_user] = actor
    monkeypatch.setattr(users.audit_logger, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(users, "trigger_n8n_event", lambda *a, **k: None)
    with TestClient(app) as client:
        yield client, engine, identity, tmp_path
    engine.dispose()


def test_upload_refresh_replace_delete_and_frame(harness):
    client, _engine, _, root = harness
    response = client.post("/users/me/avatar", json={"data_url": data_url()})
    assert response.status_code == 200, response.text
    original = response.json()
    image_url = original["avatar_url"]
    assert image_url.startswith("/avatars/")
    image = client.get(image_url)
    assert image.status_code == 200
    assert Image.open(BytesIO(image.content)).size == (512, 512)
    assert Image.open(
        BytesIO(client.get(image_url + "&thumbnail=true").content)
    ).size == (128, 128)
    assert (
        client.get("/users/self").json()["avatar_asset_id"]
        == original["avatar_asset_id"]
    )
    assert client.patch("/users/me", json={"avatar_frame": "aurora"}).status_code == 200
    replacement = client.post(
        "/users/me/avatar", json={"data_url": data_url(picture("JPEG"), "image/jpeg")}
    )
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["avatar_asset_id"] != original["avatar_asset_id"]
    assert client.get(image_url).status_code == 404
    removed = client.patch("/users/me", json={"avatar_asset_id": None})
    assert removed.status_code == 200, removed.text
    assert removed.json()["avatar_url"] is None
    assert removed.json()["avatar_frame"] == "aurora"
    assert not list((root / "media").rglob("*.webp"))


@pytest.mark.parametrize(
    "binary,mime,code",
    [
        (b"<svg onload='alert(1)'/>", "image/svg+xml", 400),
        (b"MZ executable", "image/png", 400),
        (picture("GIF"), "image/gif", 400),
        (picture("JPEG"), "image/png", 400),
        (picture()[:24], "image/png", 400),
        (picture(size=(8, 8)), "image/png", 400),
        (b"x" * (5 * 1024 * 1024 + 1), "image/png", 413),
    ],
    ids=["svg", "executable", "gif", "mismatch", "truncated", "too-small", "too-large"],
)
def test_invalid_uploads(harness, binary, mime, code):
    client, *_ = harness
    response = client.post(
        "/users/me/avatar", json={"data_url": data_url(binary, mime)}
    )
    assert response.status_code == code, response.text


def test_bio_skills_contact_and_conflicts(harness):
    client, *_ = harness
    before = client.get("/users/self").json()
    result = client.patch(
        "/users/me",
        json={
            "profile_bio": "First line\n<script>text only</script>",
            "skills": [" React ", "react", "Client   Communication"],
            "phone": "123",
            "location": "Remote",
            "timezone": "Asia/Calcutta",
            "expected_updated_at": before["updated_at"],
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["skills"] == ["React", "Client Communication"]
    assert (
        client.get("/users/self").json()["profile_bio"]
        == "First line\n<script>text only</script>"
    )
    assert (
        client.patch(
            "/users/me",
            json={"profile_bio": "stale", "expected_updated_at": before["updated_at"]},
        ).status_code
        == 409
    )
    for payload in (
        {"profile_bio": "x" * 501},
        {"skills": ["x" * 61]},
        {"skills": [""]},
        {"role": "OWNER"},
    ):
        assert client.patch("/users/me", json=payload).status_code == 422
    assert client.patch("/users/me", json={"skills": []}).json()["skills"] == []


def test_tenant_and_authorization(harness):
    client, engine, identity, _ = harness
    assert {user["id"] for user in client.get("/users").json()} == {"self", "colleague"}
    assert client.get("/users/foreign").status_code == 404
    assert client.patch("/users/me", json={"employer_id": "changed"}).status_code == 403
    assert client.patch("/users/self", json={"role": "OWNER"}).status_code == 403
    assert (
        client.post(
            "/users/colleague/avatar", json={"data_url": data_url()}
        ).status_code
        == 403
    )
    avatar = client.post("/users/me/avatar", json={"data_url": data_url()}).json()
    identity["id"] = "colleague"
    assert client.get(avatar["avatar_url"]).status_code == 200
    assert (
        client.patch(
            "/users/me", json={"avatar_asset_id": avatar["avatar_asset_id"]}
        ).status_code
        == 404
    )
    identity["id"] = "foreign"
    assert client.get(avatar["avatar_url"]).status_code == 404
    assert (
        client.post("/users/self/avatar", json={"data_url": data_url()}).status_code
        == 404
    )
    with Session(engine) as db:
        user = db.get(models.User, "foreign")
        user.role = models.RoleEnum.OWNER
        db.commit()
    assert client.get(avatar["avatar_url"]).status_code == 404
    assert (
        client.patch("/users/self", json={"profile_bio": "foreign"}).status_code == 404
    )
    assert all(
        asset["id"] != avatar["avatar_asset_id"]
        for asset in client.get("/avatars").json()
    )


def test_original_multipart_crop_and_metadata(harness):
    client, *_ = harness
    crop = {"x": 10, "y": 5, "width": 40, "height": 40}
    response = client.post(
        "/users/me/avatar",
        files={"file": ("untrusted.exe", picture(), "image/png")},
        data={"crop": json.dumps(crop)},
    )
    assert response.status_code == 200, response.text
    normalized = client.get(response.json()["avatar_url"])
    image = Image.open(BytesIO(normalized.content))
    assert image.format == "WEBP" and not image.getexif()
    assert (
        client.post(
            "/users/me/avatar",
            files={"file": ("bad.png", b"invalid", "image/png")},
            data={"crop": json.dumps(crop)},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/users/me/avatar",
            files={"file": ("image.png", picture(), "image/png")},
            data={"crop": '{"x":NaN}'},
        ).status_code
        == 422
    )


def test_failed_transaction_keeps_previous_and_cleans_new_files(harness):
    client, engine, _, root = harness
    before = client.post("/users/me/avatar", json={"data_url": data_url()}).json()
    with Session(engine) as db:
        user = db.get(models.User, "self")
        set_user_avatar_from_data_url(db, user, data_url=data_url(), actor=user)
        db.rollback()
    assert client.get(before["avatar_url"]).status_code == 200
    assert len(list((root / "media").rglob("*.webp"))) == 2


def test_dimension_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "avatar_max_pixels", 1024)
    with pytest.raises(Exception) as exc:
        load_avatar_image(picture(size=(33, 33)))
    assert exc.value.status_code == 400


def test_policy_audit_and_unauthenticated_image_access(harness):
    client, engine, *_ = harness
    policy = client.get("/avatars/policy").json()
    assert policy["maxBytes"] == 5 * 1024 * 1024
    assert policy["contentTypes"] == ["image/jpeg", "image/png", "image/webp"]
    profile = client.post("/users/me/avatar", json={"data_url": data_url()}).json()
    with Session(engine) as db:
        event = (
            db.query(models.AuditEvent)
            .filter_by(event_type="user.avatar.updated")
            .one()
        )
        assert event.actor_id == "self" and event.entity_id == "self"
    del client.app.dependency_overrides[get_current_active_user]
    assert client.get(profile["avatar_url"]).status_code == 401


def test_admin_profile_fields_and_tenant_notification_recipients(harness, monkeypatch):
    client, engine, *_ = harness
    with Session(engine) as db:
        db.get(models.User, "self").role = models.RoleEnum.ADMIN
        db.get(models.User, "foreign").role = models.RoleEnum.OWNER
        db.get(models.User, "colleague").employer_id = "KEEP-001"
        db.commit()
        tenant = db.get(models.User, "self").tenant_id
        assert users._get_admin_ids(db, tenant) == ["self"]
    monkeypatch.setattr(
        users.notification_service, "create_notification", lambda *a, **k: None
    )
    response = client.patch(
        "/users/colleague",
        json={"title": "Engineer", "profile_bio": "Bio", "manager_id": "self"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["employer_id"] == "KEEP-001"
    assert response.json()["title"] == "Engineer"
    assert (
        client.patch("/users/colleague", json={"manager_id": "foreign"}).status_code
        == 400
    )
    assert (
        client.post(
            "/users/colleague/avatar", json={"data_url": data_url()}
        ).status_code
        == 200
    )


def test_migration_adds_nullable_fields_and_preserves_rows(tmp_path):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text

    migration = importlib.import_module(
        "backend.alembic.versions.c3e5f7a9b1d2_employee_profile_avatar"
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE users (id TEXT PRIMARY KEY, tenant_id TEXT, name TEXT)")
        )
        connection.execute(
            text("CREATE TABLE avatar_assets (id TEXT PRIMARY KEY, created_by_id TEXT)")
        )
        connection.execute(
            text("INSERT INTO users VALUES ('old-user', 'tenant-1', 'Keep name')")
        )
        connection.execute(
            text("INSERT INTO avatar_assets VALUES ('old-photo', 'old-user')")
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        assert connection.execute(
            text("SELECT id, name, profile_bio FROM users")
        ).one() == ("old-user", "Keep name", None)
        assert (
            connection.execute(text("SELECT tenant_id FROM avatar_assets")).scalar_one()
            == "tenant-1"
        )
        assert "ix_avatar_assets_tenant_id" in {
            item["name"] for item in inspect(connection).get_indexes("avatar_assets")
        }
    engine.dispose()


def test_existing_minio_client_stores_variants_and_cleans_replacement(
    harness, monkeypatch
):
    from backend.app.services import minio_media_service

    client, *_ = harness
    objects = {}

    class ObjectStore:
        def put_object(self, *, Bucket, Key, Body, ContentType):
            assert ContentType == "image/webp"
            objects[Key] = Body

        def get_object(self, *, Bucket, Key):
            return {"Body": BytesIO(objects[Key])}

        def delete_object(self, *, Bucket, Key):
            objects.pop(Key, None)

    monkeypatch.setattr(get_settings(), "minio_access_key", "fixture-access")
    monkeypatch.setattr(get_settings(), "minio_secret_key", "fixture-secret")
    monkeypatch.setattr(minio_media_service, "_get_minio_client", lambda: ObjectStore())
    original = client.post("/users/me/avatar", json={"data_url": data_url()})
    assert original.status_code == 200, original.text
    first_keys = set(objects)
    assert len(first_keys) == 2 and all(
        key.startswith("private-avatars/") for key in first_keys
    )
    assert client.get(original.json()["avatar_url"]).status_code == 200
    assert (
        client.post("/users/me/avatar", json={"data_url": data_url()}).status_code
        == 200
    )
    assert len(objects) == 2 and not first_keys.intersection(objects)
    assert client.patch("/users/me", json={"avatar_asset_id": None}).status_code == 200
    assert not objects


@pytest.mark.parametrize(
    "fmt,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")]
)
def test_all_supported_formats_are_normalized(harness, fmt, mime):
    client, *_ = harness
    response = client.post(
        "/users/me/avatar", json={"data_url": data_url(picture(fmt), mime)}
    )
    assert response.status_code == 200, response.text
    assert (
        Image.open(BytesIO(client.get(response.json()["avatar_url"]).content)).format
        == "WEBP"
    )


def test_manager_cannot_bypass_avatar_permission_with_profile_patch(harness):
    client, engine, *_ = harness
    with Session(engine) as db:
        db.get(models.User, "self").role = models.RoleEnum.MANAGER
        db.commit()
    assert (
        client.patch("/users/colleague", json={"avatar_asset_id": None}).status_code
        == 403
    )
    assert (
        client.patch("/users/colleague", json={"avatar_frame": "aurora"}).status_code
        == 403
    )
    assert client.patch("/users/me", json={"avatar_frame": "aurora"}).status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"role": "owner"},
        {"role": "admin"},
        {"department_id": None},
        {"employer_id": "tampered"},
        {"manager_id": None},
        {"manager_email": "private@example.com"},
        {"shift_start": "02:00"},
        {"password": "unsafe-change"},
        {"phone": "private"},
        {"notes": "private"},
    ],
)
def test_manager_cannot_change_security_or_private_fields(harness, payload):
    client, engine, *_ = harness
    with Session(engine) as db:
        db.get(models.User, "self").role = models.RoleEnum.MANAGER
        db.commit()
    for target in ("self", "colleague"):
        assert client.patch(f"/users/{target}", json=payload).status_code == 403


def test_manager_cannot_create_privileged_accounts_or_reset_password(harness):
    client, engine, *_ = harness
    with Session(engine) as db:
        db.get(models.User, "self").role = models.RoleEnum.MANAGER
        db.commit()
    assert (
        client.post(
            "/users",
            json={
                "name": "Injected",
                "email": "injected@example.com",
                "password": "fixture-password",
                "role": "admin",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/users/colleague/reset-password", json={"new_password": "fixture-password"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize("role", [models.RoleEnum.USER, models.RoleEnum.MANAGER])
def test_private_profile_fields_omitted_from_peer_reads_and_nested_models(
    harness, role
):
    from backend.app import schemas

    client, engine, *_ = harness
    with Session(engine) as db:
        db.get(models.User, "self").role = role
        peer = db.get(models.User, "colleague")
        peer.phone, peer.location, peer.timezone = (
            "private-phone",
            "private-location",
            "UTC",
        )
        peer.notes, peer.manager_email, peer.employer_id = (
            "private-notes",
            "private@example.com",
            "EMP-2",
        )
        db.commit()
        nested = schemas.UserRead.model_validate(peer).model_dump()
        assert "phone" not in nested and "notes" not in nested
    responses = [
        client.get("/users/colleague").json(),
        client.get("/users/by-employer-id/EMP-2").json(),
        next(
            person
            for person in client.get("/users").json()
            if person["id"] == "colleague"
        ),
    ]
    for response in responses:
        assert not {
            "phone",
            "location",
            "timezone",
            "notes",
            "manager_email",
            "profile_image_key",
        }.intersection(response)
        assert response["employer_id"] == "EMP-2"


def test_private_fields_available_to_self_and_admin_without_read_mutation(harness):
    client, engine, identity, _ = harness
    with Session(engine) as db:
        peer = db.get(models.User, "colleague")
        peer.phone, peer.notes = "self-phone", "internal note"
        peer.profile_image_key = "avatars/colleague/old/avatar.webp"
        peer.profile_image_url = "https://example.com/historical.webp"
        db.commit()
    identity["id"] = "colleague"
    assert client.get("/users/colleague").json()["phone"] == "self-phone"
    assert "notes" not in client.get("/users/colleague").json()
    identity["id"] = "self"
    with Session(engine) as db:
        db.get(models.User, "self").role = models.RoleEnum.ADMIN
        db.commit()
    assert client.get("/users/colleague").json()["notes"] == "internal note"
    with Session(engine) as db:
        result = users._hydrate_user_avatar(
            db.get(models.User, "colleague"), db.get(models.User, "self")
        )
        assert "profile_image_key" not in result.model_dump()
        assert not db.dirty


def test_orphaned_tenant_default_does_not_become_global(harness):
    client, engine, identity, _root = harness
    profile = client.post("/users/me/avatar", json={"data_url": data_url()}).json()
    with Session(engine) as db:
        asset = db.get(models.AvatarAsset, profile["avatar_asset_id"])
        asset.is_default, asset.created_by_id = True, None
        db.commit()
    assert client.get(profile["avatar_url"]).status_code == 200
    identity["id"] = "foreign"
    assert client.get(profile["avatar_url"]).status_code == 404
    assert not client.get("/avatars").json()


def test_library_upload_replace_delete_uses_private_durable_variants(harness):
    client, engine, _, root = harness
    with Session(engine) as db:
        db.get(models.User, "self").role = models.RoleEnum.OWNER
        db.commit()
    created = client.post(
        "/avatars",
        json={"name": "Team photo", "storage_type": "data_url", "data_url": data_url()},
    )
    assert created.status_code == 201, created.text
    asset = created.json()
    assert len(list((root / "media").rglob("*.webp"))) == 2
    assert asset["url"].startswith("/avatars/")
    assert (
        client.patch("/users/me", json={"avatar_asset_id": asset["id"]}).status_code
        == 200
    )
    assert client.delete(f"/avatars/{asset['id']}").status_code == 409
    replaced = client.patch(
        f"/avatars/{asset['id']}",
        json={"data_url": data_url(picture("JPEG"), "image/jpeg")},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["url"] != asset["url"]
    assert len(list((root / "media").rglob("*.webp"))) == 2
    assert client.get(replaced.json()["url"]).status_code == 200
    assert client.patch("/users/me", json={"avatar_asset_id": None}).status_code == 200
    assert client.delete(f"/avatars/{asset['id']}").status_code == 204
    assert not list((root / "media").rglob("*.webp"))


def test_bundled_avatars_are_immutable_for_tenant_owner(harness):
    client, engine, *_ = harness
    with Session(engine) as db:
        db.get(models.User, "self").role = models.RoleEnum.OWNER
        db.add(
            models.AvatarAsset(
                id="bundled",
                name="Bundled",
                is_default=True,
                file_path="avatars/library/default-avatar-01.svg",
            )
        )
        db.commit()
    assert (
        client.patch("/avatars/bundled", json={"name": "tampered"}).status_code == 403
    )
    assert client.delete("/avatars/bundled").status_code == 400


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:image/svg+xml,<svg/>",
        "//evil.test/x",
        "https://user:password@example.com/x",
    ],
)
def test_unsafe_external_avatar_urls_rejected(harness, url):
    client, engine, *_ = harness
    with Session(engine) as db:
        db.get(models.User, "self").role = models.RoleEnum.OWNER
        db.commit()
    assert (
        client.post(
            "/avatars",
            json={
                "name": "Unsafe",
                "storage_type": "external_url",
                "external_url": url,
            },
        ).status_code
        == 422
    )


def test_storage_prefix_sibling_traversal_is_rejected(tmp_path):
    from backend.app.storage.local import LocalAdapter

    storage = LocalAdapter(str(tmp_path / "media"), "/uploads")
    sibling = tmp_path / "media-secret"
    sibling.mkdir()
    (sibling / "keep.txt").write_text("keep")
    for operation in (
        lambda: storage.delete("../media-secret/keep.txt"),
        lambda: storage.save(
            b"replace", "../media-secret/keep.txt", content_type="text/plain"
        ),
    ):
        with pytest.raises(ValueError):
            operation()
    assert (sibling / "keep.txt").read_text() == "keep"


def test_public_assets_hide_legacy_uploads_and_keep_bundled_artwork(tmp_path):
    from backend.app.avatar_http import AvatarSafeStaticFiles

    assets = tmp_path / "assets"
    (assets / "avatars/custom").mkdir(parents=True)
    (assets / "avatars/library").mkdir()
    (assets / "avatars/custom/x.svg").write_text("<svg onload='alert(1)'/>")
    (assets / "avatars/library/default-avatar-01.svg").write_text("<svg/>")
    app = FastAPI()
    app.mount("/assets", AvatarSafeStaticFiles(directory=assets))
    with TestClient(app) as client:
        assert client.get("/assets/avatars/custom/x.svg").status_code == 404
        assert (
            client.get("/assets/avatars/library/default-avatar-01.svg").status_code
            == 200
        )


def test_session_close_cleans_uncommitted_uploads(harness):
    client, engine, _, root = harness
    previous = client.post("/users/me/avatar", json={"data_url": data_url()}).json()
    with Session(engine) as db:
        user = db.get(models.User, "self")
        set_user_avatar_from_data_url(db, user, data_url=data_url(), actor=user)
    assert len(list((root / "media").rglob("*.webp"))) == 2
    assert client.get(previous["avatar_url"]).status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"name": " "},
        {"name": "x" * 256},
        {"avatar_frame": "unknown"},
        {"phone": "x" * 51},
    ],
)
def test_profile_write_bounds(harness, payload):
    client, *_ = harness
    assert client.patch("/users/me", json=payload).status_code == 422


def test_profile_version_accepts_equivalent_timezone_offset(harness):
    from datetime import datetime, timedelta, timezone

    client, *_ = harness
    current = datetime.fromisoformat(client.get("/users/self").json()["updated_at"])
    equivalent = current.replace(tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    )
    assert (
        client.patch(
            "/users/me",
            json={
                "profile_bio": "offset match",
                "expected_updated_at": equivalent.isoformat(),
            },
        ).status_code
        == 200
    )


def test_chunked_oversized_avatar_request_is_bounded(harness):
    client, *_ = harness

    def chunks():
        for _ in range(8):
            yield b"x" * (1024 * 1024)

    assert (
        client.post(
            "/users/me/avatar",
            content=chunks(),
            headers={"content-type": "application/json"},
        ).status_code
        == 413
    )


def test_shared_custom_avatar_is_retained_until_last_reference_is_removed(harness):
    client, engine, identity, root = harness
    uploaded = client.post("/users/me/avatar", json={"data_url": data_url()}).json()
    with Session(engine) as db:
        db.get(models.User, "self").role = models.RoleEnum.ADMIN
        db.commit()
    assert (
        client.patch(
            "/users/colleague", json={"avatar_asset_id": uploaded["avatar_asset_id"]}
        ).status_code
        == 200
    )
    assert client.patch("/users/me", json={"avatar_asset_id": None}).status_code == 200
    assert client.get(uploaded["avatar_url"]).status_code == 200
    identity["id"] = "colleague"
    assert client.patch("/users/me", json={"avatar_asset_id": None}).status_code == 200
    assert client.get(uploaded["avatar_url"]).status_code == 404
    assert not list((root / "media").rglob("*.webp"))


def test_failed_thumbnail_write_cleans_partial_files_and_preserves_previous(
    harness, monkeypatch
):
    from backend.app.storage.local import LocalAdapter

    client, _, _, root = harness
    previous = client.post("/users/me/avatar", json={"data_url": data_url()}).json()
    original_save = LocalAdapter.save

    def fail_thumbnail(self, binary, path, **kwargs):
        if path.endswith("_128.webp"):
            raise OSError("Fixture disk failure")
        return original_save(self, binary, path, **kwargs)

    monkeypatch.setattr(LocalAdapter, "save", fail_thumbnail)
    with pytest.raises(OSError, match="Fixture disk failure"):
        client.post("/users/me/avatar", json={"data_url": data_url()})
    assert len(list((root / "media").rglob("*.webp"))) == 2
    assert client.get(previous["avatar_url"]).status_code == 200


def test_exif_orientation_and_metadata_are_normalized():
    from backend.app.avatar_utils import encode_avatar

    source = Image.new("RGB", (80, 40), "red")
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "<script>private metadata</script>"
    raw = BytesIO()
    source.save(raw, format="JPEG", exif=exif)
    clean = load_avatar_image(raw.getvalue(), mime_type="image/jpeg")
    assert clean.size == (40, 80)
    output = encode_avatar(clean, 512)
    assert b"private metadata" not in output
    assert not Image.open(BytesIO(output)).getexif()


def test_api_prefixed_library_upload_has_same_request_limit(harness):
    client, engine, *_ = harness
    client.app.include_router(avatars.router, prefix="/api")
    with Session(engine) as db:
        db.get(models.User, "self").role = models.RoleEnum.OWNER
        db.commit()

    def chunks():
        for _ in range(8):
            yield b"x" * (1024 * 1024)

    assert (
        client.post(
            "/api/avatars",
            content=chunks(),
            headers={"content-type": "application/json"},
        ).status_code
        == 413
    )


def test_nested_identity_serialization_uses_protected_urls(harness):
    from backend.app import schemas

    client, engine, *_ = harness
    original = client.post("/users/me/avatar", json={"data_url": data_url()}).json()
    with Session(engine) as db:
        user = db.get(models.User, "self")
        nested = schemas.UserRead.model_validate(user).model_dump()
        assert nested["avatar_asset"]["url"] == original["avatar_url"]
        assert nested["avatar_asset"]["data_url"] is None


def test_legacy_files_are_normalized_and_unsafe_content_is_never_served(
    harness, monkeypatch
):
    client, engine, _, root = harness
    monkeypatch.chdir(root)
    folder = root / "assets/avatars/custom"
    folder.mkdir(parents=True)
    (folder / "old.png").write_bytes(picture())
    (folder / "bad.svg").write_text("<svg onload='alert(1)'/>")
    with Session(engine) as db:
        tenant = db.get(models.User, "self").tenant_id
        for key, path in (
            ("legacy-raster", "avatars/custom/old.png"),
            ("legacy-svg", "avatars/custom/bad.svg"),
            ("legacy-path", "../outside.png"),
        ):
            db.add(
                models.AvatarAsset(
                    id=key,
                    name=key,
                    tenant_id=tenant,
                    created_by_id="self",
                    file_path=path,
                )
            )
        db.commit()
    image = client.get("/avatars/legacy-raster/image?thumbnail=true")
    assert image.status_code == 200 and image.headers["content-type"] == "image/webp"
    assert Image.open(BytesIO(image.content)).size == (128, 128)
    assert client.get("/avatars/legacy-svg/image").status_code == 400
    assert client.get("/avatars/legacy-path/image").status_code == 404


def test_missing_private_storage_configuration_never_silently_switches_provider(
    harness, monkeypatch
):
    client, *_ = harness
    monkeypatch.setattr(get_settings(), "storage_provider", "minio")
    assert (
        client.post("/users/me/avatar", json={"data_url": data_url()}).status_code
        == 503
    )


def test_presigned_avatar_workflow_uses_canonical_storage_and_removes_original(
    harness, monkeypatch
):
    from backend.app import schemas
    from backend.app.services import minio_media_service as service

    client, engine, *_ = harness
    objects = {"staged/self.png": picture()}

    class Store:
        def get_object(self, *, Bucket, Key, **_kwargs):
            return {"Body": BytesIO(objects[Key])}

        def head_object(self, *, Bucket, Key):
            return {"ContentLength": len(objects[Key])}

        def put_object(self, *, Bucket, Key, Body, ContentType):
            objects[Key] = Body

        def delete_object(self, *, Bucket, Key):
            objects.pop(Key, None)

    monkeypatch.setattr(service, "_get_minio_client", lambda: Store())
    monkeypatch.setattr(get_settings(), "minio_access_key", "fixture")
    monkeypatch.setattr(get_settings(), "minio_secret_key", "fixture")
    with Session(engine) as db:
        media = models.MediaFile(
            id="presigned",
            user_id="self",
            media_type=models.MediaFileTypeEnum.AVATAR,
            bucket="fixture",
            object_key="staged/self.png",
            original_filename="portrait.png",
            content_type="image/png",
            size_bytes=len(picture()),
            status=models.MediaFileStatusEnum.PENDING,
        )
        db.add(media)
        db.commit()
        user = db.get(models.User, "self")
        service.confirm_media_upload(db, user=user, file_id=media.id)
        _, key, url = service.finalize_avatar_upload(
            db,
            user=user,
            file_id=media.id,
            crop_metadata={"x": 0, "y": 0, "width": 60, "height": 60},
        )
        assert key.startswith("private-avatars/") and url.startswith("/avatars/")
        assert db.get(models.MediaFile, media.id).deleted_at is not None
        serialized = schemas.UserRead.model_validate(user).model_dump()
        assert serialized["avatar_asset"]["url"] == url
    assert "staged/self.png" not in objects and len(objects) == 2
    assert client.get(url).status_code == 200


def test_bundled_artwork_urls_use_the_same_proxy_safe_image_route(harness, monkeypatch):
    from backend.app.avatar_utils import avatar_public_url

    client, engine, identity, root = harness
    monkeypatch.chdir(root)
    folder = root / "assets/avatars/library"
    folder.mkdir(parents=True)
    artwork = '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"></svg>'
    (folder / "default-avatar-01.svg").write_text(artwork)
    with Session(engine) as db:
        asset = models.AvatarAsset(
            id="avatar-default-01",
            name="Bundled",
            is_default=True,
            file_path="avatars/library/default-avatar-01.svg",
        )
        db.add(asset)
        db.commit()
        url = avatar_public_url(asset)
    assert url.startswith("/avatars/avatar-default-01/image")
    for actor in ("self", "foreign"):
        identity["id"] = actor
        image = client.get(url)
        assert (
            image.status_code == 200
            and image.headers["content-type"] == "image/svg+xml"
        )
        assert (
            image.text == artwork
            and "sandbox" in image.headers["content-security-policy"]
        )
