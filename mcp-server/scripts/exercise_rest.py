"""Real MCP clients against a guarded disposable ZeaPlay backend. No mocks."""

import asyncio
import json
import os
from pathlib import Path
import sys

import httpx2 as httpx
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

NAMES = ("zeaplay_list_tasks", "zeaplay_get_task", "zeaplay_list_overdue_tasks",
         "zeaplay_list_subtasks", "zeaplay_get_workload_summary")
results = []


def check(name, value):
    results.append({"case": name, "result": "PASS" if value else "FAIL"})
    if not value:
        raise RuntimeError(name)


def data(result):
    check("REST result envelope", not result.is_error and result.structured_content["source"] == "rest")
    raw = result.model_dump_json()
    check("No attachment/key/capability leakage", all(v not in raw for v in
        ("PRIVATE_MEDIA_SENTINEL", "PRIVATE_KEY_SENTINEL", "PRIVATE_USER_SENTINEL", "@phase2b.example.com",
         "hashed_password", "profile_image_url", "storage_path", "object_key", "attachments", "access_token", "refresh_token")))
    return result.structured_content["data"]


async def exercise(client, fixture, alias, label):
    tasks, users = fixture["tasks"], fixture["users"]
    tools = (await client.list_tools()).tools
    check(label + " five-tool discovery", tuple(t.name for t in tools) == NAMES)
    check(label + " read-only tool annotations", all(t.annotations.read_only_hint for t in tools))
    try:
        await client.call_tool("zeaplay_delete_task", {"task_id": tasks["a-main"]})
    except MCPError as exc:
        check(label + " write tool rejected", exc.code == -32602)
    else:
        check(label + " write tool rejected", False)
    listed = data(await client.call_tool(NAMES[0], {"page_size": 1}))
    check(label + " bounded pagination", len(listed["items"]) == 1 and listed["total"] == 2 and listed["has_more"])
    second = data(await client.call_tool(NAMES[0], {"page": 2, "page_size": 1}))
    check(label + " next page", second["items"][0]["id"] != listed["items"][0]["id"])
    overview = data(await client.call_tool(NAMES[1], {"task_id": tasks["a-main"]}))
    check(label + " authorized task", overview["overview"]["id"] == tasks["a-main"] and overview["overview"]["description"] == "")
    overdue = data(await client.call_tool(NAMES[2], {}))
    check(label + " overdue REST filter", {x["id"] for x in overdue["items"]} == {tasks["a-main"], tasks["a-second"]})
    children = data(await client.call_tool(NAMES[3], {"task_id": tasks["a-main"], "page_size": 2}))
    check(label + " paginated subtasks", len(children["items"]) == 2 and children["total"] == 3 and children["has_more"])
    workload = data(await client.call_tool(NAMES[4], {}))
    check(label + " self-only workload", workload["user_id"] == users[alias] and "contexts" not in workload)
    for hidden in (tasks["a-peer-task"], tasks["b-main"], "absent"):
        for tool in (NAMES[1], NAMES[3]):
            denied = await client.call_tool(tool, {"task_id": hidden})
            check(label + " unauthorized/foreign/missing task denial", denied.is_error and denied.structured_content["error"]["code"] in {"NOT_FOUND", "AUTH_DENIED"})
    for extra in ({"tenant_id":"tenant-b"}, {"token":"MODEL_CONTROLLED_SENTINEL"}, {"role":"owner"}, {"url":"https://production.invalid"}):
        denied = await client.call_tool(NAMES[0], extra)
        check(label + " model identity rejected", denied.is_error and denied.structured_content["error"]["code"] == "INVALID_ARGUMENTS" and "MODEL_CONTROLLED_SENTINEL" not in denied.model_dump_json())
    unchanged = data(await client.call_tool(NAMES[0], {}, meta={"user_id": users["b-member"], "role":"owner"}))
    check(label + " metadata cannot select identity", {x["id"] for x in unchanged["items"]} == {tasks["a-main"], tasks["a-second"]})


