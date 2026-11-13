"""HTTP transport doubles only; real backend/protocol tests have a separate runner."""

import asyncio
import json

import httpx2 as httpx
import pytest

from zeaplay_mcp.auth import AuthorizationContext
from zeaplay_mcp.config import Settings
from zeaplay_mcp.request_identity import CredentialBinding, RequestAuthorization
from zeaplay_mcp.rest import AuthenticatedRestAdapter, BackendClient, loopback_origin
from zeaplay_mcp.service import ToolService

pytestmark = pytest.mark.anyio
NOW = "2026-11-12T00:00:00"


def binding(user="user-a"):
    context = AuthorizationContext(user, "tenant-a", "test", user,
        frozenset({"tasks:read", "workload:read"}), "user")
    return CredentialBinding(context, "synthetic-" + user)


def card(user="user-a"):
    return {"id": user, "title": "Task https://media.invalid/PRIVATE_MEDIA_SENTINEL",
        "status": "TODO", "priority": "MEDIUM", "assigned_to_id": user,
        "due_at": NOW, "created_at": NOW, "updated_at": NOW,
        "attachments": ["tenant/PRIVATE_KEY_SENTINEL"], "storage_path": "PRIVATE_KEY_SENTINEL"}


def page(user="user-a"):
    return {"items": [card(user)], "page": 1, "page_size": 20,
        "total": 1, "total_pages": 1, "has_more": False}


def service(handler, *, timeout=1.0):
    auth = RequestAuthorization()
    async def transport(request):
        user = request.headers.get("authorization", "").removeprefix("Bearer synthetic-")
        if request.url.path == "/auth/me":
            return httpx.Response(200, json={"id": user, "role": "user", "status": "ACTIVE", "department_id": None})
        return await handler(request, user)
    backend = BackendClient("http://127.0.0.1:19001", transport=httpx.MockTransport(transport))
    return auth, backend, ToolService(Settings(timeout_seconds=timeout), auth, AuthenticatedRestAdapter(backend, auth))


async def test_projection_utc_and_url_key_minimization():
    async def handler(request, user):
        assert request.method == "GET" and request.url.path == "/tasks/page"
        assert request.headers["cookie"] == ""
        return httpx.Response(200, json=page(user), headers={"Set-Cookie": "identity=should-not-cross-users"})
    auth, backend, tools = service(handler)
    try:
        with auth.bind(binding()):
            result = await tools.call("zeaplay_list_tasks", {})
        assert not result.is_error
        assert result.structured_content["source"] == "rest"
        raw = result.model_dump_json()
        assert all(value not in raw for value in ("PRIVATE_MEDIA_SENTINEL", "PRIVATE_KEY_SENTINEL", "storage_path", "attachments", "http://media"))
        assert "+00:00" in raw or "Z" in raw
        assert "authorization" not in backend.client.headers
    finally:
        await backend.close()


@pytest.mark.parametrize("status,expected", [(401,"AUTH_REQUIRED"),(403,"AUTH_DENIED"),(404,"NOT_FOUND"),
    (409,"CONFLICT"),(422,"INVALID_ARGUMENTS"),(429,"UPSTREAM_UNAVAILABLE"),
    (500,"UPSTREAM_UNAVAILABLE"),(302,"UPSTREAM_INVALID")])
async def test_safe_status_mapping(status, expected):
    async def handler(request, user):
        return httpx.Response(status, json={"detail":"password=DO_NOT_LEAK"}, headers={"Location":"https://production.invalid"})
    auth, backend, tools = service(handler)
    try:
        with auth.bind(binding()):
            result = await tools.call("zeaplay_list_tasks", {})
        assert result.is_error and result.structured_content["error"]["code"] == expected
        assert "DO_NOT_LEAK" not in result.model_dump_json()
    finally:
        await backend.close()


@pytest.mark.parametrize("payload", [{}, {"items":[]}, page() | {"page":True}, page() | {"total":-1}, page() | {"items":[card() | {"status":"FORGED"}]}])
async def test_invalid_upstream_is_rejected(payload):
    async def handler(request, user): return httpx.Response(200, json=payload)
    auth, backend, tools = service(handler)
    try:
        with auth.bind(binding()): result = await tools.call("zeaplay_list_tasks", {})
        assert result.is_error and result.structured_content["error"]["code"] == "UPSTREAM_INVALID"
    finally: await backend.close()


