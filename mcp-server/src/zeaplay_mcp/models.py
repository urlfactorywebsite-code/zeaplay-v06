"""Service-owned schemas. Literal enum values mirror inspected REST source."""

from datetime import date
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Id = Annotated[str, Field(min_length=1, max_length=36, pattern=r"^[A-Za-z0-9_-]+$")]
Page = Annotated[int, Field(ge=1, le=10000)]
PageSize = Annotated[int, Field(ge=1, le=100)]
Search = Annotated[str, Field(max_length=200)]
Status = Literal[
    "WAITING_FOR_REQUIREMENT",
    "TODO",
    "IN_PROGRESS",
    "BUG_FIXING",
    "IN_REVIEW",
    "BLOCKED",
    "ON_HOLD",
    "DONE",
    "DEPLOYED",
    "FAILED",
    "GRAVEYARD",
]
Priority = Literal["LOW", "MEDIUM", "HIGH", "URGENT"]
SubtaskStatus = Literal["TODO", "IN_PROGRESS", "PAUSED", "TESTING", "COMPLETED"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ListTasksInput(Model):
    page: Page = 1
    page_size: PageSize = 20
    search: Search | None = None
    status: Status | None = None
    priority: Priority | None = None


class GetTaskInput(Model):
    task_id: Id


class ListSubtasksInput(GetTaskInput):
    page: Page = 1
    page_size: PageSize = 25
    search: Search | None = None


class SelfInput(Model):
    """Workload is self-only; no user, tenant, actor or credential input."""


class TaskCard(Model):
    id: Id
    title: Annotated[str, Field(max_length=256)]
    status: Status
    priority: Priority
    assigned_to_id: Id | None
    due_at: AwareDatetime | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class TaskPage(Model):
    items: list[TaskCard] = Field(max_length=100)
    page: Page
    page_size: PageSize
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    has_more: bool
    truncated: bool


class TaskOverview(TaskCard):
    description: Annotated[str, Field(max_length=4000)]
    team: Annotated[str, Field(max_length=128)]


class TaskOverviewResult(Model):
    task_id: Id
    as_of: AwareDatetime
    overview: TaskOverview
    coverage: Annotated[str, Field(max_length=256)]
    truncated: bool


class Subtask(Model):
    id: Id
    title: Annotated[str, Field(max_length=256)]
    status: SubtaskStatus
    completed: bool
    planned_start_date: date | None
    planned_end_date: date | None


class SubtaskPage(Model):
    task_id: Id
    as_of: AwareDatetime
    items: list[Subtask] = Field(max_length=100)
    total: int = Field(ge=0)
    page: Page
    page_size: PageSize
    has_more: bool
    coverage: Annotated[str, Field(max_length=256)]
    truncated: bool


class Workload(Model):
    period_start: AwareDatetime
    period_end: AwareDatetime
    manual_seconds: float = Field(ge=0, allow_inf_nan=False)
    estimated_remaining_seconds: float = Field(ge=0, allow_inf_nan=False)
    unestimated_tasks: int = Field(ge=0)
    capacity_seconds: float | None = Field(ge=0, allow_inf_nan=False)
    remaining_capacity_seconds: float | None = Field(allow_inf_nan=False)
    capacity_note: Annotated[str, Field(max_length=256)] | None


class WorkloadResult(Model):
    user_id: Id
    server_now: AwareDatetime
    timezone: Annotated[
        str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_/+\-]+$")
    ]
    active_count: int = Field(ge=0)
    workload: Workload
    coverage: Annotated[str, Field(max_length=256)]
    truncated: bool


class ErrorResult(Model):
    code: str
    message: str
    retryable: bool


T = TypeVar("T")


class ToolResponse(Model, Generic[T]):
    ok: bool
    correlation_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    source: Literal["mock", "rest"] = "mock"
    untrusted_content: Literal[True] = True
    data: T | None = None
    error: ErrorResult | None = None
