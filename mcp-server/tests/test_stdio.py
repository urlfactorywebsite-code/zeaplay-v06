import asyncio
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager

import anyio
import pytest
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from zeaplay_mcp.catalog import CATALOG

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def local_client(tmp_path, label="a-member", extra=None, mode="auto"):
    env = {"ZEAPLAY_MCP_FIXTURE_IDENTITY": label} if label else {}
    env.update(extra or {})
    server = StdioServerParameters(
        command=sys.executable, args=["-I", "-m", "zeaplay_mcp"], env=env, cwd=tmp_path
    )
    with (tmp_path / ("stderr-" + str(label) + ".log")).open(
        "w", encoding="utf8"
    ) as log:
        async with Client(
            stdio_client(server, errlog=log), mode=mode, read_timeout_seconds=8
        ) as client:
            yield client


@pytest.mark.parametrize(
    "mode,version", [("auto", "2026-07-28"), ("legacy", "2025-11-25")]
)
async def test_real_stdio_sdk_discovery_and_all_five_calls(tmp_path, mode, version):
    async with local_client(tmp_path, mode=mode) as client:
        assert client.protocol_version == version
        assert {t.name for t in (await client.list_tools()).tools} == set(CATALOG)
        for name in CATALOG:
            args = (
                {"task_id": "a-assigned"}
                if name in {"zeaplay_get_task", "zeaplay_list_subtasks"}
                else {}
            )
            r = await client.call_tool(name, args)
            assert not r.is_error and r.structured_content["source"] == "mock"
    lines = (tmp_path / "stderr-a-member.log").read_text().splitlines()
    events = [json.loads(line) for line in lines]
    assert len([e for e in events if e.get("event") == "tool_completed"]) == 5
    assert all("fixture-secret" not in line for line in lines)


async def test_multiple_stdio_processes_are_isolated_and_metadata_cannot_impersonate(
    tmp_path,
):
    async with (
        local_client(tmp_path, "a-member") as a,
        local_client(tmp_path, "b-member") as b,
    ):
        ra, rb = await asyncio.gather(
            a.call_tool(
                "zeaplay_list_tasks",
                {},
                meta={"tenant_id": "tenant-b", "actor_id": "b-owner"},
            ),
            b.call_tool("zeaplay_list_tasks", {}),
        )
        assert all(
            t["id"].startswith("a-") for t in ra.structured_content["data"]["items"]
        )
        assert [t["id"] for t in rb.structured_content["data"]["items"]] == [
            "b-assigned"
        ]
        denied = await a.call_tool("zeaplay_get_task", {"task_id": "b-assigned"})
        assert denied.is_error


async def test_stdio_missing_identity_and_failure_scenarios(tmp_path):
    async with local_client(tmp_path, None) as client:
        r = await client.call_tool("zeaplay_list_tasks", {})
        assert r.structured_content["error"]["code"] == "AUTH_REQUIRED"
    for scenario, code in [
        ("timeout", "TIMEOUT"),
        ("upstream_failure", "UPSTREAM_UNAVAILABLE"),
    ]:
        async with local_client(
            tmp_path,
            extra={
                "ZEAPLAY_MCP_SCENARIO": scenario,
                "ZEAPLAY_MCP_TIMEOUT_SECONDS": "0.03",
            },
        ) as client:
            r = await client.call_tool("zeaplay_list_tasks", {})
            assert r.is_error and r.structured_content["error"]["code"] == code
    assert "fixture-secret" not in (tmp_path / "stderr-a-member.log").read_text()


async def test_real_stdio_cancellation_keeps_connection_usable(tmp_path):
    async with local_client(
        tmp_path,
        extra={"ZEAPLAY_MCP_SCENARIO": "slow", "ZEAPLAY_MCP_TIMEOUT_SECONDS": "10"},
    ) as client:
        task = asyncio.create_task(client.call_tool("zeaplay_list_tasks", {}))
        await anyio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        r = await client.call_tool("zeaplay_get_task", {"task_id": "a-assigned"})
        assert not r.is_error
    assert '"outcome":"CANCELLED"' in (tmp_path / "stderr-a-member.log").read_text()


async def test_cli_health_config_and_transport_refuse_live_mode(tmp_path):
    base = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
    }

    def run(args, extra=None):
        return subprocess.run(
            [sys.executable, "-I", "-m", "zeaplay_mcp", *args],
            env=base | (extra or {}),
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    ready = run(["--check"], {"ZEAPLAY_MCP_FIXTURE_IDENTITY": "a-member"})
    assert ready.returncode == 0 and json.loads(ready.stdout)["ready"]
    assert (
        json.loads(ready.stdout)["alive"] and json.loads(ready.stdout)["mode"] == "mock"
    )
    missing = run(["--check"])
    assert missing.returncode == 3 and not json.loads(missing.stdout)["ready"]
    assert run(["--transport", "streamable-http"]).returncode == 2
    assert (
        run(["--check"], {"ZEAPLAY_MCP_FIXTURE_IDENTITY": "real-owner"}).returncode == 2
    )
    rejected = run(
        ["--check"],
        {
            "ZEAPLAY_MCP_BACKEND_URL": "https://production.invalid",
            "ZEAPLAY_MCP_TOKEN": "fake-sensitive-marker",
        },
    )
    assert rejected.returncode == 2 and "fake-sensitive-marker" not in rejected.stderr
    # Existing app env cannot configure this independent process.
    ignored = run(
        ["--check"],
        {
            "ZEAPLAY_MCP_FIXTURE_IDENTITY": "a-member",
            "VEE_DATABASE_URL": "postgresql://forbidden.invalid/unused",
        },
    )
    assert ignored.returncode == 0 and json.loads(ignored.stdout)["live_rest"] is False
