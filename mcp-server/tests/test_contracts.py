import asyncio
import json
from dataclasses import replace

import anyio
import jsonschema
import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import EmptyResult, Request

from zeaplay_mcp.adapter import MockRestAdapter
from zeaplay_mcp.auth import FixtureAuthorization
from zeaplay_mcp.catalog import CATALOG
from zeaplay_mcp.config import Settings
from zeaplay_mcp.fixtures import identity
from zeaplay_mcp.server import create_server
from zeaplay_mcp.service import ToolService

pytestmark = pytest.mark.anyio
VALID = {
    "zeaplay_list_tasks": {},
    "zeaplay_get_task": {"task_id": "a-assigned"},
    "zeaplay_list_overdue_tasks": {},
    "zeaplay_list_subtasks": {"task_id": "a-assigned"},
    "zeaplay_get_workload_summary": {},
}


def make(label="a-member", **settings):
    return create_server(Settings(fixture_identity=label, **settings))


@pytest.mark.parametrize("name", list(CATALOG))
async def test_each_schema_and_valid_typed_result(name):
    async with Client(make()) as client:
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == set(CATALOG)
        tool = next(t for t in tools if t.name == name)
        for schema in (tool.input_schema, tool.output_schema):
            jsonschema.Draft202012Validator.check_schema(schema)
            assert (
                schema["type"] == "object" and schema["additionalProperties"] is False
            )
        assert (
            tool.annotations.read_only_hint
            and tool.annotations.open_world_hint is False
        )
        result = await client.call_tool(name, VALID[name])
        assert not result.is_error
        data = result.structured_content
        jsonschema.Draft202012Validator(
            tool.output_schema, format_checker=jsonschema.FormatChecker()
        ).validate(data)
        assert (
            data["ok"]
            and data["source"] == "mock"
            and data["untrusted_content"] is True
        )
        assert len(data["correlation_id"]) == 32
        assert json.loads(result.content[0].text) == data


@pytest.mark.parametrize(
    "name,args",
    [
        ("zeaplay_list_tasks", {"page": 0}),
        ("zeaplay_list_tasks", {"page": True}),
        ("zeaplay_list_tasks", {"page": "1"}),
        ("zeaplay_list_tasks", {"page": 1.0}),
        ("zeaplay_list_tasks", {"page": 10001}),
        ("zeaplay_list_tasks", {"page_size": 101}),
        ("zeaplay_list_tasks", {"search": "x" * 201}),
        ("zeaplay_list_tasks", {"status": "todo"}),
        ("zeaplay_list_tasks", {"priority": "OWNER"}),
        ("zeaplay_list_tasks", {"tenant_id": "tenant-b"}),
        ("zeaplay_list_overdue_tasks", {"quick_filter": "all"}),
        ("zeaplay_get_task", {}),
        ("zeaplay_get_task", {"task_id": "../b-assigned"}),
        ("zeaplay_get_task", {"task_id": "https://production.invalid"}),
        ("zeaplay_get_task", {"task_id": "a" * 37}),
        ("zeaplay_get_task", {"task_id": "a-assigned", "credentials": "secret"}),
        ("zeaplay_list_subtasks", {"task_id": "a-assigned", "page_size": 0}),
        ("zeaplay_list_subtasks", {"task_id": "a-assigned", "search": 17}),
        ("zeaplay_get_workload_summary", {"user_id": "b-alice"}),
        ("zeaplay_get_workload_summary", {"actor_id": "a-owner"}),
    ],
)
async def test_strict_input_denies_extra_identity_coercion_and_invalid_bounds(
    name, args
):
    auth = FixtureAuthorization(identity("a-member"))
    adapter = MockRestAdapter(auth)
    async with Client(create_server(Settings(), auth, adapter)) as client:
        result = await client.call_tool(name, args)
        assert (
            result.is_error
            and result.structured_content["error"]["code"] == "INVALID_ARGUMENTS"
        )
        assert adapter.calls == []
        jsonschema.validate(
            result.structured_content, CATALOG[name].output_model.model_json_schema()
        )
        assert "secret" not in result.content[0].text


