# ZeaPlay Phase 2A mock MCP server

Independent, local, read-only prototype. **All data and identities are synthetic.**
It has no ZeaPlay HTTP client, database connection, credential acquisition, OAuth
implementation, public listener or application imports.

The [Phase 2A report](../docs/mcp/PHASE_2A_MCP_PROTOTYPE.md) contains contracts,
boundaries, evidence and the live-integration gate.

## Setup (PowerShell, from repository root)

Verified on Windows with Python 3.14.3. Project requires Python 3.11 or later;
other Python versions and operating systems were not executed.

```powershell
python -m venv mcp-server/.venv
.\mcp-server\.venv\Scripts\python.exe -m pip --isolated install --index-url https://pypi.org/simple -r mcp-server/requirements.lock.txt
.\mcp-server\.venv\Scripts\python.exe -m pip --isolated install --no-deps --no-build-isolation ./mcp-server
.\mcp-server\.venv\Scripts\python.exe -m pip check
```

The lock includes exact runtime, build and test dependencies. `pywin32` is
Windows-only. SDK HTTP/JWT dependencies are transitive packages; this service
does not configure or use their live transport/authentication capabilities.
Reinstall the local wheel after changing source, using the same install command.
Neither editable installation nor backend dependencies are needed.

## Local readiness and launch

```powershell
$env:ZEAPLAY_MCP_FIXTURE_IDENTITY = 'a-member'
.\mcp-server\.venv\Scripts\python.exe -I -m zeaplay_mcp --check
.\mcp-server\.venv\Scripts\python.exe -I -m zeaplay_mcp --transport stdio
```

The second command is a protocol process: connect it to an MCP stdio client.
It does not serve a web page. Protocol messages use stdout; structured logs use
stderr. `--check` is a separate local CLI invocation, not an MCP tool or HTTP
endpoint. Exit 0 means the selected fixture is ready; 3 means no usable fixture
authority; 2 means invalid settings. `alive: true` refers only to this CLI process.

An SDK client can launch the process without setting the parent environment:

```python
import asyncio
import sys
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    parameters = StdioServerParameters(
        command=sys.executable,  # this project's installed virtual environment
        args=["-I", "-m", "zeaplay_mcp"],
        env={"ZEAPLAY_MCP_FIXTURE_IDENTITY": "a-member"},
    )
    async with Client(stdio_client(parameters)) as client:
        print((await client.list_tools()).tools)
        print((await client.call_tool("zeaplay_list_tasks", {"page_size": 2})).structured_content)

asyncio.run(main())
```

Launch settings are trusted operator inputs, never tool arguments. See the report
for fixture labels, failure simulations and numeric bounds. No setting accepts
a backend URL or token. Do not put real credentials in this service's environment.

## Isolated verification

```powershell
.\mcp-server\.venv\Scripts\python.exe -I -m pytest mcp-server/tests -q --junitxml=mcp-server/checks/pytest-final.xml
.\mcp-server\.venv\Scripts\python.exe -I mcp-server/scripts/record_protocol_evidence.py
```

These commands collect only the new project's tests. They do not run existing
application tests, start Docker, import FastAPI or access a database. Child
processes run from disposable empty working directories. The evidence script
rewrites only its own `mcp-server/checks/` protocol/schema/log artifacts.

Supported tools: `zeaplay_list_tasks`, `zeaplay_get_task`,
`zeaplay_list_overdue_tasks`, `zeaplay_list_subtasks`,
`zeaplay_get_workload_summary` (self-only).

**Phase 2B live integration remains NO-GO.** Mock authorization cannot establish
production tenant isolation, consent, delegation or revocation guarantees.