async def test_concurrent_identity_and_attestations_never_mix():
    async def handler(request, user):
        await asyncio.sleep(0.01 if user == "user-a" else 0)
        return httpx.Response(200, json=page(user))
    auth, backend, tools = service(handler)
    async def call(user):
        with auth.bind(binding(user)):
            result = await tools.call("zeaplay_list_tasks", {})
            assert not result.is_error
            assert result.structured_content["data"]["items"][0]["id"] == user
    try:
        await asyncio.gather(*(call("user-a" if i % 2 else "user-b") for i in range(20)))
        assert (await tools.call("zeaplay_list_tasks", {})).structured_content["error"]["code"] == "AUTH_REQUIRED"
    finally: await backend.close()


async def test_deadline_and_missing_authority():
    calls = []
    async def handler(request, user):
        calls.append(1)
        await asyncio.sleep(1)
        return httpx.Response(200, json=page(user))
    auth, backend, tools = service(handler, timeout=0.02)
    try:
        assert (await tools.call("zeaplay_list_tasks", {})).is_error and not calls
        with auth.bind(binding()): result = await tools.call("zeaplay_list_tasks", {})
        assert result.structured_content["error"]["code"] == "TIMEOUT"
    finally: await backend.close()


async def test_oversize_response_and_arbitrary_paths_denied():
    async def handler(request, user): return httpx.Response(200, content=json.dumps({"huge":"X" * (1024*1024)}), headers={"content-type":"application/json"})
    auth, backend, tools = service(handler)
    try:
        with auth.bind(binding()): result = await tools.call("zeaplay_list_tasks", {})
        assert result.structured_content["error"]["code"] == "OUTPUT_LIMIT"
        for method,path in [("GET","//production.invalid/tasks"),("POST","/tasks"),("DELETE","/tasks/x"),("GET","/tasks/../users/information")]:
            with pytest.raises(Exception) as error: await backend.json(method,path)
            assert error.value.code == "AUTH_DENIED"
    finally: await backend.close()


@pytest.mark.parametrize("origin", ["https://production.invalid","http://localhost:7211","http://127.0.0.1:7211/api",
    "http://user:pass@127.0.0.1:7211","http://192.168.1.1:80","http://127.0.0.1:7211/?key=x"])
async def test_origin_boundary(origin):
    with pytest.raises(ValueError): loopback_origin(origin)


async def test_revocation_during_response_suppresses_result():
    calls=0
    async def transport(request):
        nonlocal calls
        if request.url.path=="/auth/me":
            calls+=1
            return httpx.Response(200,json={"id":"user-a","role":"user","status":"ACTIVE"}) if calls==1 else httpx.Response(401,json={"detail":"revoked"})
        return httpx.Response(200,json=page())
    auth=RequestAuthorization()
    backend=BackendClient("http://127.0.0.1:19001",transport=httpx.MockTransport(transport))
    tools=ToolService(Settings(),auth,AuthenticatedRestAdapter(backend,auth))
    try:
        with auth.bind(binding()): result=await tools.call("zeaplay_list_tasks",{})
        assert result.is_error and result.structured_content["data"] is None
        assert result.structured_content["error"]["code"]=="AUTH_REQUIRED"
    finally: await backend.close()


async def test_foreign_viewer_response_is_not_projected():
    async def handler(request,user):
        item=card();item["name"]=item.pop("title");item.update(description="PRIVATE_KEY_SENTINEL",team="A",creator={"id":"user-a"},assignees=[])
        return httpx.Response(200,json={"viewer_id":"user-b","task_id":"user-a","section":"overview","as_of":NOW,"coverage":"Test","overview":item,"page":1,"page_size":25})
    auth,backend,tools=service(handler)
    try:
        with auth.bind(binding()):result=await tools.call("zeaplay_get_task",{"task_id":"user-a"})
        assert result.is_error and result.structured_content["error"]["code"]=="AUTH_DENIED"
        assert "PRIVATE_KEY_SENTINEL" not in result.model_dump_json()
    finally:await backend.close()


