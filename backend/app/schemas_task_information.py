"""Read-only, paginated contracts for the existing task information dialog."""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class InformationPerson(BaseModel):
    id: str
    name: str


class InformationOverview(BaseModel):
    id: str
    name: str
    description: str
    team: str
    project: str | None = None
    creator: InformationPerson | None
    assignees: list[InformationPerson]
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime
    assigned_at: datetime | None
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    actual_start_at: datetime | None = None
    actual_end_at: datetime | None = None
    estimated_hours: float | None
    productive_seconds: float
    elapsed_seconds: float
    due_at: datetime | None
    completed_at: datetime | None
    approval_status: str
    approval_required: bool
    limitations: list[str]


class InformationPoints(BaseModel):
    main_base_value: int
    main_earned: int | None = None
    subtask_base_capacity: int
    subtask_available_base: int
    subtask_earned: int
    components: dict[str, int]
    subtask_components: dict[str, int]
    main_recorded_components: dict[str, int]
    main_recorded_net: int
    verified_net_earned: int
    total_net_earned: int | None = None
    recipients: list[dict[str, Any]]
    coverage: str


class InformationEvent(BaseModel):
    kind: Literal["event"] = "event"
    id: str
    source: str
    event_type: str
    timestamp: datetime
    actor: InformationPerson | None
    subtask_id: str | None = None
    channel: str
    previous_status: str | None = None
    new_status: str | None = None
    duration_seconds: float | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class InformationSubtask(BaseModel):
    kind: Literal["subtask"] = "subtask"
    id: str
    name: str
    assignee: InformationPerson | None
    effective_priority: str
    priority_inherited: bool
    planned_start_date: date | None
    planned_end_date: date | None
    actual_start_at: datetime | None
    actual_end_at: datetime | None
    status: str
    completed: bool
    deleted_at: datetime | None
    created_at: datetime | None
    policy_version: str
    additional_base_value: int
    available_base: int
    earned: int | None
    components: dict[str, int]
    productive_seconds: float
    elapsed_seconds: float


class TaskInformationRead(BaseModel):
    viewer_id: str
    task_id: str
    section: Literal["overview", "timeline", "subtasks", "points", "activity"]
    as_of: datetime
    overview: InformationOverview | None = None
    points: InformationPoints | None = None
    items: list[InformationEvent | InformationSubtask] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25
    created_at: datetime | None = None
    coverage: str