@pytest.mark.parametrize(
    "label,code",
    [
        (None, "AUTH_REQUIRED"),
        ("a-revoked", "AUTH_DENIED"),
        ("a-inactive", "AUTH_DENIED"),
        ("a-no-scopes", "AUTH_DENIED"),
    ],
)
@pytest.mark.parametrize("name", list(CATALOG))
async def test_missing_inactive_revoked_unscoped_context_never_reaches_adapter(
    label, code, name
):
    auth = FixtureAuthorization(identity(label))
    adapter = MockRestAdapter(auth)
    async with Client(create_server(Settings(), auth, adapter)) as client:
        result = await client.call_tool(name, VALID[name])
        assert result.is_error and result.structured_content["error"]["code"] == code
        assert adapter.calls == []


@pytest.mark.parametrize(
    "label,expected",
    [
        ("a-member", {"a-assigned", "a-created", "a-injection"}),
        ("a-peer", {"a-sibling", "a-created"}),
        ("a-observer", {"a-assigned"}),
        ("a-manager", {"a-assigned", "a-sibling", "a-created", "a-injection"}),
        (
            "a-owner",
            {
                "a-assigned",
                "a-sibling",
                "a-created",
                "a-injection",
                "a-other-department",
            },
        ),
        ("b-member", {"b-assigned"}),
        ("b-owner", {"b-assigned"}),
    ],
)
async def test_fixture_roles_and_tenants_have_distinct_visible_sets(label, expected):
    async with Client(make(label)) as client:
        result = await client.call_tool("zeaplay_list_tasks", {})
        assert {t["id"] for t in result.structured_content["data"]["items"]} == expected
        assert result.structured_content["data"]["total"] == len(expected)


@pytest.mark.parametrize(
    "label,task",
    [
        ("a-member", "b-assigned"),
        ("b-owner", "a-assigned"),
        ("a-member", "a-sibling"),
        ("a-manager", "a-other-department"),
        ("a-member", "does-not-exist"),
    ],
)
@pytest.mark.parametrize("name", ["zeaplay_get_task", "zeaplay_list_subtasks"])
async def test_direct_and_nested_lookup_cannot_bypass_visibility(label, task, name):
    async with Client(make(label)) as client:
        result = await client.call_tool(name, {"task_id": task})
        assert (
            result.is_error
            and result.structured_content["error"]["code"] == "NOT_FOUND"
        )
        assert result.structured_content["data"] is None


async def test_pagination_filters_overdue_and_empty_pages():
    async with Client(make()) as client:
        pages = [
            (
                await client.call_tool(
                    "zeaplay_list_tasks", {"page": p, "page_size": 1}
                )
            ).structured_content["data"]
            for p in range(1, 5)
        ]
        assert [p["items"][0]["id"] for p in pages[:3]] == [
            "a-assigned",
            "a-created",
            "a-injection",
        ]
        assert all(p["total"] == 3 and p["total_pages"] == 3 for p in pages)
        assert (
            pages[0]["has_more"]
            and not pages[2]["has_more"]
            and pages[3]["items"] == []
        )
        filtered = (
            await client.call_tool(
                "zeaplay_list_tasks",
                {"status": "TODO", "priority": "HIGH", "search": "ASSIGNED"},
            )
        ).structured_content["data"]
        assert [t["id"] for t in filtered["items"]] == ["a-assigned"]
        overdue = (
            await client.call_tool("zeaplay_list_overdue_tasks", {})
        ).structured_content["data"]
        assert {t["id"] for t in overdue["items"]} == {"a-assigned", "a-injection"}
        children = (
            await client.call_tool(
                "zeaplay_list_subtasks", {"task_id": "a-assigned", "page_size": 2}
            )
        ).structured_content["data"]
        assert (
            len(children["items"]) == 2
            and children["total"] == 3
            and children["has_more"]
        )
        matched = (
            await client.call_tool(
                "zeaplay_list_subtasks", {"task_id": "a-assigned", "search": "3"}
            )
        ).structured_content["data"]
        assert [c["id"] for c in matched["items"]] == ["a-assigned-s3"]


