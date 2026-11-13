"""Bounded execution, authorization recheck, explicit projection and safe errors."""

import json
import logging
import time
import uuid
from datetime import date, datetime

import anyio
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from .adapter import RestAdapter
from .auth import AuthorizationProvider
from .catalog import CATALOG
from .config import Settings
from .errors import MESSAGES, SafeError
from .models import (
    ErrorResult,
    Subtask,
    SubtaskPage,
    TaskCard,
    TaskOverview,
    TaskOverviewResult,
    TaskPage,
    Workload,
    WorkloadResult,
)
from .security import redact_text

logger = logging.getLogger("zeaplay_mcp")


def timestamp(raw: str | None) -> datetime | None:
    return None if raw is None else datetime.fromisoformat(raw.replace("Z", "+00:00"))


def text(raw: str, limit: int) -> tuple[str, bool]:
    if not isinstance(raw, str):
        raise SafeError("UPSTREAM_INVALID")
    safe = redact_text(raw)
    return safe[:limit], len(safe) > limit


def card(raw: dict) -> tuple[TaskCard, bool]:
    title, cut = text(raw["title"], 256)
    return TaskCard(
        id=raw["id"],
        title=title,
        status=raw["status"],
        priority=raw["priority"],
        assigned_to_id=raw["assigned_to_id"],
        due_at=timestamp(raw["due_at"]),
        created_at=timestamp(raw["created_at"]),
        updated_at=timestamp(raw["updated_at"]),
    ), cut


def wire(envelope: dict, is_error: bool) -> CallToolResult:
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(envelope, ensure_ascii=False, separators=(",", ":")),
            )
        ],
        structured_content=envelope,
        is_error=is_error,
    )