async def test_duplicate_broker_headers_cannot_mix_identity():
    from zeaplay_mcp.local_http import BrokerOnlyHTTP
    from types import SimpleNamespace
    called=[]
    async def app(scope,receive,send):called.append(True)
    middleware=BrokerOnlyHTTP(app,SimpleNamespace(resolve=lambda cap:object()))
    sent=[]
    async def receive():return {"type":"http.request","body":b""}
    async def send(message):sent.append(message)
    await middleware({"type":"http","client":("127.0.0.1",12345),"headers":[
        (b"x-zeaplay-test-broker",b"a"),(b"x-zeaplay-test-broker",b"b")]},receive,send)
    assert not called and sent[0]["status"]==401


@pytest.mark.parametrize("reference", [
    "//media.invalid/PRIVATE_MEDIA_SENTINEL",
    "/users/user-a/avatar-image?v=PRIVATE_MEDIA_SENTINEL",
    "/api/users/user-a/avatar-image?v=PRIVATE_MEDIA_SENTINEL",
    "/assets/task_templates/PRIVATE_MEDIA_SENTINEL.png",
    "task_templates/PRIVATE_MEDIA_SENTINEL.png",
    "media/workspace/dept/user/image/2026/11/PRIVATE_KEY_SENTINEL.png",
    "tenant/tenant-a/tickets/ticket-a/PRIVATE_KEY_SENTINEL.png",
])
async def test_retained_text_does_not_leak_media_references(reference):
    async def handler(request, user):
        item = card(user) | {"title": "Synthetic " + reference}
        if request.url.path == "/tasks/page":
            return httpx.Response(200, json=page(user) | {"items": [item]})
        section = request.url.params["section"]
        overview = item | {"name": item["title"], "description": reference,
            "team": reference, "assignees": [{"id": user, "email": "PRIVATE_USER_SENTINEL"}],
            "creator": {"id": user, "hashed_password": "PRIVATE_USER_SENTINEL"}}
        return httpx.Response(200, json={"viewer_id": user, "task_id": user,
            "section": section, "as_of": NOW, "coverage": reference,
            "overview": overview if section == "overview" else None,
            "items": [{"id": "child-a", "name": reference, "status": "TODO",
                "completed": False, "planned_start_date": None, "planned_end_date": None}]
                if section == "subtasks" else [],
            "page": 1, "page_size": 25, "total": 1})
    auth, backend, tools = service(handler)
    try:
        for name, args in [("zeaplay_list_tasks", {}), ("zeaplay_list_overdue_tasks", {}),
            ("zeaplay_get_task", {"task_id": "user-a"}),
            ("zeaplay_list_subtasks", {"task_id": "user-a"})]:
            with auth.bind(binding()):
                result = await tools.call(name, args)
            assert not result.is_error
            assert all(value not in result.model_dump_json() for value in
                ("PRIVATE_MEDIA_SENTINEL", "PRIVATE_KEY_SENTINEL", "PRIVATE_USER_SENTINEL"))
    finally:
        await backend.close()


async def test_broker_rejects_foreign_backend_before_password_login():
    from zeaplay_mcp.errors import SafeError
    from zeaplay_mcp.test_broker import BrokerConfig, TrustedTestBroker
    calls = []
    async def transport(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"run_id": "1" * 32, "proof": "invalid"})
    backend = BackendClient("http://127.0.0.1:19001", transport=httpx.MockTransport(transport))
    config = BrokerConfig(mode="isolated-test", run_id="1" * 32,
        backend_origin=backend.origin, attestation_secret="synthetic-" + "a" * 32,
        accounts={"a": {"email": "a@example.com", "password": "never-sent",
            "capability": "synthetic-" + "b" * 32}})
    broker = TrustedTestBroker(config, backend)
    try:
        with pytest.raises(SafeError) as error:
            await broker.start()
        assert error.value.code == "AUTH_DENIED"
        assert calls == [("GET", "/__phase2b__/attest")]
        assert broker.for_stdio("a") is None
    finally:
        await broker.close()