@pytest.mark.parametrize("status", ["FAILED", "GRAVEYARD"])
async def test_overdue_preserves_current_rest_completed_status_semantics(status):
    auth = FixtureAuthorization(identity("a-member"))
    adapter = MockRestAdapter(auth)
    task = next(t for t in adapter._tasks if t["id"] == "a-created")
    task["status"] = status
    async with Client(create_server(Settings(), auth, adapter)) as client:
        result = await client.call_tool("zeaplay_list_overdue_tasks", {})
        assert not result.is_error
        assert "a-created" in {
            t["id"] for t in result.structured_content["data"]["items"]
        }


async def test_projection_injection_fixture_redaction_and_determinism():
    auth = FixtureAuthorization(identity("a-member"))
    adapter = MockRestAdapter(auth)
    async with Client(create_server(Settings(), auth, adapter)) as client:
        a = await client.call_tool("zeaplay_get_task", {"task_id": "a-injection"})
        b = await client.call_tool("zeaplay_get_task", {"task_id": "a-injection"})
        assert a.structured_content["data"] == b.structured_content["data"]
        assert (
            a.structured_content["correlation_id"]
            != b.structured_content["correlation_id"]
        )
        assert (
            "Ignore prior instructions"
            in a.structured_content["data"]["overview"]["title"]
        )
        assert "[REDACTED]" in a.content[0].text
        for secret in (
            "MUST_NOT_PROJECT",
            "fixture-secret",
            "user_profile",
            "tenant_id",
            "email",
            "api_key",
        ):
            assert secret not in a.content[0].text
        assert adapter.calls == [("GET", "/tasks/{id}/information")] * 2
        w = (
            await client.call_tool("zeaplay_get_workload_summary", {})
        ).structured_content["data"]
        assert w["user_id"] == "a-alice" and w["workload"]["capacity_seconds"] is None
        assert "contexts" not in w and "user_name" not in w


@pytest.mark.parametrize(
    "scenario,code",
    [("timeout", "TIMEOUT"), ("upstream_failure", "UPSTREAM_UNAVAILABLE")],
)
async def test_timeout_and_upstream_failures_are_sanitized(scenario, code):
    async with Client(make(scenario=scenario, timeout_seconds=0.02)) as client:
        r = await client.call_tool("zeaplay_list_tasks", {})
        assert r.is_error and r.structured_content["error"]["code"] == code
        assert r.structured_content["error"]["retryable"]
        assert (
            "fixture-secret" not in r.content[0].text
            and "Traceback" not in r.content[0].text
        )


async def test_output_limit_and_truncation_are_explicit():
    auth = FixtureAuthorization(identity("a-member"))
    adapter = MockRestAdapter(auth)
    adapter._tasks[0]["title"] = "x" * 800
    async with Client(create_server(Settings(), auth, adapter)) as client:
        r = await client.call_tool("zeaplay_get_task", {"task_id": "a-assigned"})
        assert len(r.structured_content["data"]["overview"]["title"]) == 256
        assert r.structured_content["data"]["truncated"]
    async with Client(make(max_output_bytes=1024)) as client:
        r = await client.call_tool("zeaplay_list_tasks", {})
        assert r.is_error and r.structured_content["error"]["code"] == "OUTPUT_LIMIT"
        assert len(r.model_dump_json().encode()) <= 1024


async def test_authority_is_rechecked_after_await():
    auth = FixtureAuthorization(identity("a-member"))

    class RevokingAdapter(MockRestAdapter):
        async def workload(self, context):
            raw = await super().workload(context)
            auth.context = replace(context, revoked=True)
            return raw

    async with Client(create_server(Settings(), auth, RevokingAdapter(auth))) as client:
        r = await client.call_tool("zeaplay_get_workload_summary", {})
        assert r.is_error and r.structured_content["error"]["code"] == "AUTH_DENIED"


