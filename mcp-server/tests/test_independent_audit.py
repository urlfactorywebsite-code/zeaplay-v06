"""Independent Phase 2A checks; all protocol peers and resources are local."""

import asyncio
import json
import os
import queue
import subprocess
import sys
import threading
from contextlib import contextmanager

import anyio
import jsonschema
import pytest
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from zeaplay_mcp.adapter import MockRestAdapter
from zeaplay_mcp.auth import FixtureAuthorization
from zeaplay_mcp.config import Settings
from zeaplay_mcp.fixtures import identity
from zeaplay_mcp.server import create_server
from zeaplay_mcp.service import ToolService

pytestmark = pytest.mark.anyio
EXPECTED = (
    "zeaplay_list_tasks",
    "zeaplay_get_task",
    "zeaplay_list_overdue_tasks",
    "zeaplay_list_subtasks",
    "zeaplay_get_workload_summary",
)
VISIBLE = {"a-assigned", "a-created", "a-injection"}


def arguments(name):
    return {"task_id": "a-assigned"} if name in {EXPECTED[1], EXPECTED[3]} else {}


def launch(tmp_path, label="a-member", **settings):
    env = {"ZEAPLAY_MCP_FIXTURE_IDENTITY": label} if label else {}
    env.update(settings)
    return StdioServerParameters(
        command=sys.executable,
        args=["-I", "-m", "zeaplay_mcp"],
        cwd=tmp_path,
        env=env,
    )


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_stdio_discovery_arguments_and_privilege_escalation(tmp_path, mode):
    with (tmp_path / "audit.stderr.jsonl").open("w", encoding="utf8") as log:
        async with Client(
            stdio_client(launch(tmp_path), errlog=log),
            mode=mode,
            read_timeout_seconds=6,
        ) as client:
            tools = (await client.list_tools()).tools
            assert tuple(t.name for t in tools) == EXPECTED
            assert tuple(t.name for t in (await client.list_tools()).tools) == EXPECTED
            for name in (EXPECTED[0], EXPECTED[2], EXPECTED[4]):
                assert not (await client.call_tool(name)).is_error
            for tool in tools:
                for schema in (tool.input_schema, tool.output_schema):
                    jsonschema.Draft202012Validator.check_schema(schema)
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.open_world_hint is False
                result = await client.call_tool(tool.name, arguments(tool.name))
                assert not result.is_error
                jsonschema.validate(result.structured_content, tool.output_schema)
                for key, value in (
                    ("tenant_id", "tenant-b"),
                    ("user_id", "b-owner"),
                    ("actor_id", "a-owner"),
                    ("role", "owner"),
                    ("scopes", ["*"]),
                    ("authorization", {"tenant_id": "tenant-b", "role": "owner"}),
                    ("url", "https://production.invalid"),
                    ("token", "audit-sensitive-marker"),
                ):
                    denied = await client.call_tool(
                        tool.name, arguments(tool.name) | {key: value}
                    )
                    assert denied.is_error, (tool.name, key)
                    assert denied.structured_content["data"] is None
                    assert (
                        denied.structured_content["error"]["code"]
                        == "INVALID_ARGUMENTS"
                    )
                    assert "audit-sensitive-marker" not in denied.content[0].text
            for bad in (
                {"page": True},
                {"page": "1"},
                {"page_size": 101},
                {"search": "x" * 5000},
            ):
                denied = await client.call_tool(EXPECTED[0], bad)
                assert denied.is_error
                assert denied.structured_content["error"]["code"] == "INVALID_ARGUMENTS"
            for hidden in ("b-assigned", "a-sibling", "a-other-department", "absent"):
                for name in (EXPECTED[1], EXPECTED[3]):
                    denied = await client.call_tool(name, {"task_id": hidden})
                    assert denied.is_error
                    assert denied.structured_content["data"] is None
                    assert denied.structured_content["error"]["code"] == "NOT_FOUND"
            result = await client.call_tool(
                EXPECTED[0], {}, meta={"tenant_id": "tenant-b", "role": "owner"}
            )
            assert {
                t["id"] for t in result.structured_content["data"]["items"]
            } == VISIBLE
    assert "audit-sensitive-marker" not in (tmp_path / "audit.stderr.jsonl").read_text()


@pytest.mark.parametrize("label", [None, "a-revoked", "a-inactive", "a-no-scopes"])
async def test_stdio_every_tool_rejects_missing_or_unusable_authority(tmp_path, label):
    with (tmp_path / "denials.stderr.jsonl").open("w", encoding="utf8") as log:
        async with Client(stdio_client(launch(tmp_path, label), errlog=log)) as client:
            for name in EXPECTED:
                result = await client.call_tool(name, arguments(name))
                assert result.is_error and result.structured_content["data"] is None
                assert result.structured_content["error"]["code"] == (
                    "AUTH_REQUIRED" if label is None else "AUTH_DENIED"
                )


