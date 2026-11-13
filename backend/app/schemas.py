"""Pydantic schemas for request and response bodies."""

import json
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    PrivateAttr,
    field_validator,
    model_serializer,
    model_validator,
)

from .models import (
    ApprovalScopeTypeEnum,
    ApprovalStatusEnum,
    AuditLogCategoryEnum,
    AuditLogSeverityEnum,
    AuditLogSourceEnum,
    AuditLogStatusEnum,
    AvatarStorageTypeEnum,
    BadgeProgressStatusEnum,
    BadgeStateEnum,
    ChatConversationTypeEnum,
    ChatMemberRoleEnum,
    ChatMessageTypeEnum,
    MediaCategoryEnum,
    NotificationEntityTypeEnum,
    NotificationTypeEnum,
    RecurrenceRuleEnum,
    RewardClaimStatusEnum,
    RewardImageSourceEnum,
    RewardLogActionEnum,
    RewardStatusEnum,
    RoleEnum,
    StorageProviderEnum,
    TaskApprovalStatusEnum,
    TaskPriorityEnum,
    TaskStatusEnum,
    TaskTransferStatusEnum,
    ToolCategoryStatusEnum,
    ToolPricingTypeEnum,
    ToolStatusEnum,
    UserStatusEnum,
)
from .profile_validation import ProfileFields, validate_profile_write

# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

class LevelBase(BaseModel):
    name: str
    bg_image: Optional[str] = None
    is_active: bool = True
    season_id: Optional[str] = None

class LevelCreate(LevelBase):
    pass

class LevelUpdate(BaseModel):
    name: Optional[str] = None
    bg_image: Optional[str] = None
    is_active: Optional[bool] = None
    season_id: Optional[str] = None