class ToolService:
    def __init__(
        self,
        settings: Settings,
        authorization: AuthorizationProvider,
        adapter: RestAdapter,
    ):
        self.settings, self.authorization, self.adapter = (
            settings,
            authorization,
            adapter,
        )
        self.limiter = anyio.CapacityLimiter(settings.max_concurrency)

    async def call(self, name: str, arguments: dict | None) -> CallToolResult:
        contract = CATALOG[name]  # The protocol layer rejects unknown tool names.
        correlation = uuid.uuid4().hex
        start, outcome = time.monotonic(), "INTERNAL_ERROR"
        try:
            context = self.authorization.require(contract.scope)
            try:
                encoded = json.dumps(
                    arguments, ensure_ascii=False, allow_nan=False
                ).encode("utf-8")
                if len(encoded) > 4096:
                    raise SafeError("INVALID_ARGUMENTS")
                query = contract.input_model.model_validate(
                    {} if arguments is None else arguments
                )
            except (ValidationError, ValueError, TypeError, RecursionError):
                raise SafeError("INVALID_ARGUMENTS") from None
            with anyio.fail_after(self.settings.timeout_seconds):
                async with self.limiter:
                    data = await self._read(name, context, query)
                    # Never release a result based only on admission-time authority.
                    self.authorization.ensure_current(context, contract.scope)
            model = contract.output_model(
                ok=True, correlation_id=correlation, data=data,
                source=getattr(self.adapter, "source", "mock"),
            )
            result = wire(model.model_dump(mode="json"), False)
            if (
                len(result.model_dump_json(by_alias=True).encode("utf-8"))
                > self.settings.max_output_bytes - 512
            ):
                raise SafeError("OUTPUT_LIMIT")
            outcome = "PASS"
            return result
        except SafeError as exc:
            outcome = exc.code
        except TimeoutError:
            outcome = "TIMEOUT"
        except (ValidationError, KeyError, TypeError, ValueError):
            outcome = "UPSTREAM_INVALID"
        except RuntimeError:
            outcome = "UPSTREAM_UNAVAILABLE"
        except Exception:  # noqa: BLE001 - Return only a fixed safe message at the tool boundary.
            outcome = "INTERNAL_ERROR"
        except BaseException:
            outcome = "CANCELLED"
            raise  # Preserve SDK/AnyIO cancellation, including cleanup and limiter release.
        finally:
            logger.info(
                {
                    "event": "tool_completed",
                    "tool": name,
                    "correlation_id": correlation,
                    "outcome": outcome,
                    "duration_ms": round((time.monotonic() - start) * 1000),
                    "mock": getattr(self.adapter, "source", "mock") == "mock",
                }
            )
        model = contract.output_model(
            ok=False,
            source=getattr(self.adapter, "source", "mock"),
            correlation_id=correlation,
            error=ErrorResult(
                code=outcome,
                message=MESSAGES[outcome],
                retryable=outcome in {"TIMEOUT", "UPSTREAM_UNAVAILABLE"},
            ),
        )
        return wire(model.model_dump(mode="json"), True)

    async def _read(self, name: str, context, query):
        if name in {"zeaplay_list_tasks", "zeaplay_list_overdue_tasks"}:
            raw = await self.adapter.list_tasks(
                context, query, overdue=name.endswith("overdue_tasks")
            )
            if (
                raw["page"] != query.page
                or raw["page_size"] != query.page_size
                or len(raw["items"]) > query.page_size
            ):
                raise SafeError("UPSTREAM_INVALID")
            if any(
                not self.authorization.can_read_task(context, t) for t in raw["items"]
            ):
                raise SafeError("AUTH_DENIED")
            projected = [card(t) for t in raw["items"]]
            return TaskPage(
                items=[c for c, _ in projected],
                page=raw["page"],
                page_size=raw["page_size"],
                total=raw["total"],
                total_pages=raw["total_pages"],
                has_more=raw["has_more"],
                truncated=any(cut for _, cut in projected),
            )
        if name == "zeaplay_get_task":
            raw = await self.adapter.information(context, query.task_id, "overview")
            task = dict(raw["overview"])
            task["title"] = task["name"]
            task["assigned_to_id"] = (
                task["assignees"][0]["id"] if task["assignees"] else None
            )
            if raw["task_id"] != query.task_id or task["id"] != query.task_id:
                raise SafeError("UPSTREAM_INVALID")
            if not self.authorization.can_read_task(context, task):
                raise SafeError("NOT_FOUND")
            base, cut = card(task)
            description, desc_cut = text(task["description"], 4000)
            team, team_cut = text(task["team"], 128)
            coverage, coverage_cut = text(raw["coverage"], 256)
            return TaskOverviewResult(
                task_id=query.task_id,
                as_of=timestamp(raw["as_of"]),
                overview=TaskOverview(
                    **base.model_dump(), description=description, team=team
                ),
                coverage=coverage,
                truncated=cut or desc_cut or team_cut or coverage_cut,
            )
        if name == "zeaplay_list_subtasks":
            raw = await self.adapter.information(
                context, query.task_id, "subtasks", query
            )
            if (
                raw["task_id"] != query.task_id
                or raw["page"] != query.page
                or raw["page_size"] != query.page_size
                or len(raw["items"]) > query.page_size
            ):
                raise SafeError("UPSTREAM_INVALID")
            items, cut = [], False
            for child in raw["items"]:
                title, truncated = text(child["name"], 256)
                cut |= truncated
                items.append(
                    Subtask(
                        id=child["id"],
                        title=title,
                        status=child["status"],
                        completed=child["completed"],
                        planned_start_date=date.fromisoformat(
                            child["planned_start_date"]
                        )
                        if child["planned_start_date"]
                        else None,
                        planned_end_date=date.fromisoformat(child["planned_end_date"])
                        if child["planned_end_date"]
                        else None,
                    )
                )
            coverage, coverage_cut = text(raw["coverage"], 256)
            return SubtaskPage(
                task_id=query.task_id,
                as_of=timestamp(raw["as_of"]),
                items=items,
                total=raw["total"],
                page=query.page,
                page_size=query.page_size,
                has_more=query.page * query.page_size < raw["total"],
                coverage=coverage,
                truncated=cut or coverage_cut,
            )
        if name == "zeaplay_get_workload_summary":
            raw = await self.adapter.workload(context)
            if raw["user_id"] != context.user_id:
                raise SafeError("AUTH_DENIED")
            workload = {k: raw["workload"][k] for k in Workload.model_fields}
            for key in ("period_start", "period_end"):
                workload[key] = timestamp(workload[key])
            note_cut = False
            if workload["capacity_note"] is not None:
                workload["capacity_note"], note_cut = text(
                    workload["capacity_note"], 256
                )
            coverage, coverage_cut = text(raw["coverage"], 256)
            return WorkloadResult(
                user_id=raw["user_id"],
                server_now=timestamp(raw["server_now"]),
                timezone=raw["timezone"],
                active_count=raw["active_count"],
                workload=Workload(**workload),
                coverage=coverage,
                truncated=note_cut or coverage_cut,
            )
        raise SafeError("INTERNAL_ERROR")
