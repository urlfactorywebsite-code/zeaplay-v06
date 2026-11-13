"""Record official SDK stdio discovery/call evidence using synthetic data only.

Run with this project's installed virtual environment and Python -I. Neither
the current directory nor application environment chooses a backend or actor.
"""

import asyncio
import json
import platform
import sys
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import jsonschema
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from zeaplay_mcp.catalog import CATALOG


async def main() -> None:
    output = Path(__file__).resolve().parents[1] / "checks"
    output.mkdir(exist_ok=True)
    sessions, schemas = [], {}
    for mode in ("auto", "legacy"):
        with TemporaryDirectory(prefix="zeaplay-mock-stdio-") as empty_cwd:
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-I", "-m", "zeaplay_mcp"],
                env={"ZEAPLAY_MCP_FIXTURE_IDENTITY": "a-member"},
                cwd=empty_cwd,
            )
            with (output / f"stdio-{mode}.stderr.jsonl").open(
                "w", encoding="utf-8"
            ) as log:
                async with Client(
                    stdio_client(parameters, errlog=log),
                    mode=mode,
                    read_timeout_seconds=8,
                ) as client:
                    tools = (await client.list_tools()).tools
                    assert {tool.name for tool in tools} == set(CATALOG)
                    calls = []
                    for tool in tools:
                        schema = {
                            "inputSchema": tool.input_schema,
                            "outputSchema": tool.output_schema,
                            "annotations": tool.annotations.model_dump(by_alias=True),
                        }
                        for key in ("inputSchema", "outputSchema"):
                            jsonschema.Draft202012Validator.check_schema(schema[key])
                        if mode == "legacy":
                            assert schemas[tool.name] == schema
                        schemas[tool.name] = schema
                        arguments = (
                            {"task_id": "a-assigned"}
                            if tool.name
                            in {"zeaplay_get_task", "zeaplay_list_subtasks"}
                            else {}
                        )
                        result = await client.call_tool(tool.name, arguments)
                        assert not result.is_error
                        jsonschema.Draft202012Validator(
                            tool.output_schema,
                            format_checker=jsonschema.FormatChecker(),
                        ).validate(result.structured_content)
                        assert result.structured_content["source"] == "mock"
                        assert (
                            json.loads(result.content[0].text)
                            == result.structured_content
                        )
                        calls.append({"tool": tool.name, "result": "PASS"})
                    sessions.append(
                        {
                            "mode": mode,
                            "protocol_version": client.protocol_version,
                            "transport": "stdio",
                            "fixture_identity": "a-member",
                            "calls": calls,
                        }
                    )
    evidence = {
        "result": "PASS",
        "scope": "Offline mock protocol only; no live backend or browser",
        "python": platform.python_version(),
        "platform": platform.system(),
        "sdk": {
            name: version(name) for name in ("mcp", "mcp-types", "pydantic", "anyio")
        },
        "sessions": sessions,
    }
    for name, payload in (("protocol.json", evidence), ("tool-schemas.json", schemas)):
        (output / name).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
