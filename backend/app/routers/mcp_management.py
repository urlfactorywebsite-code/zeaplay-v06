"""Administrative readiness only. No protocol, credentials, probes or storage.

There is no approved tenant MCP policy/grant store in the current schema.
Never substitute a process dictionary, browser storage, provider configuration,
navigation rules or global feature flags for durable tenant authorization.
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from ..dependencies import get_current_api_admin
from ..models import User
from ..database import get_db
import os


ToolId = Literal[
    "zeaplay_list_tasks", "zeaplay_get_task", "zeaplay_list_overdue_tasks",
    "zeaplay_list_subtasks", "zeaplay_get_workload_summary",
]
ToolRole = Literal["user", "manager", "admin", "owner"]
# Public catalog metadata only. Do not import the separate MCP runtime into API.
TOOLS = (
    ("zeaplay_list_tasks", "List tasks", "Read tasks visible to the current user.", "tasks:read"),
    ("zeaplay_get_task", "Get task", "Read an authorized task overview.", "tasks:read"),
    ("zeaplay_list_overdue_tasks", "List overdue tasks", "Read visible overdue tasks.", "tasks:read"),
    ("zeaplay_list_subtasks", "List subtasks", "Read subtasks after parent task authorization.", "tasks:read"),
    ("zeaplay_get_workload_summary", "Workload summary", "Read only the current user's workload.", "workload:read"),
)
STORAGE_BLOCKER = "Tenant MCP policy storage requires an approved schema. Changes cannot be saved."


async def mcp_admin(request: Request, response: Response,
                    user: User = Depends(get_current_api_admin)) -> User:
    # Identity comes only from the existing active, session-validated database user.
    try:
        UUID(str(user.tenant_id))
    except (AttributeError, TypeError, ValueError):
        raise HTTPException(403, "Authenticated tenant context is required")
    if request.query_params:
        raise HTTPException(422, "MCP management does not accept query parameters")
    response.headers["Cache-Control"] = "no-store"
    return user


class ManagementRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_response(request: Request):
            try:
                response = await handler(request)
            except RequestValidationError:
                # Pydantic's default errors echo submitted values, potentially
                # including a pasted credential. Management never reflects them.
                # Locations include arbitrary extra-field names as well as
                # values. Return a fixed error rather than reflecting either.
                response = JSONResponse(status_code=422, content={
                    "detail": {"code": "MCP_INVALID_REQUEST", "message": "Invalid MCP management request."}})
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
                raise
            response.headers["Cache-Control"] = "no-store"
            return response

        return safe_response


router = APIRouter(prefix="/mcp-management", tags=["mcp-management"], route_class=ManagementRoute)


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    read_only: Literal[True]
    allowed_tool_ids: list[ToolId] = Field(max_length=5)
    allowed_roles: list[ToolRole] = Field(max_length=4)
    reason: str = Field(min_length=1, max_length=500)
    expected_revision: int = Field(default=0, ge=0, strict=True)

    @field_validator("read_only", mode="before")
    @classmethod
    def only_read_only(cls, value):
        if value is not True:
            raise ValueError("Only read-only MCP tools are approved")
        return value

    @field_validator("allowed_tool_ids", "allowed_roles")
    @classmethod
    def no_duplicates(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Duplicate policy entries are not allowed")
        return value

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("A reason is required")
        return value.strip()


class EmergencyDisable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


@router.get("")
def management_snapshot(user: User = Depends(mcp_admin), db=Depends(get_db)):
    """Fail-closed defaults are explicitly not persisted configuration/health."""
    result = {
        "tenant_context": str(user.tenant_id),
        "configuration": {
            "available": False, "persisted": False, "blocker": STORAGE_BLOCKER,
            "enabled": False, "read_only": True, "allowed_tool_ids": [],
            "allowed_roles": [], "emergency_disabled": None,
        },
        "overview": {
            "service_status": "not_configured", "health_status": "not_monitored",
            "last_checked_at": None, "total_tools": len(TOOLS), "enabled_tools": 0,
            "active_connections": None, "security_mode": "Read-only / remote access blocked",
            "endpoint": None, "remote_access_enabled": False,
        },
        "tools": [{"id": id, "name": name, "description": description, "scope": scope,
                   "read_only": True, "enabled": False, "available": False}
                  for id, name, description, scope in TOOLS],
        "connections": {"available": False, "items": [],
                        "reason": "OAuth and delegated user consent are not implemented for MCP."},
        "security": {
            "management_authentication": "Existing ZeaPlay session; Owner/Admin only",
            "mcp_authentication": "Not ready for remote clients",
            "oauth_delegation": "Not implemented for MCP",
            "credential_handling": "No MCP credentials issued, accepted or stored by management",
            "remote_connections": "Unavailable",
            "restrictions": ["Only the five approved read-only tools",
                             "Current backend task and tenant permissions remain authoritative",
                             "No API key shortcut or production connection creation",
                             "Remote access requires OAuth, consent, durable policy enforcement and deployment review"],
        },
        "activity": {"available": False, "items": [],
                     "reason": "Tenant MCP activity logging is not implemented. No activity data is available."},
    }
    if os.environ.get('ZEA_MCP_PHASE4A_ISOLATED') == '1':
        from ..mcp.management import snapshot
        return snapshot(db, user, result)
    return result


def storage_unavailable():
    # Even a valid enable request cannot activate a service or write other tables.
    raise HTTPException(503, {"code": "MCP_POLICY_STORAGE_UNAVAILABLE", "message": STORAGE_BLOCKER},
                        headers={"Cache-Control": "no-store"})


@router.patch("/policy")
def update_policy(payload: PolicyUpdate, user: User = Depends(mcp_admin), db=Depends(get_db)):
    if os.environ.get('ZEA_MCP_PHASE4A_ISOLATED') == '1':
        from ..mcp.management import update
        return update(db, user, payload)
    storage_unavailable()


@router.post("/emergency-disable")
def emergency_disable(payload: EmergencyDisable, user: User = Depends(mcp_admin), db=Depends(get_db)):
    # Never return a successful emergency stop without durable enforcement.
    if os.environ.get('ZEA_MCP_PHASE4A_ISOLATED') == '1':
        from ..mcp.management import emergency
        return emergency(db, user)
    storage_unavailable()
