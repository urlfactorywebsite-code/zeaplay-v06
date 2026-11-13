"""Fixed-origin read-only REST adapter. No database/application dependency."""

import ipaddress
import json
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx2 as httpx

from . import upstream
from .auth import AuthorizationContext
from .errors import SafeError
from .models import GetTaskInput, ListSubtasksInput, ListTasksInput
from .request_identity import RequestAuthorization
from .security import redact_text

_GET = re.compile(r"^/(?:auth/me|tasks/page|tasks/activity|__phase2b__/attest|tasks/[A-Za-z0-9_-]{1,36}/information)$")
_URL = re.compile(
    r"(?i)(?:(?:[a-z][a-z0-9+.-]*:)?//|www\.)[^\s<>\"']+"
    r"|(?:/?(?:uploads|private-avatars|avatars|media|tenant|assets|task_templates)/)[^\s<>\"']+"
    r"|/?(?:api/)?users/[A-Za-z0-9_-]{1,36}/avatar-image(?:[?#][^\s<>\"']*)?"
)


def loopback_origin(value: str) -> str:
    try:
        url = urlsplit(value)
        valid = (url.scheme == "http" and ipaddress.ip_address(url.hostname).is_loopback
                 and url.port is not None and 0 < url.port <= 65535
                 and url.path in ("", "/") and not url.query and not url.fragment
                 and url.username is None and url.password is None)
        if valid:
            return value.rstrip("/")
    except (ValueError, TypeError):
        pass
    raise ValueError("Isolated REST requires an explicit numeric loopback origin and port")


def safe_text(value: str) -> str:
    return _URL.sub("[media reference omitted]", redact_text(value))


def stamp(value: str | None) -> str | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # Existing ZeaPlay Task columns store naive UTC; information uses aware UTC.
    return dt.replace(tzinfo=UTC).isoformat() if dt.tzinfo is None else dt.isoformat()


class BackendClient:
    """Shared connection pool; credentials are always per request, never defaults.

    POST is exclusively the trusted test broker's fixed login control plane.
    Tool adapters expose GET operations only. No redirects/proxies/cookie auth.
    """

    def __init__(self, origin: str, *, timeout: float = 5.0, transport=None):
        self.origin = loopback_origin(origin)
        if not 0.01 <= timeout <= 10:
            raise ValueError("Invalid HTTP timeout")
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout), limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
            follow_redirects=False, trust_env=False, transport=transport,
        )

    async def close(self):
        await self.client.aclose()

    async def json(self, method: str, path: str, *, credential: str | None = None, params=None, body=None):
        if not ((method == "GET" and _GET.fullmatch(path)) or (method == "POST" and path == "/auth/login")):
            raise SafeError("AUTH_DENIED")
        headers = {"Accept": "application/json", "Accept-Encoding": "identity", "Cookie": ""}
        if credential is not None:
            headers["Authorization"] = "Bearer " + credential
        try:
            async with self.client.stream(method, self.origin + path, headers=headers, params=params, json=body) as response:
                code = response.status_code
                if code == 401:
                    raise SafeError("AUTH_REQUIRED")
                if code == 403:
                    raise SafeError("AUTH_DENIED")
                if code == 404:
                    raise SafeError("NOT_FOUND")
                if code == 409:
                    raise SafeError("CONFLICT")
                if code == 422:
                    raise SafeError("INVALID_ARGUMENTS")
                if code == 429 or code >= 500:
                    raise SafeError("UPSTREAM_UNAVAILABLE")
                if code != 200 or response.headers.get("content-type", "").split(";")[0].lower() != "application/json":
                    raise SafeError("UPSTREAM_INVALID")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise SafeError("UPSTREAM_INVALID")
                length = response.headers.get("content-length")
                if length is not None and int(length) > 1024 * 1024:
                    raise SafeError("OUTPUT_LIMIT")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 1024 * 1024:
                        raise SafeError("OUTPUT_LIMIT")
                def invalid_constant(_):
                    raise ValueError("Invalid JSON number")
                data = json.loads(raw, parse_constant=invalid_constant)
                if not isinstance(data, dict):
                    raise ValueError("Object required")
                return data
        except httpx.TimeoutException:
            raise SafeError("TIMEOUT") from None
        except httpx.TransportError:
            raise SafeError("UPSTREAM_UNAVAILABLE") from None
        except (ValueError, RecursionError):
            raise SafeError("UPSTREAM_INVALID") from None


