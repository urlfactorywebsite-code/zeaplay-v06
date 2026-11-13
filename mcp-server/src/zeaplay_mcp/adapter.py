"""Read-only interface shaped around fixed REST contracts; no HTTP implementation."""

from copy import deepcopy
from typing import Literal, Protocol

import anyio

from .auth import AuthorizationContext, AuthorizationProvider
from .config import Scenario
from .errors import SafeError
from .fixtures import AS_OF, subtasks, tasks
from .models import ListSubtasksInput, ListTasksInput


class RestAdapter(Protocol):
    async def list_tasks(
        self, context: AuthorizationContext, query: ListTasksInput, *, overdue: bool
    ) -> dict: ...
    async def information(
        self,
        context: AuthorizationContext,
        task_id: str,
        section: Literal["overview", "subtasks"],
        query: ListSubtasksInput | None = None,
    ) -> dict: ...
    async def workload(self, context: AuthorizationContext) -> dict: ...


class MockRestAdapter:
    def __init__(
        self, authorization: AuthorizationProvider, scenario: Scenario = "normal"
    ):
        self.authorization = authorization
        self.scenario = scenario
        self._tasks = tasks()
        self.calls: list[tuple[str, str]] = []
        self.cancelled = False

    async def _simulate(self, operation: str) -> None:
        try:
            if self.scenario == "upstream_failure":
                raise RuntimeError(
                    "Raw upstream failure: password=fixture-secret Bearer fixture-secret"
                )
            if self.scenario in {"timeout", "slow"} and operation == "list":
                await anyio.sleep(30)
            await anyio.lowlevel.checkpoint()
        except BaseException:
            self.cancelled = True
            raise

    def _task(self, context: AuthorizationContext, task_id: str) -> dict:
        row = next((t for t in self._tasks if t["id"] == task_id), None)
        if row is None or not self.authorization.can_read_task(context, row):
            raise SafeError("NOT_FOUND")
        return row

    async def list_tasks(
        self, context: AuthorizationContext, query: ListTasksInput, *, overdue: bool
    ) -> dict:
        self.calls.append(("GET", "/tasks/page"))
        await self._simulate("list")
        rows = [t for t in self._tasks if self.authorization.can_read_task(context, t)]
        if query.search is not None:
            rows = [
                t
                for t in rows
                if query.search.casefold()
                in (t["title"] + " " + t["description"]).casefold()
            ]
        if query.status is not None:
            rows = [t for t in rows if t["status"] == query.status]
        if query.priority is not None:
            rows = [t for t in rows if t["priority"] == query.priority]
        if overdue:
            rows = [
                t
                for t in rows
                if t["due_at"]
                and t["due_at"] < AS_OF
                # Match the inspected REST quick_filter: only DONE/DEPLOYED
                # are in services.gamification.COMPLETED_STATUSES.
                and t["status"] not in {"DONE", "DEPLOYED"}
            ]
        rows.sort(key=lambda t: t["id"])
        start = (query.page - 1) * query.page_size
        return deepcopy(
            {
                "items": rows[start : start + query.page_size],
                "page": query.page,
                "page_size": query.page_size,
                "total": len(rows),
                "total_pages": (len(rows) + query.page_size - 1) // query.page_size,
                "has_more": start + query.page_size < len(rows),
            }
        )

    async def information(
        self,
        context: AuthorizationContext,
        task_id: str,
        section: Literal["overview", "subtasks"],
        query: ListSubtasksInput | None = None,
    ) -> dict:
        self.calls.append(("GET", "/tasks/{id}/information"))
        await self._simulate("information")
        task = self._task(context, task_id)
        common = {
            "task_id": task_id,
            "viewer_id": context.user_id,
            "section": section,
            "as_of": AS_OF,
            "coverage": "Synthetic fixture only; no live authorization proof",
        }
        if section == "overview":
            # Actual information REST uses overview.name and assignees, unlike
            # /tasks/page's title/assigned_to_id. Extra private fields stress the
            # explicit projection; they are synthetic, never production data.
            return deepcopy(
                {
                    **common,
                    "overview": {
                        **task,
                        "name": task["title"],
                        "assignees": [
                            {"id": task["assigned_to_id"], "name": "Synthetic assignee"}
                        ]
                        if task["assigned_to_id"]
                        else [],
                        "creator": {
                            "id": task["created_by_id"],
                            "name": "Synthetic creator",
                        },
                    },
                }
            )
        if section != "subtasks" or query is None:
            raise SafeError("UPSTREAM_INVALID")
        rows = list(subtasks(task_id))
        if query.search is not None:
            rows = [t for t in rows if query.search.casefold() in t["name"].casefold()]
        start = (query.page - 1) * query.page_size
        return {
            **common,
            "items": rows[start : start + query.page_size],
            "total": len(rows),
            "page": query.page,
            "page_size": query.page_size,
        }

    async def workload(self, context: AuthorizationContext) -> dict:
        self.calls.append(("GET", "/tasks/activity"))
        await self._simulate("workload")
        return {
            "user_id": context.user_id,
            "server_now": AS_OF,
            "timezone": "UTC",
            "active_count": 1,
            "workload": {
                "period_start": AS_OF,
                "period_end": "2026-11-13T00:00:00Z",
                "manual_seconds": 1800.0,
                "estimated_remaining_seconds": 3600.0,
                "unestimated_tasks": 1,
                "capacity_seconds": None,
                "remaining_capacity_seconds": None,
                "capacity_note": "Synthetic; capacity is not configured",
            },
            "coverage": "Fixed synthetic workload; not computed from production business data",
            "contexts": [{"private": "MUST_NOT_PROJECT"}],
            "user_name": "MUST_NOT_PROJECT",
        }