async def test_bad_upstream_identity_and_schema_do_not_escape_projection():
    auth = FixtureAuthorization(identity("a-member"))

    class ForeignAdapter(MockRestAdapter):
        async def workload(self, context):
            r = await super().workload(context)
            r["user_id"] = "b-alice"
            return r

    async with Client(create_server(Settings(), auth, ForeignAdapter(auth))) as client:
        r = await client.call_tool("zeaplay_get_workload_summary", {})
        assert r.is_error and r.structured_content["error"]["code"] == "AUTH_DENIED"
    bad = MockRestAdapter(auth)
    bad._tasks[0]["status"] = "SECRET_STATUS"
    async with Client(create_server(Settings(), auth, bad)) as client:
        r = await client.call_tool("zeaplay_get_task", {"task_id": "a-assigned"})
        assert (
            r.is_error and r.structured_content["error"]["code"] == "UPSTREAM_INVALID"
        )
        assert "SECRET_STATUS" not in r.content[0].text


async def test_information_contract_names_and_subtask_workflow_states():
    auth = FixtureAuthorization(identity("a-member"))
    adapter = MockRestAdapter(auth)
    raw = await adapter.information(auth.context, "a-assigned", "overview")
    assert raw["overview"]["name"] == "Synthetic assigned task"
    async with Client(create_server(Settings(), auth, adapter)) as client:
        result = await client.call_tool(
            "zeaplay_list_subtasks", {"task_id": "a-assigned"}
        )
        assert not result.is_error
        assert [s["status"] for s in result.structured_content["data"]["items"]] == [
            "TODO",
            "PAUSED",
            "COMPLETED",
        ]


async def test_unknown_tool_and_unknown_protocol_method_are_protocol_errors():
    async with Client(make()) as client:
        with pytest.raises(MCPError) as e:
            await client.call_tool("delete_task", {"task_id": "a-assigned"})
        assert e.value.code == -32602 and e.value.message == "Unknown tool"
        with pytest.raises(MCPError) as e:
            await client.session.send_request(
                Request(method="arbitrary/write", params=None), EmptyResult
            )
        assert e.value.code == -32601


async def test_cancellation_propagates_and_releases_capacity():
    auth = FixtureAuthorization(identity("a-member"))
    adapter = MockRestAdapter(auth, "slow")
    service = ToolService(
        Settings(timeout_seconds=10.0, max_concurrency=1), auth, adapter
    )
    task = asyncio.create_task(service.call("zeaplay_list_tasks", {}))
    await anyio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert adapter.cancelled
    result = await service.call("zeaplay_get_task", {"task_id": "a-assigned"})
    assert not result.is_error


async def test_deadline_includes_waiting_for_capacity():
    auth = FixtureAuthorization(identity("a-member"))
    adapter = MockRestAdapter(auth)
    service = ToolService(
        Settings(timeout_seconds=0.02, max_concurrency=1), auth, adapter
    )
    occupied = object()
    await service.limiter.acquire_on_behalf_of(occupied)
    try:
        result = await service.call("zeaplay_list_tasks", {})
        assert result.is_error
        assert result.structured_content["error"]["code"] == "TIMEOUT"
        assert adapter.calls == []
    finally:
        service.limiter.release_on_behalf_of(occupied)
    result = await service.call("zeaplay_get_task", {"task_id": "a-assigned"})
    assert not result.is_error


@pytest.mark.parametrize(
    "name",
    ["zeaplay_get_task", "zeaplay_list_subtasks", "zeaplay_get_workload_summary"],
)
async def test_coverage_and_workload_note_clipping_is_explicit(name):
    auth = FixtureAuthorization(identity("a-member"))

    class VerboseAdapter(MockRestAdapter):
        async def information(self, context, task_id, section, query=None):
            raw = await super().information(context, task_id, section, query)
            raw["coverage"] = "x" * 300
            return raw

        async def workload(self, context):
            raw = await super().workload(context)
            raw["coverage"] = "x" * 300
            raw["workload"]["capacity_note"] = "x" * 300
            return raw

    async with Client(create_server(Settings(), auth, VerboseAdapter(auth))) as client:
        result = await client.call_tool(name, VALID[name])
        assert not result.is_error
        data = result.structured_content["data"]
        assert data["truncated"] and len(data["coverage"]) == 256
        if name == "zeaplay_get_workload_summary":
            assert len(data["workload"]["capacity_note"]) == 256