async def test_real_stdio_concurrent_calls_do_not_mix_results_or_elevate_identity(
    tmp_path,
):
    with (tmp_path / "concurrent.stderr.jsonl").open("w", encoding="utf8") as log:
        async with Client(stdio_client(launch(tmp_path), errlog=log)) as client:
            await client.list_tools()
            requests = [
                (EXPECTED[0], {"page_size": 1, "page": 1}),
                (EXPECTED[1], {"task_id": "a-assigned"}),
                (EXPECTED[1], {"task_id": "b-assigned"}),
                (EXPECTED[3], {"task_id": "a-sibling"}),
                (EXPECTED[4], {"user_id": "a-owner"}),
                (EXPECTED[4], {}),
            ] * 4
            results = await asyncio.gather(
                *(client.call_tool(n, a) for n, a in requests)
            )
            ids = set()
            for (name, args), result in zip(requests, results, strict=True):
                data = result.structured_content
                assert data["correlation_id"] not in ids
                ids.add(data["correlation_id"])
                if name == EXPECTED[0]:
                    assert {row["id"] for row in data["data"]["items"]} == {
                        "a-assigned"
                    }
                    assert data["data"]["total"] == 3
                elif (
                    args.get("task_id") in {"b-assigned", "a-sibling"}
                    or "user_id" in args
                ):
                    assert result.is_error and data["data"] is None
                else:
                    assert not result.is_error
                    if name == EXPECTED[4]:
                        assert data["data"]["user_id"] == "a-alice"


async def test_concurrent_adapter_work_respects_process_capacity():
    auth = FixtureAuthorization(identity("a-member"))

    class CountingAdapter(MockRestAdapter):
        active = 0
        peak = 0

        async def workload(self, context):
            self.active += 1
            self.peak = max(self.active, self.peak)
            try:
                await anyio.sleep(0.02)
                return await super().workload(context)
            finally:
                self.active -= 1

    adapter = CountingAdapter(auth)
    async with Client(
        create_server(Settings(max_concurrency=2), auth, adapter)
    ) as client:
        results = await asyncio.gather(
            *(client.call_tool(EXPECTED[4], {}) for _ in range(12))
        )
    assert all(not r.is_error for r in results)
    assert adapter.peak == 2 and adapter.active == 0


@contextmanager
def raw_stdio(tmp_path):
    """A raw legacy wire peer avoids SDK coercion when testing malformed frames."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
    }
    env["ZEAPLAY_MCP_FIXTURE_IDENTITY"] = "a-member"
    with (tmp_path / "raw.stderr.jsonl").open("w", encoding="utf8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-I", "-m", "zeaplay_mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            cwd=tmp_path,
            env=env,
        )
        inbox = queue.Queue()

        def receive():
            for line in proc.stdout:
                inbox.put(line)

        reader = threading.Thread(target=receive, daemon=True)
        reader.start()
        next_id = 0

        def send(method, params=None):
            nonlocal next_id
            next_id += 1
            request = {"jsonrpc": "2.0", "id": next_id, "method": method}
            if params is not None:
                request["params"] = params
            proc.stdin.write(json.dumps(request).encode("utf8") + b"\n")
            proc.stdin.flush()
            line = inbox.get(timeout=6)
            reply = json.loads(line)
            assert reply["jsonrpc"] == "2.0" and reply["id"] == next_id
            return reply

        try:
            hello = send(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "phase2a-independent-audit",
                        "version": "1.0",
                    },
                },
            )
            assert hello["result"]["capabilities"] == {"tools": {"listChanged": False}}
            assert hello["result"]["protocolVersion"] == "2025-11-25"
            proc.stdin.write(
                b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
            )
            proc.stdin.flush()
            assert (
                tuple(t["name"] for t in send("tools/list")["result"]["tools"])
                == EXPECTED
            )
            yield send
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            proc.stdout.close()
            reader.join(timeout=1)
    assert "audit-sensitive-marker" not in (tmp_path / "raw.stderr.jsonl").read_text()


def test_raw_malformed_envelopes_and_write_methods_are_rejected(tmp_path):
    with raw_stdio(tmp_path) as send:
        for params in (
            {"name": EXPECTED[0], "arguments": ["audit-sensitive-marker"]},
            {"name": EXPECTED[0], "arguments": "audit-sensitive-marker"},
            {"name": EXPECTED[0], "arguments": True},
            {"name": ["audit-sensitive-marker"], "arguments": {}},
            {"arguments": {"password": "audit-sensitive-marker"}},
        ):
            reply = send("tools/call", params)
            assert reply["error"]["code"] == -32602
            assert "audit-sensitive-marker" not in json.dumps(reply)
        for name in (
            "delete_task",
            "zeaplay_delete_task",
            "zeaplay_update_task",
            "GET",
        ):
            assert (
                send("tools/call", {"name": name, "arguments": {}})["error"]["code"]
                == -32602
            )
        assert send("arbitrary/write", {})["error"]["code"] == -32601
        assert (
            send("tools/list", {"cursor": "audit-sensitive-marker"})["error"]["code"]
            == -32602
        )
        assert (
            send("tools/call", {"name": EXPECTED[0], "arguments": {}})["result"][
                "isError"
            ]
            is False
        )


def test_raw_explicit_null_arguments_do_not_bypass_object_schema(tmp_path):
    with raw_stdio(tmp_path) as send:
        for name in EXPECTED:
            reply = send("tools/call", {"name": name, "arguments": None})
            assert reply["error"]["code"] == -32602
        # Omitted optional arguments still mean the default empty object.
        assert send("tools/call", {"name": EXPECTED[0]})["result"]["isError"] is False


async def test_non_utf8_argument_text_is_an_input_error_not_upstream_failure():
    auth = FixtureAuthorization(identity("a-member"))
    adapter = MockRestAdapter(auth)
    service = ToolService(Settings(), auth, adapter)
    result = await service.call(EXPECTED[0], {"search": "\ud800"})
    assert result.is_error
    assert result.structured_content["error"]["code"] == "INVALID_ARGUMENTS"
    assert adapter.calls == []