class LevelRead(LevelBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    season_id: Optional[str] = None
    created_by_id: str
    created_at: datetime
    season: Optional["SeasonRead"] = None

class LevelNodeBase(BaseModel):
    type: str  # CHECKPOINT, TOWER, DECOR, GIFT
    x: int
    y: int
    width: int
    height: int
    title: str
    description: Optional[str] = None
    xp_threshold: int = 0
    reward_id: Optional[str] = None
    require_confirm: bool = True
    animation_key: Optional[str] = None

class LevelNodeCreate(LevelNodeBase):
    pass

class LevelNodeUpdate(BaseModel):
    type: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    xp_threshold: Optional[int] = None
    reward_id: Optional[str] = None
    require_confirm: Optional[bool] = None
    animation_key: Optional[str] = None

class LevelNodeRead(LevelNodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    level_id: str
    created_at: datetime
    updated_at: datetime

class LevelEdgeBase(BaseModel):
    from_node: str
    to_node: str
    path: Optional[dict] = None

class LevelEdgeCreate(LevelEdgeBase):
    pass

class LevelEdgeUpdate(BaseModel):
    from_node: Optional[str] = None
    to_node: Optional[str] = None
    path: Optional[dict] = None

class LevelEdgeRead(LevelEdgeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    level_id: str
    created_at: datetime
    updated_at: datetime

class LevelEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    level_id: str
    node_id: Optional[str] = None
    event_type: str  # REACHED, CLAIMED, ANIM_SHOWN
    user_id: str
    created_at: datetime

class LevelPreviewResponse(BaseModel):
    level: LevelRead
    nodes: List[LevelNodeRead]
    edges: List[LevelEdgeRead]
    user_xp: int
    reachable_nodes: List[str]  # node ids


# ---------------------------------------------------------------------------
# Auth & Tokens
# ---------------------------------------------------------------------------


class Token(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str
    token_type: str
    exp: int
    scopes: List[str] = Field(default_factory=list)


class TokenMintRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=255)
    scopes: List[str] = Field(default_factory=list)
    expires_in_minutes: Optional[int] = Field(default=None, ge=5, le=60 * 24 * 365 * 10)


class TokenMintResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    scopes: List[str] = Field(default_factory=list)
    issued_at: datetime
    expires_at: datetime
    subject: str
    label: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------


class DepartmentBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)


class DepartmentRead(DepartmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str


# ---------------------------------------------------------------------------
# Avatars
# ---------------------------------------------------------------------------


class AvatarAssetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    storage_type: AvatarStorageTypeEnum = AvatarStorageTypeEnum.FILE
    data_url: Optional[str] = None
    external_url: Optional[str] = Field(default=None, max_length=500)

    @field_validator("external_url")
    @classmethod
    def validate_external_url(cls, value):
        from .avatar_utils import safe_external_avatar_url
        if value is not None and not safe_external_avatar_url(value):
            raise ValueError("Avatar URLs must use HTTP or HTTPS without credentials")
        return value


class AvatarAssetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    data_url: Optional[str] = None
    external_url: Optional[str] = Field(default=None, max_length=500)

    validate_external_url = field_validator("external_url")(AvatarAssetCreate.validate_external_url.__func__)


class AvatarAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def resolve_safe_asset(cls, value):
        from .avatar_utils import avatar_public_url, safe_external_avatar_url
        from .models import AvatarAsset
        if isinstance(value, AvatarAsset):
            result = {field: getattr(value, field, None) for field in cls.model_fields}
            result.update(url=avatar_public_url(value), data_url=None,
                external_url=safe_external_avatar_url(value.external_url))
            return result
        return value

    id: str
    name: str
    storage_type: AvatarStorageTypeEnum
    url: Optional[str] = None
    data_url: Optional[str] = None
    external_url: Optional[str] = None
    is_default: bool
    mime_type: Optional[str] = None
    created_by_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AvatarUploadPayload(BaseModel):
    data_url: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserBase(ProfileFields):
    name: str
    email: EmailStr
    employer_id: Optional[str] = None
    role: RoleEnum = RoleEnum.USER
    status: UserStatusEnum = UserStatusEnum.ACTIVE
    department_id: Optional[str] = None
    avatar_asset_id: Optional[str] = None
    avatar_frame: Optional[str] = None
    manager_id: Optional[str] = None
    manager_email: Optional[str] = None
    shift_name: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    morning_break_start: Optional[str] = None
    morning_break_end: Optional[str] = None
    lunch_break_start: Optional[str] = None
    lunch_break_end: Optional[str] = None
    evening_break_start: Optional[str] = None
    evening_break_end: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = None
    notes: Optional[str] = None
    projects: Optional[List[str]] = None


class UserCreate(UserBase):
    validate_profile = model_validator(mode="after")(validate_profile_write)
    password: str = Field(min_length=6)


class UserUpdate(ProfileFields):
    model_config = ConfigDict(extra="forbid")
    validate_profile = model_validator(mode="after")(validate_profile_write)
    expected_updated_at: Optional[datetime] = None
    name: Optional[str] = None
    employer_id: Optional[str] = None
    role: Optional[RoleEnum] = None
    status: Optional[UserStatusEnum] = None
    department_id: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=6)
    points: Optional[int] = None
    tasks_created: Optional[int] = None
    tasks_completed: Optional[int] = None
    clarity_scores: Optional[List[int]] = None
    claimed_reward_ids: Optional[List[str]] = None
    unlocked_achievement_ids: Optional[List[str]] = None
    avatar_asset_id: Optional[str] = None
    avatar_frame: Optional[str] = None
    manager_id: Optional[str] = None
    manager_email: Optional[str] = None
    shift_name: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    morning_break_start: Optional[str] = None
    morning_break_end: Optional[str] = None
    lunch_break_start: Optional[str] = None
    lunch_break_end: Optional[str] = None
    evening_break_start: Optional[str] = None
    evening_break_end: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = None
    notes: Optional[str] = None
    projects: Optional[List[str]] = None


class UserPasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


class UserProfileUpdate(ProfileFields):
    validate_profile = model_validator(mode="after")(validate_profile_write)
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: Optional[datetime] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    location: Optional[str] = Field(default=None, max_length=255)
    timezone: Optional[str] = Field(default=None, max_length=64)
    name: Optional[str] = None
    employer_id: Optional[str] = None
    department_id: Optional[str] = None
    avatar_asset_id: Optional[str] = None
    avatar_frame: Optional[str] = None
    manager_email: Optional[str] = None
    shift_name: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    morning_break_start: Optional[str] = None
    morning_break_end: Optional[str] = None
    lunch_break_start: Optional[str] = None
    lunch_break_end: Optional[str] = None
    evening_break_start: Optional[str] = None
    evening_break_end: Optional[str] = None


class UserResetPassword(BaseModel):
    new_password: str = Field(min_length=6)


class UserRead(UserBase):
    _include_private_fields: bool = PrivateAttr(default=False)
    _include_internal_notes: bool = PrivateAttr(default=False)

    @model_serializer(mode="wrap")
    def serialize_profile(self, handler):
        result = handler(self)
        from .avatar_utils import safe_external_avatar_url
        if self.profile_image_key:
            result["profile_image_url"] = f"/users/{self.id}/avatar-image?v={self.updated_at.isoformat()}"
        elif self.profile_image_url and not self.profile_image_url.startswith(("/avatars/", "/users/")):
            result["profile_image_url"] = safe_external_avatar_url(self.profile_image_url)
        result.pop("profile_image_key", None)
        if not self._include_private_fields:
            for field in ("phone", "location", "timezone", "notes", "manager_email",
                "shift_name", "shift_start", "shift_end", "morning_break_start", "morning_break_end",
                "lunch_break_start", "lunch_break_end", "evening_break_start", "evening_break_end"):
                result.pop(field, None)
        if not self._include_internal_notes:
            result.pop("notes", None)
        return result

    skills: Optional[List[str]] = None

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, value):
        # Historical profile values remain readable; write schemas validate changes.
        return value

    model_config = ConfigDict(from_attributes=True)

    id: str
    employer_id: Optional[str] = None
    points: int
    overall_xp_points: int = 0
    claimed_xp_points: int = 0
    tasks_created: int
    tasks_completed: int
    clarity_scores: List[int]
    claimed_reward_ids: List[str]
    unlocked_achievement_ids: List[str]
    avatar_asset: Optional[AvatarAssetRead] = None
    avatar_url: Optional[str] = None
    profile_image_key: Optional[str] = None
    profile_image_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    department: Optional[DepartmentRead] = None


# ---------------------------------------------------------------------------
# Subtasks
# ---------------------------------------------------------------------------


class SubtaskBase(BaseModel):
    title: str
    completed: bool = False


class SubtaskStatusEnum(str, Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    TESTING = "TESTING"
    COMPLETED = "COMPLETED"


class SubtaskRead(SubtaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    planned_start_date: Optional[date] = None
    planned_end_date: Optional[date] = None
    actual_start_at: Optional[datetime] = None
    actual_end_at: Optional[datetime] = None
    priority_override: Optional[TaskPriorityEnum] = None
    point_policy_version: str = "legacy"
    version: int = 1
    created_at: Optional[datetime] = None
    status: SubtaskStatusEnum = SubtaskStatusEnum.TODO
    managed: bool = False
    effective_priority: Optional[TaskPriorityEnum] = None
    deleted_at: Optional[datetime] = None
    reward_timezone: Optional[str] = None


class _SubtaskDates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planned_start_date: Optional[date] = None
    planned_end_date: Optional[date] = None
    actual_start_at: Optional[datetime] = None
    actual_end_at: Optional[datetime] = None
    priority_override: Optional[TaskPriorityEnum] = None

    @field_validator("actual_start_at", "actual_end_at")
    @classmethod
    def utc_timestamp(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("An explicit timezone is required")
            return value.astimezone(timezone.utc)
        return value

    @model_validator(mode="after")
    def ordered_ranges(self):
        if self.planned_start_date and self.planned_end_date and self.planned_end_date < self.planned_start_date:
            raise ValueError("Planned end precedes start")
        if self.actual_start_at and self.actual_end_at and self.actual_end_at < self.actual_start_at:
            raise ValueError("Actual end precedes start")
        return self


class SubtaskScheduleUpdate(_SubtaskDates):
    expected_version: int = Field(ge=1, strict=True)


class SubtaskCreate(_SubtaskDates):
    title: str = Field(min_length=1, max_length=255)
    completed: Literal[False] = False
    planned_start_date: date
    planned_end_date: date

    @model_validator(mode="after")
    def new_checklist(self):
        if not self.title.strip():
            raise ValueError("A subtask title is required")
        if self.actual_start_at is not None or self.actual_end_at is not None:
            raise ValueError("Record and confirm actual times after creating the subtask")
        return self


class SubtaskUpdate(_SubtaskDates):
    deleted: Optional[bool] = None
    expected_version: Optional[int] = Field(default=None, ge=1, strict=True)
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    completed: Optional[bool] = None
    status: Optional[SubtaskStatusEnum] = None
    action: Optional[Literal["START", "PAUSE", "RESUME", "SEND_TO_TESTING", "COMPLETE", "REOPEN"]] = None
    confirm_actual_times: bool = False
    manage: bool = False

    @model_validator(mode="after")
    def explicit_edit(self):
        for name in ("title", "completed", "status", "action", "deleted"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        if self.title is not None and not self.title.strip():
            raise ValueError("A subtask title is required")
        if sum(name in self.model_fields_set for name in ("status", "action", "completed")) > 1:
            raise ValueError("Choose one status, action or legacy completion flag")
        if {"actual_start_at", "actual_end_at"} & self.model_fields_set and not self.confirm_actual_times:
            raise ValueError("Explicitly confirm manually entered actual times")
        return self


class SubtaskInput(SubtaskUpdate):
    id: Optional[str] = None
    title: str = Field(min_length=1, max_length=255)


class SubtaskRewardPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    expected_version: int = Field(ge=0, strict=True)
    bonus_enabled: Optional[bool] = None
    penalty_enabled: Optional[bool] = None
    refresh_rules: bool = False


class TaskActivityInput(BaseModel):
    """Internal validated snapshots; actor and tenant always come from the server."""
    model_config = ConfigDict(extra="forbid")
    event_type: str = Field(min_length=1, max_length=255)
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = Field(default=None, min_length=1, max_length=128)

    @field_validator("before", "after", "metadata")
    @classmethod
    def json_snapshot(cls, value):
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Snapshots must contain finite JSON values") from exc
        return value

    @field_validator("event_type", "correlation_id")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("A nonblank value is required")
        return value


class PointAdjustmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(min_length=1, max_length=36)
    component_type: Literal["BASE", "BONUS", "PENALTY", "ADJUSTMENT", "REVERSAL"]
    points: int = Field(strict=True, ge=-2147483648, le=2147483647)
    policy_version: str = Field(min_length=1, max_length=80)
    idempotency_key: str = Field(min_length=1, max_length=128)
    activity_event_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=1, max_length=2000)
    reversal_of_id: Optional[UUID] = None
    calculation_inputs: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def component_invariants(self):
        if self.component_type == "BONUS" and self.points < 0 or self.component_type == "PENALTY" and self.points > 0:
            raise ValueError("Bonus/penalty sign does not match its component")
        if (self.component_type == "REVERSAL") != (self.reversal_of_id is not None):
            raise ValueError("Only reversals require a reversal reference")
        if any(not value.strip() for value in (self.user_id, self.policy_version, self.idempotency_key, self.activity_event_id, self.reason)):
            raise ValueError("Nonblank ledger values are required")
        return self


class ManualWorkIntervalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    started_at: datetime
    ended_at: datetime
    note: Optional[str] = Field(default=None, max_length=10000)
    request_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def interval_invariants(self):
        if any(value.tzinfo is None or value.utcoffset() is None for value in (self.started_at, self.ended_at)):
            raise ValueError("Work timestamps require an explicit timezone")
        self.started_at = self.started_at.astimezone(timezone.utc)
        self.ended_at = self.ended_at.astimezone(timezone.utc)
        if self.ended_at <= self.started_at or not self.request_id.strip():
            raise ValueError("A positive work interval and nonblank request ID are required")
        return self


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


class ActivityCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["START", "PAUSE", "RESUME", "STOP"]
    subtask_id: Optional[str] = Field(default=None, min_length=1, max_length=36)
    expected_version: int = Field(ge=0, strict=True)
    request_id: UUID


class ConfirmedWorkInput(ManualWorkIntervalInput):
    confirmed: Literal[True]
    subtask_id: Optional[str] = Field(default=None, min_length=1, max_length=36)
    supersedes_id: Optional[str] = Field(default=None, min_length=1, max_length=36)

    @field_validator("confirmed", mode="before")
    @classmethod
    def require_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation of manual work times is required")
        return value


class TaskBase(BaseModel):
    title: str
    description: str = ""
    status: TaskStatusEnum = TaskStatusEnum.TODO
    priority: TaskPriorityEnum = TaskPriorityEnum.MEDIUM
    team: str = "General"
    assigned_to_id: Optional[str] = None
    task_group_id: Optional[str] = None
    due_at: Optional[datetime] = None
    recurrence_rule: RecurrenceRuleEnum = RecurrenceRuleEnum.NONE
    recurring_task_id: Optional[str] = None
    clarity_rating: Optional[int] = None
    attachments: List[str] = Field(default_factory=list)
    estimated_hours: Optional[float] = None
    tags: List[str] = Field(default_factory=list)


class TaskCreate(TaskBase):
    assigned_to_ids: List[str] = Field(default_factory=list)
    follower_ids: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    subtasks: List[SubtaskCreate] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatusEnum] = None
    priority: Optional[TaskPriorityEnum] = None
    team: Optional[str] = None
    assigned_to_id: Optional[str] = None
    approval_required: Optional[bool] = None
    approver_id: Optional[str] = None
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    recurrence_rule: Optional[RecurrenceRuleEnum] = None
    recurring_task_id: Optional[str] = None
    clarity_rating: Optional[int] = None
    attachments: Optional[List[str]] = None
    estimated_hours: Optional[float] = None
    tags: Optional[List[str]] = None
    follower_ids: Optional[List[str]] = None
    dependencies: Optional[List[str]] = None
    subtasks: Optional[List[SubtaskInput]] = None


class TaskTransferRequest(BaseModel):
    from_user_id: str
    to_user_id: str
    statuses: List[TaskStatusEnum] = Field(min_length=1)


class TaskTransferResponse(BaseModel):
    from_user_id: str
    to_user_id: str
    statuses: List[TaskStatusEnum]
    updated_count: int


class TaskTransferWorkflowRequest(BaseModel):
    to_user_id: str
    note: Optional[str] = None


class TaskTransferWorkflowDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: Optional[str] = None


class TaskTransferWorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    from_user_id: Optional[str] = None
    to_user_id: str
    requested_by_id: str
    approved_by_id: Optional[str] = None
    status: TaskTransferStatusEnum
    note: Optional[str] = None
    created_at: datetime
    acted_at: Optional[datetime] = None


class TaskApprovalAction(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: Optional[str] = None


class TaskSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str


class SubtaskActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subtask_id: Optional[str] = None
    actor_id: str
    event_type: str
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    created_at: datetime


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("ticket_id", mode="before")
    @classmethod
    def serialize_ticket_id(cls, value):
        # The ORM uses UUID; keep the existing JSON string/null contract.
        return str(value) if isinstance(value, UUID) else value

    id: str
    status: TaskStatusEnum
    created_by_id: str
    created_at: datetime
    updated_at: datetime
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    ticket_id: Optional[str] = None
    approval_required: bool = False
    approval_status: TaskApprovalStatusEnum = TaskApprovalStatusEnum.NONE
    approver_id: Optional[str] = None
    assignee: Optional['UserRead'] = None
    creator: Optional['UserRead'] = None
    subtasks: List[SubtaskRead]
    subtask_activity: List[SubtaskActivityRead] = Field(default_factory=list)
    subtask_rewards: Optional[Dict[str, Any]] = None

    dependencies: List[TaskSummary]
    follower_ids: List[str] = Field(default_factory=list)
    status_title: Optional[str] = None


class TaskListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str = ""
    status: TaskStatusEnum
    priority: TaskPriorityEnum
    team: str
    assigned_to_id: Optional[str] = None
    task_group_id: Optional[str] = None
    created_by_id: str
    created_at: datetime
    updated_at: datetime
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    recurrence_rule: RecurrenceRuleEnum = RecurrenceRuleEnum.NONE
    recurring_task_id: Optional[str] = None
    clarity_rating: Optional[int] = None
    attachments: List[str] = Field(default_factory=list)
    estimated_hours: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    follower_ids: List[str] = Field(default_factory=list)
    subtasks: List[SubtaskRead] = Field(default_factory=list)


class TaskListResponse(BaseModel):
    items: List[TaskListItem]
    page: int
    page_size: int
    total: int
    total_pages: int
    status_counts: Dict[str, int] = Field(default_factory=dict)
    next_cursor: Optional[str] = None
    has_more: bool = False


class TaskSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: TaskStatusEnum
    priority: TaskPriorityEnum
    team: str
    assigned_to_id: Optional[str] = None
    created_by_id: str
    created_at: datetime
    updated_at: datetime
    due_at: Optional[datetime] = None


class TaskKanbanColumn(BaseModel):
    status: str
    title: str
    order: int
    count: int
    items: List[TaskListItem]


class TaskKanbanResponse(BaseModel):
    columns: List[TaskKanbanColumn]


class TaskCalendarDaySummary(BaseModel):
    date: date
    total: int = 0
    completed: int = 0
    overdue: int = 0
    urgent: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    due_soon: int = 0


class TaskCalendarSummaryResponse(BaseModel):
    start_date: date
    end_date: date
    days: List[TaskCalendarDaySummary]


# Minimal task payload for leaderboard point calculation.
class TaskLeaderboardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: TaskStatusEnum
    status_title: Optional[str] = None
    priority: TaskPriorityEnum
    team: str
    assigned_to_id: Optional[str] = None
    created_by_id: str
    created_at: datetime
    updated_at: datetime
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    clarity_rating: Optional[int] = None


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


class CommentBase(BaseModel):
    content: str


class CommentCreate(CommentBase):
    task_id: str
    user_id: str


class CommentRead(CommentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    user_id: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Kanban Columns
# ---------------------------------------------------------------------------


class KanbanColumnBase(BaseModel):
    title: str
    order: int


class KanbanColumnCreate(KanbanColumnBase):
    pass


class KanbanColumnUpdate(BaseModel):
    title: Optional[str] = None
    order: Optional[int] = None


class KanbanColumnRead(KanbanColumnBase):
    model_config = ConfigDict(from_attributes=True)

    id: str


# ---------------------------------------------------------------------------
# Achievements & Rewards
# ---------------------------------------------------------------------------


class BadgeRuleConditions(BaseModel):
    model_config = ConfigDict(extra="allow")

    priority: Optional[List[str]] = None
    assigned_to: Optional[Literal["self", "team", "any"]] = None
    created_by: Optional[Literal["self", "team", "any"]] = None
    project_id: Optional[str] = None
    pipeline_id: Optional[str] = None


class BadgeRuleCount(BaseModel):
    type: Literal[">=", "==", "<="]
    value: int = Field(ge=0)


class BadgeRuleTimeWindow(BaseModel):
    value: int = Field(ge=1)
    unit: Literal["minutes", "hours", "days", "weeks", "months"]


class BadgeRule(BaseModel):
    entity: Literal["task", "ticket", "subtask", "comment", "project", "time", "manual"]
    event: Literal[
        "created",
        "completed",
        "updated",
        "reopened",
        "deleted",
        "assigned",
        "priority_changed",
        "status_changed",
        "overdue",
    ]
    conditions: BadgeRuleConditions = Field(default_factory=BadgeRuleConditions)
    count: BadgeRuleCount
    time_window: Optional[BadgeRuleTimeWindow] = None
    negative: bool = False


class BadgeRuleSet(BaseModel):
    operator: Literal["AND", "OR"] = "AND"
    rules: List[BadgeRule] = Field(default_factory=list)


class BadgeBase(BaseModel):
    name: str
    description: str
    tier: str
    tier_group: Optional[str] = None
    tier_order: int = Field(default=1, ge=1)
    bonus_xp: int = Field(default=0, ge=0)
    image_url: Optional[str] = None
    image_asset_path: Optional[str] = None
    state: BadgeStateEnum = BadgeStateEnum.DRAFT
    is_system: bool = False


class BadgeCreate(BadgeBase):
    rules: BadgeRuleSet


class BadgeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tier: Optional[str] = None
    tier_group: Optional[str] = None
    tier_order: Optional[int] = Field(default=None, ge=1)
    bonus_xp: Optional[int] = Field(default=None, ge=0)
    image_url: Optional[str] = None
    image_asset_path: Optional[str] = None
    state: Optional[BadgeStateEnum] = None
    is_system: Optional[bool] = None
    rules: Optional[BadgeRuleSet] = None


class BadgeRead(BadgeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
    rules: Optional[BadgeRuleSet] = None


class BadgeAchievementRead(BaseModel):
    id: str
    name: str
    description: str
    tier: str
    tier_group: Optional[str] = None
    tier_order: int
    bonus_xp: int
    image_url: Optional[str] = None
    state: BadgeStateEnum
    is_system: bool
    status: BadgeProgressStatusEnum
    progress_percent: int
    earned_at: Optional[datetime] = None


class AchievementBase(BaseModel):
    id: str
    title: str
    description: str
    points: int
    icon: str


class AchievementCreate(AchievementBase):
    pass


class AchievementUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    points: Optional[int] = None
    icon: Optional[str] = None


class AchievementRead(AchievementBase):
    model_config = ConfigDict(from_attributes=True)


class RewardIconRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    url: str
    label: str


class RewardBase(BaseModel):
    title: str
    description: str
    image_source: RewardImageSourceEnum = RewardImageSourceEnum.LIBRARY
    image_ref: Optional[str] = None
    xp_required: int = Field(default=0, ge=0)
    dept_whitelist: Optional[List[str]] = Field(default=None)
    auto_redeem: bool = True
    allow_multiple_claims: bool = False
    expires_at: Optional[datetime] = None

    @field_validator("dept_whitelist", mode="before")
    @classmethod
    def normalize_depts(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if not value:
            return None
        cleaned = [dept_id for dept_id in value if dept_id]
        return cleaned or None


class RewardCreate(RewardBase):
    pass


class RewardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    image_source: Optional[RewardImageSourceEnum] = None
    image_ref: Optional[str] = None
    xp_required: Optional[int] = Field(default=None, ge=0)
    dept_whitelist: Optional[List[str]] = None
    auto_redeem: Optional[bool] = None
    allow_multiple_claims: Optional[bool] = None
    expires_at: Optional[datetime] = None


class RewardRead(RewardBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: RewardStatusEnum
    created_at: datetime
    updated_at: datetime
    created_by_id: Optional[str] = None
    updated_by_id: Optional[str] = None
    image_url: Optional[str] = None


class RewardListResponse(BaseModel):
    items: List[RewardRead]
    page: int
    total: int
    page_size: int
    total_pages: int


class RewardImageUploadResponse(BaseModel):
    image_ref: str
    image_url: str
    mime_type: str
    size: int


class RewardClaimUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: EmailStr
    role: RoleEnum
    department_id: Optional[str] = None


class RewardClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reward_id: str
    user_id: str
    status: RewardClaimStatusEnum
    xp_spent: int = 0
    claimed_at: datetime
    resolved_at: Optional[datetime] = None
    approver_id: Optional[str] = None
    reward: RewardRead
    user: RewardClaimUser


class RewardClaimListResponse(BaseModel):
    items: List[RewardClaimRead]
    page: int
    total: int
    page_size: int
    total_pages: int


class RewardLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_id: Optional[str] = None
    subject_type: str
    subject_id: str
    action: RewardLogActionEnum
    meta: Optional[Dict[str, Any]] = None
    created_at: datetime


class RewardLogListResponse(BaseModel):
    items: List[RewardLogRead]
    page: int
    total: int
    page_size: int
    total_pages: int


# ---------------------------------------------------------------------------
# Audit Events

class AuditActorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[RoleEnum] = None


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_id: Optional[str] = None
    actor: Optional[AuditActorRead] = None
    event_type: str
    entity_type: str
    entity_id: str
    payload: Optional[Dict[str, Any]] = None
    created_at: datetime


class AuditEventListResponse(BaseModel):
    items: List[AuditEventRead]
    page: int
    total: int
    page_size: int
    total_pages: int


# ---------------------------------------------------------------------------
# Audit Logs (Advanced)

class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    actor_id: Optional[str] = None
    actor_role: Optional[str] = None
    actor: Optional[AuditActorRead] = None
    action: str
    category: AuditLogCategoryEnum
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    target_user_id: Optional[str] = None
    approval_id: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    source: AuditLogSourceEnum
    severity: AuditLogSeverityEnum
    status: AuditLogStatusEnum
    reason: Optional[str] = None
    trigger: Optional[str] = None
    route: Optional[str] = None
    method: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default=None, alias="metadata_payload")
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: List[AuditLogRead]
    page: int
    total: int
    page_size: int
    total_pages: int


class AuditRetentionConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    retention_days: int
    created_at: datetime
    updated_at: datetime
    last_applied_at: Optional[datetime] = None


class AuditRetentionConfigUpdate(BaseModel):
    retention_days: int = Field(ge=30, le=365)


class AuditRetentionApplyResponse(BaseModel):
    updated: int
    cutoff_at: datetime
    retention_days: int


# ---------------------------------------------------------------------------
# Tool Library

class ToolCategoryBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    display_order: int = 0
    status: ToolCategoryStatusEnum = ToolCategoryStatusEnum.ACTIVE


class ToolCategoryCreate(ToolCategoryBase):
    pass


class ToolCategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    display_order: Optional[int] = None
    status: Optional[ToolCategoryStatusEnum] = None


class ToolCategoryRead(ToolCategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class ToolCategoryListResponse(BaseModel):
    items: List[ToolCategoryRead]
    page: int
    total: int
    page_size: int
    total_pages: int


class ToolBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    website_url: Optional[str] = None
    preview_image_url: Optional[str] = None
    category_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    pricing_type: ToolPricingTypeEnum = ToolPricingTypeEnum.FREE
    is_internal: bool = False


class ToolCreate(ToolBase):
    pass


class ToolUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, min_length=1)
    website_url: Optional[str] = None
    preview_image_url: Optional[str] = None
    category_id: Optional[str] = None
    tags: Optional[List[str]] = None
    pricing_type: Optional[ToolPricingTypeEnum] = None
    is_internal: Optional[bool] = None
    status: Optional[ToolStatusEnum] = None


class ToolRead(ToolBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: ToolStatusEnum
    created_by: str
    approved_by: Optional[str] = None
    review_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    category: Optional[ToolCategoryRead] = None
    is_favorite: bool = False


class ToolListResponse(BaseModel):
    items: List[ToolRead]
    page: int
    total: int
    page_size: int
    total_pages: int


class ToolDecision(BaseModel):
    reason: Optional[str] = None


class ToolFavoriteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tool: ToolRead
    created_at: datetime


class ToolFavoriteListResponse(BaseModel):
    items: List[ToolRead]


# ---------------------------------------------------------------------------
# Notifications

class DataExportScope(str, Enum):
    USERS = "users"
    TASKS = "tasks"
    DEPARTMENTS = "departments"
    ALL = "all"


class UserBackup(BaseModel):
    profile_bio: Optional[str] = Field(default=None, max_length=500)
    id: str
    name: str
    email: EmailStr
    employer_id: Optional[str] = None
    role: RoleEnum
    status: UserStatusEnum
    department_id: Optional[str]
    manager_id: Optional[str] = None
    manager_email: Optional[str] = None
    shift_name: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    morning_break_start: Optional[str] = None
    morning_break_end: Optional[str] = None
    lunch_break_start: Optional[str] = None
    lunch_break_end: Optional[str] = None
    evening_break_start: Optional[str] = None
    evening_break_end: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = None
    notes: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    projects: List[str] = Field(default_factory=list)
    points: int
    tasks_created: int
    tasks_completed: int
    clarity_scores: List[int]
    claimed_reward_ids: List[str]
    unlocked_achievement_ids: List[str]
    hashed_password: Optional[str] = Field(default=None, exclude=True)
    created_at: datetime
    updated_at: datetime


class TaskSubtaskBackup(BaseModel):
    id: Optional[str]
    title: str
    completed: bool


class TaskCommentBackup(BaseModel):
    id: Optional[str]
    user_id: str
    content: str
    created_at: datetime


class TaskBackup(BaseModel):
    id: str
    title: str
    description: str
    status: TaskStatusEnum
    status_title: Optional[str] = None
    priority: TaskPriorityEnum
    team: str
    assigned_to_id: Optional[str]
    task_group_id: str
    created_by_id: str
    created_at: datetime
    updated_at: datetime
    due_at: Optional[datetime]
    completed_at: Optional[datetime]
    recurrence_rule: RecurrenceRuleEnum
    recurring_task_id: Optional[str]
    clarity_rating: Optional[int]
    attachments: List[str] = Field(default_factory=list)
    estimated_hours: Optional[float]
    tags: List[str] = Field(default_factory=list)
    subtasks: List[TaskSubtaskBackup] = Field(default_factory=list)
    comments: List[TaskCommentBackup] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)


class NotificationBackup(BaseModel):
    id: str
    user_id: str
    type: NotificationTypeEnum
    title: Optional[str] = None
    body: Optional[str] = None
    message: str
    entity_type: Optional[NotificationEntityTypeEnum] = None
    entity_id: Optional[str] = None
    deep_link: Optional[str] = None
    is_read: bool
    related_task_id: Optional[str] = None
    related_reward_id: Optional[str] = None
    related_chat_id: Optional[str] = None
    created_at: datetime


class UserRewardBackup(BaseModel):
    id: str
    user_id: str
    reward_id: str
    status: RewardClaimStatusEnum
    xp_spent: int = 0
    claimed_at: datetime
    resolved_at: Optional[datetime] = None
    approver_id: Optional[str] = None


class UserAchievementBackup(BaseModel):
    user_id: str
    achievement_id: str
    unlocked_at: datetime


class KanbanColumnBackup(BaseModel):
    id: str
    title: str
    order: int


class DataExportBundle(BaseModel):
    scope: DataExportScope
    generated_at: datetime
    departments: List[DepartmentRead] = Field(default_factory=list)
    users: List[UserBackup] = Field(default_factory=list)
    tasks: List[TaskBackup] = Field(default_factory=list)
    achievements: List[AchievementRead] = Field(default_factory=list)
    rewards: List[RewardRead] = Field(default_factory=list)
    kanban_columns: List[KanbanColumnRead] = Field(default_factory=list)
    notifications: List[NotificationBackup] = Field(default_factory=list)
    user_rewards: List[UserRewardBackup] = Field(default_factory=list)
    user_achievements: List[UserAchievementBackup] = Field(default_factory=list)


class DataImportPayload(BaseModel):
    scope: DataExportScope = DataExportScope.ALL
    departments: List[DepartmentRead] = Field(default_factory=list)
    users: List[UserBackup] = Field(default_factory=list)
    tasks: List[TaskBackup] = Field(default_factory=list)
    achievements: List[AchievementRead] = Field(default_factory=list)
    rewards: List[RewardRead] = Field(default_factory=list)
    kanban_columns: List[KanbanColumnRead] = Field(default_factory=list)
    notifications: List[NotificationBackup] = Field(default_factory=list)
    user_rewards: List[UserRewardBackup] = Field(default_factory=list)
    user_achievements: List[UserAchievementBackup] = Field(default_factory=list)


class ResetConfirmPayload(BaseModel):
    confirmation: str = ""
    otp: str = Field(min_length=4, max_length=10)


# ---------------------------------------------------------------------------
# Seasonal Rewards
# ---------------------------------------------------------------------------

class SeasonalRewardConfigBase(BaseModel):
    reward_type: str
    name: str
    description: str = ""
    points_required: int
    reward_value: str
    max_recipients: Optional[int] = None
    is_active: bool = True
    auto_distribute: bool = False
    notification_enabled: bool = True

class SeasonalRewardConfigCreate(SeasonalRewardConfigBase):
    pass

class SeasonalRewardConfigUpdate(BaseModel):
    reward_type: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    points_required: Optional[int] = None
    reward_value: Optional[str] = None
    max_recipients: Optional[int] = None
    is_active: Optional[bool] = None
    auto_distribute: Optional[bool] = None
    notification_enabled: Optional[bool] = None

class SeasonalRewardConfigRead(SeasonalRewardConfigBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    created_at: datetime
    updated_at: datetime

class RewardDistributionBase(BaseModel):
    season_id: str
    reward_type: str
    period_start: datetime
    period_end: datetime
    total_recipients: int
    total_rewards: int
    status: str
    details: str = ""

class RewardDistributionCreate(RewardDistributionBase):
    pass

class RewardDistributionUpdate(BaseModel):
    season_id: Optional[str] = None
    reward_type: Optional[str] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    total_recipients: Optional[int] = None
    total_rewards: Optional[int] = None
    status: Optional[str] = None
    details: Optional[str] = None

class RewardDistributionRead(RewardDistributionBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    created_at: datetime
    updated_at: datetime

class SeasonalLeaderboardBase(BaseModel):
    season_id: str
    user_id: str
    total_points: int
    rank: int

class SeasonalLeaderboardCreate(SeasonalLeaderboardBase):
    pass

class SeasonalLeaderboardUpdate(BaseModel):
    total_points: Optional[int] = None
    rank: Optional[int] = None

class SeasonalLeaderboardRead(SeasonalLeaderboardBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    created_at: datetime
    updated_at: datetime
    user: Optional[UserRead] = None


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------

class SeasonBase(BaseModel):
    name: str
    description: str = ""
    start_date: datetime
    end_date: datetime
    theme: str = ""
    bonus_multiplier: float = 1.0
    is_active: bool = True

class SeasonCreate(SeasonBase):
    pass

class SeasonUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    theme: Optional[str] = None
    bonus_multiplier: Optional[float] = None
    is_active: Optional[bool] = None

class SeasonRead(SeasonBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# User Progress
# ---------------------------------------------------------------------------

class UserProgressBase(BaseModel):
    user_id: str
    level_id: str
    season_id: str
    current_points: int = 0
    total_points_earned: int = 0

class UserProgressCreate(UserProgressBase):
    pass

class UserProgressUpdate(BaseModel):
    current_points: Optional[int] = None
    total_points_earned: Optional[int] = None

class UserProgressRead(UserProgressBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    level_unlocked_at: datetime
    created_at: datetime
    updated_at: datetime
    user: Optional[UserRead] = None
    level: Optional[LevelRead] = None
    season: Optional[SeasonRead] = None

# ---------------------------------------------------------------------------
# Start - Dashboard lottie code
#  Dashboard lottie code placeholder
# End - Dashboard lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - All Tasks lottie code
#  All Tasks lottie code placeholder
# End - All Tasks lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - Kanban Board lottie code
#  Kanban Board lottie code placeholder
# End - Kanban Board lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - Calendar lottie code
#  Calendar lottie code placeholder
# End - Calendar lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - Users lottie code
#  Users lottie code placeholder
# End - Users lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - Gantt Chart lottie code
#  Gantt Chart lottie code placeholder
# End - Gantt Chart lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - Reports lottie code
#  Reports lottie code placeholder
# End - Reports lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - Manage Rewards lottie code
#  Manage Rewards lottie code placeholder
# End - Manage Rewards lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - Achievements lottie code
#  Achievements lottie code placeholder
# End - Achievements lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - Points Table lottie code
#  Points Table lottie code placeholder
# End - Points Table lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - Template Editor lottie code
#  Template Editor lottie code placeholder
# End - Template Editor lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - API lottie code
#  API lottie code placeholder
# End - API lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - Profile lottie code
#  Profile lottie code placeholder
# End - Profile lottie code
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Start - Support lottie code
#  Support lottie code placeholder
# End - Support lottie code
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class PipelineStageBase(BaseModel):
    label: str
    status: TaskStatusEnum
    order: int

class PipelineStageCreate(PipelineStageBase):
    pass

class PipelineStageUpdate(BaseModel):
    label: Optional[str] = None
    status: Optional[TaskStatusEnum] = None
    order: Optional[int] = None

class PipelineStageRead(PipelineStageBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    pipeline_id: str
    status: TaskStatusEnum

class PipelineBase(BaseModel):
    name: str
    department_id: str

class PipelineCreate(PipelineBase):
    stages: Optional[List[PipelineStageCreate]] = None

class PipelineUpdate(BaseModel):
    name: Optional[str] = None
    department_id: Optional[str] = None

class PipelineRead(PipelineBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    created_by_id: str
    created_at: datetime
    stages: List[PipelineStageRead]
    department: Optional[DepartmentRead] = None

class PipelineMembershipUpdate(BaseModel):
    user_ids: List[str]


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    user_id: str
    name: str
    email: str
    avatar_url: Optional[str] = None
    avatar_frame: Optional[str] = None
    title: Optional[str] = None
    department_name: Optional[str] = None
    account_status: UserStatusEnum = UserStatusEnum.ACTIVE
    app_role: RoleEnum
    role: ChatMemberRoleEnum
    joined_at: datetime
    last_read_message_id: Optional[str] = None
    last_read_at: Optional[datetime] = None
    is_muted: bool = False
    is_pinned: bool = False


class ChatConversationBase(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    avatar_url: Optional[str] = Field(default=None, max_length=1024)
    project_id: Optional[str] = Field(default=None, max_length=36)
    team_id: Optional[str] = Field(default=None, max_length=255)
    is_private: bool = False


class ChatConversationCreate(ChatConversationBase):
    type: ChatConversationTypeEnum
    member_ids: List[str] = Field(default_factory=list)


class ChatSpaceCreate(ChatConversationBase):
    member_ids: List[str] = Field(default_factory=list)


class ChatGroupCreate(ChatConversationBase):
    name: str = Field(min_length=1, max_length=255)
    member_ids: List[str] = Field(min_length=1)


class ChatDirectCreate(BaseModel):
    user_id: Optional[str] = Field(default=None, min_length=1)
    target_user_id: Optional[str] = Field(default=None, min_length=1)

    @field_validator("target_user_id")
    @classmethod
    def target_or_user_id(cls, value: Optional[str], info):
        values = info.data
        if not value and not values.get("user_id"):
            raise ValueError("user_id is required")
        return value


class ChatDirectoryUserRead(BaseModel):
    id: str
    name: str
    email: str
    avatar_url: Optional[str] = None
    avatar_frame: Optional[str] = None
    presence: Literal["ONLINE", "AWAY", "OFFLINE"] = "OFFLINE"
    last_seen_at: Optional[datetime] = None
    role_name: Optional[str] = None
    team_name: Optional[str] = None
    title: Optional[str] = None
    existing_conversation_id: Optional[str] = None
    is_favorite: bool = False
    unread_count: int = 0
    latest_message_preview: Optional[str] = None
    last_message_at: Optional[datetime] = None


class ChatDirectoryPage(BaseModel):
    items: List[ChatDirectoryUserRead]
    next_cursor: Optional[str] = None


class ChatMemberAdd(BaseModel):
    user_ids: List[str] = Field(min_length=1)
    role: ChatMemberRoleEnum = ChatMemberRoleEnum.MEMBER


class ChatMemberUpdate(BaseModel):
    role: Optional[ChatMemberRoleEnum] = None
    is_muted: Optional[bool] = None
    is_pinned: Optional[bool] = None
    last_read_message_id: Optional[str] = None


class ChatConversationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    avatar_url: Optional[str] = Field(default=None, max_length=1024)
    is_private: Optional[bool] = None
    is_archived: Optional[bool] = None


class ChatMessageBase(BaseModel):
    content: str = Field(default="", max_length=5000)


class ChatMessageCreate(ChatMessageBase):
    message_type: ChatMessageTypeEnum = ChatMessageTypeEnum.TEXT
    client_id: Optional[str] = Field(default=None, max_length=128)
    reply_to_message_id: Optional[str] = None
    attachments: List["ChatAttachmentCreate"] = Field(default_factory=list)

    @model_validator(mode="after")
    def content_or_attachment(self):
        if not self.content.strip() and not self.attachments:
            raise ValueError("Message content or attachment is required")
        return self


class ChatMessageUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class ChatReadMarkerUpdate(BaseModel):
    last_read_message_id: Optional[str] = None


class ChatReactionCreate(BaseModel):
    emoji: str = Field(min_length=1, max_length=64)

    @field_validator("emoji")
    @classmethod
    def emoji_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("emoji is required")
        return value


class ChatReactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    message_id: str
    user_id: str
    emoji: str
    created_at: datetime


class ChatAttachmentCreate(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    original_file_name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=255)
    file_size: int = Field(ge=0)
    storage_key: str = Field(min_length=1, max_length=1024)
    url: Optional[str] = Field(default=None, max_length=1024)

    @field_validator("file_name", "original_file_name", "mime_type", "storage_key")
    @classmethod
    def required_text_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field is required")
        return value


class ChatAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    message_id: str
    file_name: str
    original_file_name: str
    mime_type: str
    file_size: int
    storage_key: str
    url: Optional[str] = None
    created_at: datetime


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    sender_id: str
    sender_name: str
    sender_role: RoleEnum
    message_type: ChatMessageTypeEnum
    client_id: Optional[str] = None
    content: str
    reply_to_message_id: Optional[str] = None
    edited_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    reactions: List[ChatReactionRead] = Field(default_factory=list)
    attachments: List[ChatAttachmentRead] = Field(default_factory=list)
    mentions: List[str] = Field(default_factory=list)


class ChatPinnedMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    message_id: str
    pinned_by: str
    created_at: datetime
    message: ChatMessageRead


class ChatConversationRead(ChatConversationBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    type: ChatConversationTypeEnum
    created_by_id: Optional[str]
    is_archived: bool = False
    created_at: datetime
    updated_at: datetime
    last_message_at: Optional[datetime]
    members: List[ChatMemberRead] = Field(default_factory=list)
    unread_count: int = 0


class ChatConversationSummary(ChatConversationRead):
    last_message: Optional[ChatMessageRead] = None


class ChatConversationDetail(ChatConversationRead):
    messages: List[ChatMessageRead] = Field(default_factory=list)


class ChatMessagePage(BaseModel):
    items: List[ChatMessageRead]
    next_cursor: Optional[str] = None
    has_more: bool = False


class ChatMessageSearchResult(BaseModel):
    message: ChatMessageRead
    conversation: ChatConversationSummary


class ChatMessageSearchPage(BaseModel):
    items: List[ChatMessageSearchResult]
    next_cursor: Optional[str] = None
    has_more: bool = False


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class NotificationBase(BaseModel):
    type: NotificationTypeEnum
    title: Optional[str] = None
    body: Optional[str] = None
    message: str
    entity_type: Optional[NotificationEntityTypeEnum] = None
    entity_id: Optional[str] = None
    deep_link: Optional[str] = None
    related_task_id: Optional[str] = None
    related_reward_id: Optional[str] = None
    related_chat_id: Optional[str] = None


class NotificationCreate(NotificationBase):
    user_id: str


class NotificationRead(NotificationBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    is_read: bool
    created_at: datetime
    alert_kind: Optional[str] = None

    @field_validator("created_at", mode="after")
    @classmethod
    def notification_utc(cls, value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


NotificationModule = Literal["tasks", "tickets", "users", "departments", "comments", "chat"]


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionCreate(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys
    user_agent: Optional[str] = None
    device_label: Optional[str] = None
    binding_protocol: Optional[Literal["user-v1"]] = None


class PushSubscriptionDelete(BaseModel):
    endpoint: str


class PushSubscriptionPublicKey(BaseModel):
    public_key: str


class PushTestResult(BaseModel):
    delivered: int


class NotificationPreferenceRead(BaseModel):
    module: NotificationModule
    push_enabled: bool
    updated_at: Optional[datetime] = None
    sound_enabled: bool = False
    near_deadline_hours: int = 24
    productive_capacity_hours: Optional[float] = None
    overtime_threshold_minutes: int = 0
    quiet_start: Optional[str] = None
    quiet_end: Optional[str] = None


class NotificationPreferenceUpdate(BaseModel):
    module: NotificationModule
    push_enabled: bool
    sound_enabled: Optional[bool] = None
    near_deadline_hours: Optional[int] = Field(default=None, ge=1, le=8760)
    productive_capacity_hours: Optional[float] = Field(default=None, gt=0, le=24, allow_inf_nan=False)
    overtime_threshold_minutes: Optional[int] = Field(default=None, ge=0, le=1440)
    quiet_start: Optional[str] = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    quiet_end: Optional[str] = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class NotificationPreferenceBatchUpdate(BaseModel):
    preferences: List[NotificationPreferenceUpdate]


class ApprovalRead(BaseModel):
    id: str
    scope_type: ApprovalScopeTypeEnum
    scope_id: str
    status: ApprovalStatusEnum
    order_index: Optional[int] = None
    requested_by: str
    approver_id: Optional[str] = None
    comment: Optional[str] = None
    sla_hours: int
    created_at: datetime
    acted_at: Optional[datetime] = None


class ApprovalActionPayload(BaseModel):
    decision: Literal["approved", "rejected", "cancelled"]
    comment: Optional[str] = None


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


class WebhookBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2048)
    subscribed_events: List[str] = Field(default_factory=list)
    is_enabled: bool = True
    custom_headers: Optional[Dict[str, str]] = None


class WebhookCreate(WebhookBase):
    pass


class WebhookUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    url: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    subscribed_events: Optional[List[str]] = None
    is_enabled: Optional[bool] = None
    custom_headers: Optional[Dict[str, str]] = None


class WebhookRead(WebhookBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    secret: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WebhookDeliveryLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    status: str
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    response_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    attempt_count: int
    last_attempt_at: Optional[datetime] = None
    created_at: datetime


class WebhookDeliveryLogPage(BaseModel):
    items: List[WebhookDeliveryLogRead] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class WebhookTestRequest(BaseModel):
    event_name: Optional[str] = None


class WebhookTestResponse(BaseModel):
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    response_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    delivered_at: Optional[datetime] = None


class WebhookDispatchRequest(BaseModel):
    event: str
    data: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Configurations
# ---------------------------------------------------------------------------


class SmtpConfigBase(BaseModel):
    host: str
    port: int
    username: str
    password: Optional[str] = None
    encryption: str = "tls"


class SmtpConfigUpdate(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    encryption: Optional[str] = None


class SmtpConfigRead(SmtpConfigBase):
    model_config = ConfigDict(from_attributes=True)


class ApiConfigBase(BaseModel):
    provider: str
    api_key: Optional[str] = None


class ApiConfigUpdate(ApiConfigBase):
    pass


class ApiConfigRead(ApiConfigBase):
    model_config = ConfigDict(from_attributes=True)


class PointsTableConfigBase(BaseModel):
    points_config: Optional[Dict[str, Dict[str, Dict[str, int]]]] = None
    task_creation_points: Optional[int] = None
    clarity_points_per_star: Optional[int] = None
    manager_overdue_penalty: Optional[int] = None


class PointsTableConfigUpdate(PointsTableConfigBase):
    pass


class PointsTableConfigRead(PointsTableConfigBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------#
# Release Notes
# ---------------------------------------------------------------------------#


class ReleaseNotesBase(BaseModel):
    version_label: str
    content_mode: Literal["text", "code"] = "text"
    details_text: Optional[str] = None
    html: Optional[str] = None
    css: Optional[str] = None
    js: Optional[str] = None


class ReleaseNotesUpdate(BaseModel):
    version_label: Optional[str] = None
    content_mode: Optional[Literal["text", "code"]] = None
    details_text: Optional[str] = None
    html: Optional[str] = None
    css: Optional[str] = None
    js: Optional[str] = None


class ReleaseNotesRead(ReleaseNotesBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    updated_by_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------#
# Multiple SMTP Configurations
# ---------------------------------------------------------------------------#


class MultipleSmtpConfigBase(BaseModel):
    name: str
    host: str
    port: int
    username: str
    password: Optional[str] = None
    encryption: str = "tls"
    notification_types: List[str] = Field(default_factory=list)


class MultipleSmtpConfigCreate(MultipleSmtpConfigBase):
    pass


class MultipleSmtpConfigUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    encryption: Optional[str] = None
    notification_types: Optional[List[str]] = None


class MultipleSmtpConfigRead(MultipleSmtpConfigBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------#
# Email templates
# ---------------------------------------------------------------------------#


class EmailTemplateBase(BaseModel):
    notification_type: str
    subject: str
    body: str


class EmailTemplateUpdate(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None


class EmailTemplateRead(EmailTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class SmtpTestPayload(BaseModel):
    notification_type: str
    to_address: str
    subject: Optional[str] = None
    body: Optional[str] = None


# ---------------------------------------------------------------------------#
# OAuth Configurations
# ---------------------------------------------------------------------------#


class OAuthConfigBase(BaseModel):
    name: str
    redirect_url: str
    scopes: List[str] = Field(default_factory=list)
    n8n_integration: bool = False


class OAuthConfigCreate(OAuthConfigBase):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    api_key: Optional[str] = None


class OAuthConfigUpdate(BaseModel):
    name: Optional[str] = None
    redirect_url: Optional[str] = None
    scopes: Optional[List[str]] = None
    n8n_integration: Optional[bool] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    api_key: Optional[str] = None


class OAuthCredentialsRotate(BaseModel):
    rotate_client_id: bool = False
    rotate_client_secret: bool = True
    rotate_api_key: bool = True


class OAuthConfigRead(OAuthConfigBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    client_secret: str
    api_key: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def serialize_database_id(cls, value):
        return str(value)


# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------


class N8NTriggerRequest(BaseModel):
    event: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class AuthResponse(BaseModel):
    token: Token
    user: UserRead


TaskRead.model_rebuild()


# ---------------------------------------------------------------------------#
# Task Templates
# ---------------------------------------------------------------------------#


class TaskTemplateBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    priority: TaskPriorityEnum = TaskPriorityEnum.MEDIUM
    team: str = "General"
    subtasks: List[str] = Field(default_factory=list)
    attachments: List[str] = Field(default_factory=list)
    estimated_hours: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    featured_image: Optional[str] = None
    department_id: Optional[str] = None
    recurrence_rule: RecurrenceRuleEnum = RecurrenceRuleEnum.NONE


class TaskTemplateCreate(TaskTemplateBase):
    pass


class TaskTemplateUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[TaskPriorityEnum] = None
    team: Optional[str] = None
    subtasks: Optional[List[str]] = None
    attachments: Optional[List[str]] = None
    estimated_hours: Optional[float] = None
    tags: Optional[List[str]] = None
    featured_image: Optional[str] = None
    department_id: Optional[str] = None


class TaskTemplateRead(TaskTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_by_id: str
    created_at: datetime
    updated_at: datetime
    department: Optional[DepartmentRead] = None
    creator: Optional[UserRead] = None


class TaskTemplateAssignRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    assignment_type: str = Field(..., alias="assignmentType", pattern="^(single|multiple|department)$")
    user_ids: Optional[List[str]] = Field(default=None, alias="userIds")
    department_id: Optional[str] = Field(default=None, alias="departmentId")
    planned_start_date: Optional[date] = Field(default=None, alias="plannedStartDate")
    planned_end_date: Optional[date] = Field(default=None, alias="plannedEndDate")

    @model_validator(mode="after")
    def planned_range(self):
        if self.planned_start_date and self.planned_end_date and self.planned_start_date > self.planned_end_date:
            raise ValueError("Planned end precedes start")
        return self


# ---------------------------------------------------------------------------#
# Media Library
# ---------------------------------------------------------------------------#


class MediaSortOption(str, Enum):
    CREATED_DESC = "created_desc"
    CREATED_ASC = "created_asc"
    SIZE_DESC = "size_desc"
    SIZE_ASC = "size_asc"


class MediaItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    filename: str
    ext: str
    mime_type: str
    size_bytes: int
    category: MediaCategoryEnum
    storage_provider: StorageProviderEnum
    storage_path: str
    public_url: str
    width: Optional[int] = None
    height: Optional[int] = None
    checksum_sha256: str
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    original_id: Optional[str] = None


class MediaListResponse(BaseModel):
    items: List[MediaItemRead]
    page: int
    page_size: int
    total: int


class MediaUpdateRequest(BaseModel):
    filename: Optional[str] = Field(default=None, min_length=1, max_length=255)


class MediaProviderConnectRequest(BaseModel):
    provider: StorageProviderEnum

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: str | StorageProviderEnum) -> StorageProviderEnum | str:
        if isinstance(value, StorageProviderEnum):
            return value
        normalized = (value or "").lower()
        if normalized == "google_drive":
            normalized = "gdrive"
        return normalized


class MediaProviderStatusResponse(BaseModel):
    provider: StorageProviderEnum
    status: str
    details: Optional[str] = None


class MediaBulkDeleteRequest(BaseModel):
    ids: List[str] = Field(default_factory=list)
    hard: bool = False


class MediaBulkDeleteResponse(BaseModel):
    deleted: int


class AvatarCropMetadata(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    scale: float = Field(default=1.0, gt=0)
    rotate: float = Field(default=0.0)


class MediaPresignRequest(BaseModel):
    purpose: Literal["library", "avatar"]
    tab: Optional[Literal["images", "videos", "documents", "zip"]] = None
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1)


class MediaPresignResponse(BaseModel):
    upload_url: str
    bucket: str
    object_key: str
    file_id: str
    expires_in: int


class MediaConfirmRequest(BaseModel):
    file_id: str = Field(min_length=1)
    crop: Optional[AvatarCropMetadata] = None


class MediaConfirmResponse(BaseModel):
    file_id: str
    status: str


class AvatarFinalizeRequest(BaseModel):
    file_id: str = Field(min_length=1)
    crop: AvatarCropMetadata


class AvatarFinalizeResponse(BaseModel):
    file_id: str
    profile_image_key: str
    profile_image_url: str


class MediaFileListItem(BaseModel):
    id: str
    original_filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    read_url: str


class MediaFileListResponse(BaseModel):
    items: List[MediaFileListItem]
    page: int
    page_size: int
    total: int



class FeatureFlagBase(BaseModel):
    key: str
    label: str
    group: str
    description: str | None = None
    enabled: bool


class FeatureFlagRead(FeatureFlagBase):
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FeatureFlagUpdate(BaseModel):
    key: str
    enabled: bool


class FeatureFlagUpdateRequest(BaseModel):
    flags: list[FeatureFlagUpdate]