async def backend_auth_checks(config, fixtures):
    """Target current real auth/tenant handlers; no signed-token fabrication."""
    account=config["accounts"]["a-peer"]
    async with httpx.AsyncClient(base_url=config["backend_origin"],trust_env=False,timeout=10) as client:
        wrong=await client.post("/auth/login",json={"email":account["email"],"password":"deliberately-wrong-fixture-password"})
        check("backend rejects incorrect password",wrong.status_code==401)
        first=await client.post("/auth/login",data={"username":account["email"],"password":account["password"]})
        check("backend form login",first.status_code==200)
        other=await client.post("/auth/login",json={"email":account["email"],"password":account["password"]})
        check("backend independent JSON login",other.status_code==200)
        first_token=first.json()["token"]
        rotated=await client.post("/auth/refresh",json={"refresh_token":first_token["refresh_token"],"tenant_id":"forged"},headers={"X-Tenant-ID":"forged"})
        check("backend refresh rotation",rotated.status_code==200)
        current=rotated.json()["access_token"]
        foreign=await client.get("/tasks/"+fixtures["tasks"]["b-main"]+"/information",headers={"Authorization":"Bearer "+current,"X-Tenant-ID":"forged"})
        check("backend rejects cross-tenant read despite spoofed tenant",foreign.status_code in (403,404))
        workload=await client.get("/tasks/activity",params={"user_id":fixtures["users"]["b-member"]},headers={"Authorization":"Bearer "+current})
        check("backend forbids foreign workload selection",workload.status_code in (403,404))
        replay=await client.post("/auth/refresh",json={"refresh_token":first_token["refresh_token"]})
        check("backend rejects refresh reuse",replay.status_code==401)
        stale=await client.get("/auth/me",headers={"Authorization":"Bearer "+current})
        check("backend reuse revokes rotated access",stale.status_code==401)
        survivor=await client.get("/auth/me",headers={"Authorization":"Bearer "+other.json()["token"]["access_token"]})
        check("backend preserves independent session",survivor.status_code==200)
        loggedout=await client.post("/auth/logout",headers={"Authorization":"Bearer "+other.json()["token"]["access_token"]})
        check("backend logout",loggedout.status_code in (200,204))
        stale=await client.get("/auth/me",headers={"Authorization":"Bearer "+other.json()["token"]["access_token"]})
        check("backend logged-out credential remains invalid",stale.status_code==401)


