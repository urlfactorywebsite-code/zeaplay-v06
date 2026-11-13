"""Explicit process configuration; no dotenv, backend origins or credentials."""

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FixtureIdentity = Literal[
    "a-member",
    "a-peer",
    "a-observer",
    "a-manager",
    "a-owner",
    "b-member",
    "b-owner",
    "a-revoked",
    "a-inactive",
    "a-no-scopes",
]
Scenario = Literal["normal", "timeout", "upstream_failure", "slow"]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    fixture_identity: FixtureIdentity | None = None
    scenario: Scenario = "normal"
    timeout_seconds: float = Field(default=1.0, ge=0.01, le=10)
    max_output_bytes: int = Field(default=131072, ge=1024, le=131072)
    max_concurrency: int = Field(default=4, ge=1, le=16)

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> "Settings":
        values = os.environ if env is None else env
        names = {
            "ZEAPLAY_MCP_FIXTURE_IDENTITY": "fixture_identity",
            "ZEAPLAY_MCP_SCENARIO": "scenario",
            "ZEAPLAY_MCP_TIMEOUT_SECONDS": "timeout_seconds",
            "ZEAPLAY_MCP_MAX_OUTPUT_BYTES": "max_output_bytes",
            "ZEAPLAY_MCP_MAX_CONCURRENCY": "max_concurrency",
        }
        if any(k.startswith("ZEAPLAY_MCP_") and k not in names for k in values):
            raise ValueError("Unsupported prototype setting")
        data: dict[str, object] = {
            target: values[key] for key, target in names.items() if key in values
        }
        if "timeout_seconds" in data:
            data["timeout_seconds"] = float(str(data["timeout_seconds"]))
        for key in ("max_output_bytes", "max_concurrency"):
            if key in data:
                data[key] = int(str(data[key]))
        return cls.model_validate(data)