class AuthenticatedRestAdapter:
    source = "rest"

    def __init__(self, backend: BackendClient, authorization: RequestAuthorization):
        self.backend, self.authorization = backend, authorization

    async def _principal(self, context: AuthorizationContext):
        binding = self.authorization.binding(context)
        principal = upstream.Principal.model_validate(await self.backend.json("GET", "/auth/me", credential=binding.credential))
        if (principal.id != context.user_id or principal.role != context.role
                or principal.status != "ACTIVE" or principal.department_id != context.department_id):
            raise SafeError("AUTH_DENIED")
        return binding

    async def _get(self, context, path, params=None):
        binding = await self._principal(context)
        return await self.backend.json("GET", path, credential=binding.credential, params=params)

    async def list_tasks(self, context, query: ListTasksInput, *, overdue: bool):
        # Validate again even if called outside ToolService.
        query = ListTasksInput.model_validate(query.model_dump())
        params = query.model_dump(exclude_none=True)
        if overdue:
            params["quick_filter"] = "overdue"
        raw = upstream.Page.model_validate(await self._get(context, "/tasks/page", params))
        if raw.page != query.page or raw.page_size != query.page_size:
            raise SafeError("UPSTREAM_INVALID")
        result = raw.model_dump()
        for item in result["items"]:
            item["title"] = safe_text(item["title"])
            for key in ("due_at", "created_at", "updated_at"):
                item[key] = stamp(item[key])
        await self._principal(context)
        self.authorization.attest(context, [t.id for t in raw.items])
        return result

    async def information(self, context, task_id: str, section: str, query: ListSubtasksInput | None = None):
        GetTaskInput(task_id=task_id)
        if section not in {"overview", "subtasks"} or (section == "subtasks" and query is None):
            raise SafeError("INVALID_ARGUMENTS")
        params = {"section": section}
        if query is not None:
            params.update(page=query.page, page_size=query.page_size, search=query.search or "")
        raw = upstream.Information.model_validate(await self._get(context, f"/tasks/{task_id}/information", params))
        if raw.viewer_id != context.user_id or raw.task_id != task_id or raw.section != section:
            raise SafeError("AUTH_DENIED")
        result = raw.model_dump()
        result["as_of"] = stamp(raw.as_of)
        result["coverage"] = safe_text(raw.coverage)
        if section == "overview":
            if raw.overview is None or raw.overview.id != task_id:
                raise SafeError("UPSTREAM_INVALID")
            overview = result["overview"]
            overview["name"] = safe_text(overview["name"])
            # Free-form descriptions can embed legacy attachment keys/URLs.
            overview["description"] = ""
            overview["team"] = safe_text(overview["team"])
            for key in ("due_at", "created_at", "updated_at"):
                overview[key] = stamp(overview[key])
        else:
            for child in result["items"]:
                child["name"] = safe_text(child["name"])
        await self._principal(context)
        self.authorization.attest(context, [task_id])
        return result

    async def workload(self, context):
        raw = upstream.Activity.model_validate(await self._get(context, "/tasks/activity"))
        if raw.user_id != context.user_id:
            raise SafeError("AUTH_DENIED")
        result = raw.model_dump()
        result["server_now"] = stamp(raw.server_now)
        for key in ("period_start", "period_end"):
            result["workload"][key] = stamp(result["workload"][key])
        if result["workload"]["capacity_note"] is not None:
            result["workload"]["capacity_note"] = safe_text(result["workload"]["capacity_note"])
        result["coverage"] = "Current backend self-only workload; no delegated production access."
        await self._principal(context)
        return result