async def main(root: Path, http_origin: str):
    config = json.loads((root / "broker.json").read_text())
    fixtures = json.loads((root / "fixtures.json").read_text())
    await backend_auth_checks(config,fixtures)
    env = {k:v for k,v in os.environ.items() if k.upper() in {"SYSTEMROOT","WINDIR","PATH","TEMP","TMP","COMSPEC"}}
    env["ZEAPLAY_MCP_TIMEOUT_SECONDS"] = "5"
    params = StdioServerParameters(command=sys.executable, args=["-I","-B","-m","zeaplay_mcp",
        "--mode","rest","--isolated-test","--broker-config",str(root/"broker.json"),"--identity","a-member"], cwd=root, env=env)
    with (root / "stdio.jsonl").open("w") as log:
        async with Client(stdio_client(params, errlog=log), read_timeout_seconds=30) as client:
            await exercise(client, fixtures, "a-member", "stdio")
    # Discovery may work without a stdio binding; execution must not.
    params.args = params.args[:-2]
    with (root / "missing-identity.jsonl").open("w") as log:
        async with Client(stdio_client(params, errlog=log), read_timeout_seconds=30) as client:
            denied = await client.call_tool(NAMES[0], {})
            check("stdio missing identity", denied.is_error and denied.structured_content["error"]["code"] == "AUTH_REQUIRED")
    async with httpx.AsyncClient(trust_env=False, timeout=10) as raw:
        check("HTTP missing broker capability", (await raw.post(http_origin+"/mcp", json={})).status_code == 401)
        check("HTTP browser origin denied", (await raw.post(http_origin+"/mcp", headers={"Origin":"http://evil.invalid"},json={})).status_code == 403)
        capability = config["accounts"]["a-member"]["capability"]
        check("HTTP invalid broker capability", (await raw.post(http_origin+"/mcp",
            headers={"x-zeaplay-test-broker": "invalid-capability"}, json={})).status_code == 401)
        check("HTTP duplicate identity headers denied", (await raw.post(http_origin+"/mcp",
            headers=[("x-zeaplay-test-broker",capability), ("x-zeaplay-test-broker",config["accounts"]["b-member"]["capability"])],
            json={})).status_code == 401)
        check("HTTP hostile Host denied with valid capability", (await raw.post(http_origin+"/mcp",
            headers={"x-zeaplay-test-broker":capability,"Host":"evil.invalid"},json={})).status_code == 421)
    clients = []
    transport_clients = []
    from contextlib import AsyncExitStack
    async with AsyncExitStack() as stack:
        for alias in ("a-member","b-member","a-manager","a-owner"):
            transport_client = await stack.enter_async_context(httpx.AsyncClient(
                headers={"x-zeaplay-test-broker":config["accounts"][alias]["capability"]},trust_env=False,timeout=20))
            client = await stack.enter_async_context(Client(streamable_http_client(http_origin+"/mcp", http_client=transport_client), read_timeout_seconds=30))
            clients.append(client)
            transport_clients.append(transport_client)
        await exercise(clients[0], fixtures, "a-member", "streamable-http")
        # One SDK client/pool must resolve each HTTP request's capability afresh.
        for alias in ("a-member", "b-member", "a-member"):
            transport_clients[0].headers["x-zeaplay-test-broker"] = config["accounts"][alias]["capability"]
            current = data(await clients[0].call_tool(NAMES[4], {}, meta={"user_id":fixtures["users"]["a-owner"]}))
            check("HTTP A-B-A uses request identity", current["user_id"] == fixtures["users"][alias])
        async def concurrent(index):
            slot = index % 2
            expected = {fixtures["tasks"]["b-main"]} if slot else {fixtures["tasks"]["a-main"], fixtures["tasks"]["a-second"]}
            if index % 3 == 0:
                listing = data(await clients[slot].call_tool(NAMES[0], {}))
                isolated = {t["id"] for t in listing["items"]} == expected
            elif index % 3 == 1:
                own = fixtures["tasks"]["b-main" if slot else "a-main"]
                overview = data(await clients[slot].call_tool(NAMES[1], {"task_id":own}))
                isolated = overview["overview"]["id"] == own
            else:
                workload = data(await clients[slot].call_tool(NAMES[4], {}))
                isolated = workload["user_id"] == fixtures["users"]["b-member" if slot else "a-member"]
            check("concurrent users remain isolated", isolated)
        await asyncio.gather(*(concurrent(i) for i in range(20)))
        manager = data(await clients[2].call_tool(NAMES[0], {}))
        check("Manager department scope", {t["id"] for t in manager["items"]} == {fixtures["tasks"]["a-main"], fixtures["tasks"]["a-second"]})
        owner = data(await clients[3].call_tool(NAMES[0], {}))
        check("Owner current tenant only", len(owner["items"]) == 3 and fixtures["tasks"]["b-main"] not in {t["id"] for t in owner["items"]})
        # Real durable invalidation through a fixture-only guarded control;
        # current production trigger revokes every session in this user's family.
        async with httpx.AsyncClient(trust_env=False, timeout=10) as raw:
            response = await raw.post(config["backend_origin"]+"/__phase2b__/revoke/a-member",
                headers={"x-fixture-control":config["attestation_secret"]})
            check("fixture credential revocation committed", response.status_code == 200)
        denied = await clients[0].call_tool(NAMES[0], {})
        check("revoked credentials denied by real backend", denied.is_error and denied.structured_content["error"]["code"] == "AUTH_REQUIRED")
        for alias in ("b-member", "a-member"):
            transport_clients[0].headers["x-zeaplay-test-broker"] = config["accounts"][alias]["capability"]
            current = await clients[0].call_tool(NAMES[4], {})
            if alias == "b-member":
                check("HTTP revoked A to B remains B", data(current)["user_id"] == fixtures["users"][alias])
            else:
                check("HTTP A-B-A does not restore revoked credentials", current.is_error and current.structured_content["error"]["code"] == "AUTH_REQUIRED")
        check("other user remains valid after revocation", data(await clients[1].call_tool(NAMES[4], {}))["user_id"] == fixtures["users"]["b-member"])


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve()
    try:
        asyncio.run(main(root, sys.argv[2]))
        outcome = "PASS"
    except BaseException as exc:
        outcome = "FAIL"
        results.append({"failure_type":type(exc).__name__})
    (root/"integration-results.json").write_text(json.dumps({"result":outcome,"checks":results},indent=2))
    print(json.dumps({"result":outcome,"checks":len(results),"failed":[r for r in results if r.get("result")=="FAIL"],"evidence":str(root/"integration-results.json")}))
    raise SystemExit(0 if outcome == "PASS" else 1)
