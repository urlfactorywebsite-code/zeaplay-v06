"""Independent, bounded REST DTOs. Extra backend fields are discarded."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import Id, Priority, Status, SubtaskStatus

Text = Annotated[str, Field(max_length=65536)]
Stamp = Annotated[str, Field(min_length=10, max_length=64)]
Count = Annotated[int, Field(ge=0, le=2**53 - 1)]


class Upstream(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class Card(Upstream):
    id: Id
    title: Text
    status: Status
    priority: Priority
    assigned_to_id: Id | None
    due_at: Stamp | None
    created_at: Stamp
    updated_at: Stamp


class Page(Upstream):
    items: list[Card] = Field(max_length=100)
    page: int = Field(ge=1, le=10000)
    page_size: int = Field(ge=1, le=100)
    total: Count
    total_pages: Count
    has_more: bool


class Person(Upstream):
    id: Id


class Overview(Upstream):
    id: Id
    name: Text
    description: Text
    team: Text
    status: Status
    priority: Priority
    assignees: list[Person] = Field(max_length=100)
    creator: Person | None
    due_at: Stamp | None
    created_at: Stamp
    updated_at: Stamp


class Child(Upstream):
    id: Id
    name: Text
    status: SubtaskStatus
    completed: bool
    planned_start_date: Annotated[str, Field(max_length=10)] | None
    planned_end_date: Annotated[str, Field(max_length=10)] | None


class Information(Upstream):
    viewer_id: Id
    task_id: Id
    section: Literal["overview", "subtasks"]
    as_of: Stamp
    coverage: Text
    overview: Overview | None = None
    items: list[Child] = Field(default_factory=list, max_length=100)
    total: Count = 0
    page: int = Field(ge=1, le=10000)
    page_size: int = Field(ge=1, le=100)


class Work(Upstream):
    period_start: Stamp
    period_end: Stamp
    manual_seconds: float = Field(ge=0, allow_inf_nan=False)
    estimated_remaining_seconds: float = Field(ge=0, allow_inf_nan=False)
    unestimated_tasks: Count
    capacity_seconds: float | None = Field(ge=0, allow_inf_nan=False)
    remaining_capacity_seconds: float | None = Field(allow_inf_nan=False)
    capacity_note: Text | None


class Activity(Upstream):
    user_id: Id
    server_now: Stamp
    timezone: Annotated[str, Field(min_length=1, max_length=64)]
    active_count: Count
    workload: Work


class Principal(Upstream):
    id: Id
    role: Literal["user", "manager", "admin", "owner"]
    status: Literal["ACTIVE", "INACTIVE"]
    department_id: Id | None = None
