"""Settings authorization checks. Run with VEE_DATABASE_URL=sqlite:///:memory:."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import models
from backend.app.database import get_db
from backend.app.dependencies import get_current_active_user
from backend.app.routers import ai, config, data_admin, feature_flags


@pytest.fixture
def settings_app(monkeypatch):
    app = FastAPI()
    app.include_router(config.router)
    app.include_router(data_admin.router)
    app.include_router(feature_flags.router)
    app.include_router(ai.router)
    app.dependency_overrides[get_db] = lambda: None
    monkeypatch.setattr(config, "_get_or_create_api_config", lambda db, tenant_id: SimpleNamespace(provider="Fixture", api_key="fixture-credential"))
    return app


@pytest.mark.parametrize("role", list(models.RoleEnum))
def test_api_configuration_never_exposes_credential_to_ordinary_members(settings_app, role):
    settings_app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(role=role, tenant_id="fixture-tenant")
    with TestClient(settings_app) as client:
        response = client.get("/config/api")
    if role in (models.RoleEnum.USER, models.RoleEnum.MANAGER):
        assert response.status_code == 403
        assert 'fixture-credential' not in response.text
    else:
        assert response.status_code == 200
        assert response.json()['api_key'] == 'fixture-credential' 


@pytest.mark.parametrize("method,path,role", [
    ("GET", "/config/smtp/multiple", models.RoleEnum.USER),
    ("GET", "/config/oauth", models.RoleEnum.USER),
    ("PATCH", "/config/api", models.RoleEnum.USER),
    ("GET", "/feature-flags/", models.RoleEnum.USER),
    ("GET", "/feature-flags/", models.RoleEnum.MANAGER),
    ("GET", "/feature-flags/", models.RoleEnum.ADMIN),
    ("GET", "/admin/data/export", models.RoleEnum.USER),
    ("GET", "/admin/data/export", models.RoleEnum.MANAGER),
    ("GET", "/admin/data/export", models.RoleEnum.ADMIN),
])
def test_direct_sensitive_requests_are_forbidden_before_database_access(settings_app, method, path, role):
    settings_app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(role=role, tenant_id="fixture-tenant")
    with TestClient(settings_app) as client:
        response = client.request(method, path, json={"provider": "Fixture"} if method == "PATCH" else None)
    assert response.status_code == 403


def test_signed_out_configuration_request_is_rejected(settings_app):
    with TestClient(settings_app) as client:
        response = client.get("/config/api")
    assert response.status_code == 401


@pytest.fixture
def ai_client(settings_app, monkeypatch):
    settings_app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(role=models.RoleEnum.USER, tenant_id="fixture-tenant")
    monkeypatch.setattr(ai, "_keys", lambda db, tenant_id: ["fixture-provider-secret"])
    monkeypatch.setattr(ai, "get_settings", lambda: SimpleNamespace(gemini_daily_limit=60, ai_webhook_url="https://example.test/ai"))
    ai._usage.clear()
    with TestClient(settings_app) as client:
        yield client


def test_ai_generation_preserves_prompts_and_schema_without_returning_keys(ai_client, monkeypatch):
    import httpx
    captured = {}

    def post(url, body, key=None):
        captured.update(url=url, body=body, key=key)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Fixture answer"}]}}]})

    monkeypatch.setattr(ai, "_post", post)
    response = ai_client.post("/ai/generate", json={"model": "gemini-2.5-flash", "contents": "Fixture prompt", "config": {"systemInstruction": "Fixture instruction", "responseMimeType": "application/json", "responseSchema": {"type": "OBJECT"}}})
    assert response.status_code == 200
    assert response.json() == {"text": "Fixture answer"}
    assert captured["key"] == "fixture-provider-secret"
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "Fixture instruction"
    assert captured["body"]["generationConfig"]["responseSchema"] == {"type": "OBJECT"}
    assert "fixture-provider-secret" not in response.text


def test_ai_model_cannot_override_upstream_destination(ai_client):
    response = ai_client.post("/ai/generate", json={"model": "../../other-host", "contents": "Fixture"})
    assert response.status_code == 422


def test_ai_provider_errors_do_not_echo_credentials(ai_client, monkeypatch):
    import httpx
    monkeypatch.setattr(ai, "_post", lambda *args: httpx.Response(400, text="fixture-provider-secret"))
    response = ai_client.post("/ai/generate", json={"model": "gemini-2.5-flash", "contents": "Fixture"})
    assert response.status_code == 502
    assert "fixture-provider-secret" not in response.text


def test_ai_webhook_uses_server_destination_and_redacts_echoed_keys(ai_client, monkeypatch):
    import httpx
    captured = {}

    def post(url, body, key=None):
        captured.update(url=url, body=body)
        return httpx.Response(200, json={"reply": "Reply fixture-provider-secret"})

    monkeypatch.setattr(ai, "_post", post)
    response = ai_client.post("/ai/message", json={"message": "Fixture", "sessionId": "test", "payload": {"apiKey": "client-key"}, "webhookUrl": "https://untrusted.test/"})
    assert response.status_code == 200
    assert captured["url"] == "https://example.test/ai"
    assert captured["body"]["apiKey"] == "fixture-provider-secret"
    assert response.json() == {"reply": "Reply [REDACTED_SECRET]"}


def test_ai_quota_failure_tries_another_server_key(ai_client, monkeypatch):
    import httpx
    monkeypatch.setattr(ai, "_keys", lambda db, tenant_id: ["fixture-key-one", "fixture-key-two"])
    calls = []

    def post(url, body, key=None):
        calls.append(key)
        return httpx.Response(429) if len(calls) == 1 else httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Retried"}]}}]})

    monkeypatch.setattr(ai, "_post", post)
    response = ai_client.post("/ai/generate", json={"model": "gemini-2.5-flash", "contents": "Fixture"})
    assert response.status_code == 200
    assert len(calls) == 2 and calls[0] != calls[1]


@pytest.mark.parametrize("path,body", [("/ai/generate", {"model": "gemini-2.5-flash", "contents": "Fixture"}), ("/ai/message", {"message": "Fixture"})])
def test_signed_out_ai_requests_are_rejected(settings_app, path, body):
    with TestClient(settings_app) as client:
        response = client.post(path, json=body)
    assert response.status_code == 401
