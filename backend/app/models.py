"""SQLAlchemy models for the Vee Task Manager backend."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, attributes, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .database import Base


class UTCDateTime(TypeDecorator):
    """New workflow timestamps are UTC, including SQLite's naive storage format."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Workflow timestamps require an explicit timezone")
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RoleEnum(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    MANAGER = "manager"
    OWNER = "owner"


class UserStatusEnum(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class TaskPriorityEnum(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class TaskStatusEnum(str, enum.Enum):
    WAITING_FOR_REQUIREMENT = "WAITING_FOR_REQUIREMENT"
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    BUG_FIXING = "BUG_FIXING"
    IN_REVIEW = "IN_REVIEW"
    BLOCKED = "BLOCKED"
    ON_HOLD = "ON_HOLD"
    DONE = "DONE"
    DEPLOYED = "DEPLOYED"
    FAILED = "FAILED"
    GRAVEYARD = "GRAVEYARD"


class TaskApprovalStatusEnum(str, enum.Enum):
    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RecurrenceRuleEnum(str, enum.Enum):
    NONE = "NONE"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    AFTER_COMPLETION = "AFTER_COMPLETION"


class NotificationTypeEnum(str, enum.Enum):
    TASK_CREATED = "TASK_CREATED"
    TASK_UPDATED = "TASK_UPDATED"
    TASK_DELETED = "TASK_DELETED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    TASK_OVERDUE = "TASK_OVERDUE"
    COMMENT_ADDED = "COMMENT_ADDED"
    ACHIEVEMENT_UNLOCKED = "ACHIEVEMENT_UNLOCKED"
    REWARD_CLAIMED = "REWARD_CLAIMED"
    CHAT_MESSAGE = "CHAT_MESSAGE"
    TICKET_CREATED = "TICKET_CREATED"
    TICKET_UPDATED = "TICKET_UPDATED"
    TICKET_DELETED = "TICKET_DELETED"
    TICKET_ASSIGNED = "TICKET_ASSIGNED"
    TICKET_CLOSED = "TICKET_CLOSED"
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    USER_DELETED = "USER_DELETED"
    DEPARTMENT_CREATED = "DEPARTMENT_CREATED"
    DEPARTMENT_UPDATED = "DEPARTMENT_UPDATED"
    DEPARTMENT_DELETED = "DEPARTMENT_DELETED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_ACTED = "APPROVAL_ACTED"
    SLA_BREACH = "SLA_BREACH"


class NotificationEntityTypeEnum(str, enum.Enum):
    TICKET = "ticket"
    TASK = "task"
    APPROVAL = "approval"
    USER = "user"
    DEPARTMENT = "department"


class ApprovalScopeTypeEnum(str, enum.Enum):
    TICKET = "ticket"
    TASK = "task"
    OVERRIDE_CLOSE = "override_close"


class ApprovalStatusEnum(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class TaskTransferStatusEnum(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ToolCategoryStatusEnum(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ToolPricingTypeEnum(str, enum.Enum):
    FREE = "free"
    PAID = "paid"
    TRIAL = "trial"


class ToolStatusEnum(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AuditLogSourceEnum(str, enum.Enum):
    MANUAL = "manual"
    AUTOMATION = "automation"
    API = "api"
    SYSTEM = "system"


class AuditLogSeverityEnum(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AuditLogStatusEnum(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"


class AuditLogCategoryEnum(str, enum.Enum):
    USER = "user"
    TASK = "task"
    TICKET = "ticket"
    APPROVAL = "approval"
    AUTOMATION = "automation"
    NOTIFICATION = "notification"
    SECURITY = "security"
    SYSTEM = "system"


class ChatConversationTypeEnum(str, enum.Enum):
    SPACE = "SPACE"
    DIRECT = "DIRECT"
    GROUP = "GROUP"


class ChatMemberRoleEnum(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class ChatMessageTypeEnum(str, enum.Enum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    FILE = "FILE"
    SYSTEM = "SYSTEM"


class AvatarStorageTypeEnum(str, enum.Enum):
    FILE = "file"
    DATA_URL = "data_url"
    EXTERNAL_URL = "external_url"


class MediaCategoryEnum(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    MUSIC = "music"
    DOCUMENT = "doc"
    ZIP = "zip"


class MediaFileTypeEnum(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    ZIP = "zip"
    AVATAR = "avatar"


class MediaFileStatusEnum(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class StorageProviderEnum(str, enum.Enum):
    LOCAL = "local"
    SUPABASE = "supabase"
    GDRIVE = "gdrive"


class RewardImageSourceEnum(str, enum.Enum):
    LIBRARY = "LIBRARY"
    UPLOAD = "UPLOAD"


class RewardStatusEnum(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class RewardClaimStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REDEEMED = "REDEEMED"


class RewardLogActionEnum(str, enum.Enum):
    CREATED = "CREATED"
    EDITED = "EDITED"
    DELETED = "DELETED"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    AUTO_ASSIGNED = "AUTO_ASSIGNED"
    IMAGE_DELETED = "IMAGE_DELETED"
    AUTO_REDEEMED = "AUTO_REDEEMED"


class BadgeStateEnum(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class BadgeProgressStatusEnum(str, enum.Enum):
    LOCKED = "locked"
    IN_PROGRESS = "in_progress"
    EARNED = "earned"


class NodeTypeEnum(str, enum.Enum):
    CHECKPOINT = "CHECKPOINT"
    TOWER = "TOWER"
    DECOR = "DECOR"
    GIFT = "GIFT"


class EventTypeEnum(str, enum.Enum):
    REACHED = "REACHED"
    CLAIMED = "CLAIMED"
    ANIM_SHOWN = "ANIM_SHOWN"



# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Use aware UTC timestamps for timezone-aware database columns."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Association tables
# ---------------------------------------------------------------------------


task_dependencies = Table(
    'task_dependencies',
    Base.metadata,
    Column('task_id', String(36), ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
    Column('depends_on_task_id', String(36), ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
)


task_followers = Table(
    'task_followers',
    Base.metadata,
    Column('task_id', String(36), ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
    Column('user_id', String(36), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime(timezone=True), default=utc_now, nullable=False),
)



# ---------------------------------------------------------------------------
# Core models


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    users: Mapped[List["User"]] = relationship("User", back_populates="department")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("auth_epoch >= 0", name="ck_users_auth_epoch"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    employer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # PostgreSQL migration trigger advances this on security-sensitive updates.
    auth_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    role: Mapped[RoleEnum] = mapped_column(SAEnum(RoleEnum), default=RoleEnum.USER, nullable=False)
    department_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    manager_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    manager_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    webex_person_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    shift_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    shift_start: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    shift_end: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    morning_break_start: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    morning_break_end: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    lunch_break_start: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    lunch_break_end: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    evening_break_start: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    evening_break_end: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    profile_bio: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    skills: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    projects: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[UserStatusEnum] = mapped_column(
        SAEnum(UserStatusEnum), default=UserStatusEnum.ACTIVE, nullable=False
    )
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clarity_scores: Mapped[List[int]] = mapped_column(JSON, default=list, nullable=False)
    claimed_reward_ids: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    unlocked_achievement_ids: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    avatar_asset_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("avatar_assets.id", ondelete="SET NULL"), nullable=True
    )
    avatar_frame: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    profile_image_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    profile_image_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    department: Mapped[Optional[Department]] = relationship("Department", back_populates="users")
    comments: Mapped[List["Comment"]] = relationship(
        "Comment", back_populates="author", cascade="all, delete-orphan"
    )
    tasks_assigned: Mapped[List["Task"]] = relationship(
        "Task", back_populates="assignee", foreign_keys="Task.assigned_to_id"
    )
    tasks_created_rel: Mapped[List["Task"]] = relationship(
        "Task", back_populates="creator", foreign_keys="Task.created_by_id"
    )
    followed_tasks: Mapped[List["Task"]] = relationship(
        "Task",
        secondary=task_followers,
        back_populates="followers",
    )
    avatar_asset: Mapped[Optional["AvatarAsset"]] = relationship(
        "AvatarAsset", back_populates="users", foreign_keys=[avatar_asset_id]
    )
    created_avatars: Mapped[List["AvatarAsset"]] = relationship(
        "AvatarAsset",
        back_populates="creator",
        foreign_keys="AvatarAsset.created_by_id",
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )
    push_subscriptions: Mapped[List["PushSubscription"]] = relationship(
        "PushSubscription", back_populates="user", cascade="all, delete-orphan"
    )
    notification_preferences: Mapped[List["NotificationPreference"]] = relationship(
        "NotificationPreference", back_populates="user", cascade="all, delete-orphan"
    )
    chat_participations: Mapped[List["ChatParticipant"]] = relationship(
        "ChatParticipant", back_populates="user", cascade="all, delete-orphan"
    )
    chat_messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="sender"
    )
    created_conversations: Mapped[List["ChatConversation"]] = relationship(
        "ChatConversation", back_populates="created_by"
    )
    media_files: Mapped[List["MediaFile"]] = relationship(
        "MediaFile",
        back_populates="owner",
        foreign_keys="MediaFile.user_id",
        cascade="all, delete-orphan",
    )
    media_items: Mapped[List["MediaItem"]] = relationship(
        "MediaItem",
        back_populates="owner",
        foreign_keys="MediaItem.owner_id",
        cascade="all, delete-orphan",
    )
    reward_claims: Mapped[List["RewardClaim"]] = relationship(
        "RewardClaim",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="RewardClaim.user_id",
    )
    approved_reward_claims: Mapped[List["RewardClaim"]] = relationship(
        "RewardClaim",
        back_populates="approver",
        foreign_keys="RewardClaim.approver_id",
    )

    @property
    def claimed_xp_points(self) -> int:
        total = 0
        for claim in self.reward_claims or []:
            if claim.status == RewardClaimStatusEnum.REJECTED:
                continue
            total += claim.xp_spent if claim.xp_spent is not None else (claim.reward.xp_required if claim.reward else 0)
        return total

    @property
    def overall_xp_points(self) -> int:
        return (self.points or 0) + self.claimed_xp_points


class AvatarAsset(Base):
    __tablename__ = "avatar_assets"

    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    storage_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_type: Mapped[AvatarStorageTypeEnum] = mapped_column(
        SAEnum(AvatarStorageTypeEnum), default=AvatarStorageTypeEnum.FILE, nullable=False
    )
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    data_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    creator: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="created_avatars",
        foreign_keys=[created_by_id],
    )
    users: Mapped[List["User"]] = relationship(
        "User",
        back_populates="avatar_asset",
        foreign_keys=[User.avatar_asset_id],
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_assignee_status_updated", "assigned_to_id", "status", "updated_at"),
        Index("ix_tasks_creator_status", "created_by_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[TaskStatusEnum] = mapped_column(
        SAEnum(TaskStatusEnum), default=TaskStatusEnum.TODO, nullable=False
    )
    priority: Mapped[TaskPriorityEnum] = mapped_column(
        SAEnum(TaskPriorityEnum), default=TaskPriorityEnum.MEDIUM, nullable=False
    )
    team: Mapped[str] = mapped_column(String(255), default="General", nullable=False)
    task_group_id: Mapped[str] = mapped_column(
        String(36), default=generate_uuid, nullable=False, index=True
    )
    ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True
    )
    assigned_to_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approval_status: Mapped[TaskApprovalStatusEnum] = mapped_column(
        SAEnum(
            TaskApprovalStatusEnum,
            name="task_approval_status_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=TaskApprovalStatusEnum.NONE,
        nullable=False,
    )
    approver_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    recurrence_rule: Mapped[RecurrenceRuleEnum] = mapped_column(
        SAEnum(RecurrenceRuleEnum), default=RecurrenceRuleEnum.NONE, nullable=False
    )
    recurring_task_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    clarity_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    attachments: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    estimated_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    search_vector: Mapped[Optional[str]] = mapped_column(
        TSVECTOR().with_variant(Text, "sqlite"),
        Computed(
            "to_tsvector('english', coalesce(title,'') || ' ' || coalesce(description,''))",
            persisted=True,
        ),
        nullable=True,
    )

    assignee: Mapped[Optional[User]] = relationship(
        "User", back_populates="tasks_assigned", foreign_keys=[assigned_to_id]
    )
    creator: Mapped[User] = relationship(
        "User", back_populates="tasks_created_rel", foreign_keys=[created_by_id]
    )
    approver: Mapped[Optional[User]] = relationship(
        "User", foreign_keys=[approver_id]
    )
    ticket: Mapped[Optional["Ticket"]] = relationship("Ticket")
    subtasks: Mapped[List["Subtask"]] = relationship(
        "Subtask", back_populates="task", cascade="all, delete-orphan"
    )
    comments: Mapped[List["Comment"]] = relationship(
        "Comment", back_populates="task", cascade="all, delete-orphan"
    )
    messages: Mapped[List["TaskMessage"]] = relationship(
        "TaskMessage", back_populates="task", cascade="all, delete-orphan"
    )
    dependencies: Mapped[List["Task"]] = relationship(
        "Task",
        secondary=task_dependencies,
        primaryjoin=lambda: Task.id == task_dependencies.c.task_id,
        secondaryjoin=lambda: Task.id == task_dependencies.c.depends_on_task_id,
        back_populates="dependents",
    )
    dependents: Mapped[List["Task"]] = relationship(
        "Task",
        secondary=task_dependencies,
        primaryjoin=lambda: Task.id == task_dependencies.c.depends_on_task_id,
        secondaryjoin=lambda: Task.id == task_dependencies.c.task_id,
        back_populates="dependencies",
    )
    followers: Mapped[List[User]] = relationship(
        "User",
        secondary=task_followers,
        back_populates="followed_tasks",
    )


class Subtask(Base):
    __tablename__ = "subtasks"
    __table_args__ = (
        CheckConstraint("planned_end_date IS NULL OR planned_start_date IS NULL OR planned_end_date >= planned_start_date", name="ck_subtasks_planned_dates"),
        CheckConstraint("actual_end_at IS NULL OR actual_start_at IS NULL OR actual_end_at >= actual_start_at", name="ck_subtasks_actual_dates"),
        CheckConstraint("version >= 1", name="ck_subtasks_version"),
        CheckConstraint("priority_override IS NULL OR priority_override IN ('LOW','MEDIUM','HIGH','URGENT')", name="ck_subtasks_priority_override"),
        CheckConstraint("length(trim(point_policy_version)) > 0", name="ck_subtasks_policy_version"),
        Index("ix_subtasks_task_completed", "task_id", "completed"),
        Index("ix_subtasks_task_policy", "task_id", "point_policy_version"),
        Index("ix_subtasks_task_workflow_status", "task_id", "workflow_status"),
        Index("ix_subtasks_reward_order", "task_id", "point_policy_version", "deleted_at", "created_at", "id"),
        CheckConstraint("workflow_version IN (0,2)", name="ck_subtasks_workflow_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    planned_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    planned_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    actual_start_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    actual_end_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    priority_override: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    point_policy_version: Mapped[str] = mapped_column(String(80), default="legacy", server_default="legacy", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    # Legacy rows have no known creation instant; migrations never invent one.
    created_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), default=utc_now, nullable=True)
    # Independent of reward activation: legacy checklist rows stay at version 0.
    workflow_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    workflow_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    reward_timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    task: Mapped[Task] = relationship("Task", back_populates="subtasks")

    @property
    def status(self):
        return self.workflow_status or ("COMPLETED" if self.completed else "TODO")

    @property
    def managed(self):
        return self.workflow_version == 2

    @property
    def effective_priority(self):
        return self.priority_override or self.task.priority


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    task: Mapped[Task] = relationship("Task", back_populates="comments")
    author: Mapped[User] = relationship("User", back_populates="comments")


class TaskMessage(Base):
    __tablename__ = "task_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    mentions: Mapped[List[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    task: Mapped[Task] = relationship("Task", back_populates="messages")
    author: Mapped[User] = relationship("User")


class KanbanColumn(Base):
    __tablename__ = "kanban_columns"
    __table_args__ = (UniqueConstraint("order", name="uq_kanban_column_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    title: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)


class Achievement(Base):
    __tablename__ = "achievements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    icon: Mapped[str] = mapped_column(String(100), nullable=False)

    user_unlocks: Mapped[List["UserAchievement"]] = relationship(
        "UserAchievement", back_populates="achievement", cascade="all, delete-orphan"
    )


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    achievement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("achievements.id", ondelete="CASCADE"), primary_key=True
    )
    unlocked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped[User] = relationship("User", backref="achievement_links")
    achievement: Mapped[Achievement] = relationship("Achievement", back_populates="user_unlocks")


class Badge(Base):
    __tablename__ = "badges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(String(50), nullable=False)
    tier_group: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    tier_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    bonus_xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    image_asset_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    state: Mapped[BadgeStateEnum] = mapped_column(
        SAEnum(BadgeStateEnum), default=BadgeStateEnum.DRAFT, nullable=False
    )
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    ruleset: Mapped[Optional["BadgeRule"]] = relationship(
        "BadgeRule", back_populates="badge", cascade="all, delete-orphan", uselist=False
    )
    progress: Mapped[List["UserBadgeProgress"]] = relationship(
        "UserBadgeProgress", back_populates="badge", cascade="all, delete-orphan"
    )


class BadgeRule(Base):
    __tablename__ = "badge_rules"

    badge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("badges.id", ondelete="CASCADE"), primary_key=True
    )
    rules: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    badge: Mapped[Badge] = relationship("Badge", back_populates="ruleset")


class UserBadgeProgress(Base):
    __tablename__ = "user_badge_progress"
    __table_args__ = (UniqueConstraint("user_id", "badge_id", name="uq_user_badge_progress"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    badge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("badges.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[BadgeProgressStatusEnum] = mapped_column(
        SAEnum(BadgeProgressStatusEnum), default=BadgeProgressStatusEnum.LOCKED, nullable=False
    )
    progress_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    earned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user: Mapped[User] = relationship("User", backref="badge_progress")
    badge: Mapped[Badge] = relationship("Badge", back_populates="progress")


class RewardIcon(Base):
    __tablename__ = "reward_icons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)


class Reward(Base):
    __tablename__ = "rewards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    image_source: Mapped[RewardImageSourceEnum] = mapped_column(
        SAEnum(RewardImageSourceEnum), default=RewardImageSourceEnum.LIBRARY, nullable=False
    )
    image_ref: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    xp_required: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dept_whitelist: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    auto_redeem: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_multiple_claims: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[RewardStatusEnum] = mapped_column(
        SAEnum(RewardStatusEnum), default=RewardStatusEnum.ACTIVE, nullable=False
    )
    created_by_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    created_by: Mapped[Optional[User]] = relationship(
        "User", foreign_keys=[created_by_id], backref="rewards_created"
    )
    updated_by: Mapped[Optional[User]] = relationship(
        "User", foreign_keys=[updated_by_id], backref="rewards_updated"
    )
    claims: Mapped[List["RewardClaim"]] = relationship(
        "RewardClaim", back_populates="reward", cascade="all, delete-orphan"
    )


class RewardClaim(Base):
    __tablename__ = "reward_claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    reward_id: Mapped[str] = mapped_column(String(36), ForeignKey("rewards.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[RewardClaimStatusEnum] = mapped_column(
        SAEnum(RewardClaimStatusEnum), default=RewardClaimStatusEnum.PENDING, nullable=False
    )
    xp_spent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approver_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    reward: Mapped[Reward] = relationship("Reward", back_populates="claims")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id], back_populates="reward_claims")
    approver: Mapped[Optional[User]] = relationship(
        "User", foreign_keys=[approver_id], back_populates="approved_reward_claims"
    )


class RewardLog(Base):
    __tablename__ = "reward_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    action: Mapped[RewardLogActionEnum] = mapped_column(SAEnum(RewardLogActionEnum), nullable=False)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    actor: Mapped[Optional[User]] = relationship("User")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scope_type: Mapped[ApprovalScopeTypeEnum] = mapped_column(
        SAEnum(
            ApprovalScopeTypeEnum,
            name="approval_scope_type_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requested_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    approver_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    order_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[ApprovalStatusEnum] = mapped_column(
        SAEnum(
            ApprovalStatusEnum,
            name="approval_status_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ApprovalStatusEnum.PENDING,
        nullable=False,
    )
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sla_hours: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    acted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    requester: Mapped[User] = relationship("User", foreign_keys=[requested_by])
    approver: Mapped[Optional[User]] = relationship("User", foreign_keys=[approver_id])


class TaskTransferRequest(Base):
    __tablename__ = "task_transfer_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    from_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    to_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=False
    )
    requested_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=False
    )
    approved_by_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[TaskTransferStatusEnum] = mapped_column(
        SAEnum(
            TaskTransferStatusEnum,
            name="task_transfer_status_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=TaskTransferStatusEnum.PENDING,
        nullable=False,
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    acted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped["Task"] = relationship("Task")
    from_user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[from_user_id])
    to_user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[to_user_id])
    requested_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[requested_by_id])
    approved_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[approved_by_id])


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("audit_schema_version IN (1, 2)", name="ck_audit_events_schema_version"),
        Index("ix_audit_events_tenant_task_time", "tenant_id", "task_id", "created_at", "id"),
        Index("ix_audit_events_tenant_subtask_time", "tenant_id", "subtask_id", "created_at", "id"),
        Index("ix_audit_events_tenant_correlation", "tenant_id", "correlation_id"),
        Index("ix_audit_events_tenant_type_time", "tenant_id", "event_type", "created_at", "id"),
        Index("ix_audit_events_actor_v2", "actor_id", sqlite_where=text("audit_schema_version = 2"), postgresql_where=text("audit_schema_version = 2")),
        Index("ix_audit_events_task_ref", "task_id"),
        Index("ix_audit_events_subtask_ref", "subtask_id"),
        Index("uq_work_activity_request", "tenant_id", "actor_id", "correlation_id", unique=True,
              sqlite_where=text("event_type IN ('work.started','work.paused','work.resumed','work.stopped','work.switched','work.completed')"),
              postgresql_where=text("event_type IN ('work.started','work.paused','work.resumed','work.stopped','work.switched','work.completed')")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    # Version 1 is the untouched legacy log; version 2 is append-only task activity.
    audit_schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True)
    subtask_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("subtasks.id", ondelete="RESTRICT"), nullable=True)
    before: Mapped[Optional[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    after: Mapped[Optional[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    actor: Mapped[Optional[User]] = relationship("User", foreign_keys=[actor_id])


class TaskWorkflowSettings(Base):
    """Server-owned activation marker, separate from global UI feature flags."""
    __tablename__ = "task_workflow_settings"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_task_workflow_settings_version"),
        CheckConstraint("NOT enabled OR (activated_at IS NOT NULL AND point_policy_version <> 'legacy')", name="ck_task_workflow_settings_activation"),
        CheckConstraint("length(trim(point_policy_version)) > 0", name="ck_task_workflow_settings_policy"),
        Index("uq_task_workflow_settings_active_tenant", "tenant_id", unique=True,
              sqlite_where=text("enabled = 1"), postgresql_where=text("enabled")),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    point_policy_version: Mapped[str] = mapped_column(String(80), primary_key=True, default="legacy", server_default="legacy", nullable=False)
    activated_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    reward_policy_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)


class TaskWorkInterval(Base):
    """Actual manually recorded work; independent of status elapsed time."""
    __tablename__ = "task_work_intervals"
    __table_args__ = (
        CheckConstraint("ended_at > started_at", name="ck_task_work_intervals_positive"),
        Index("ix_task_work_intervals_tenant_task_time", "tenant_id", "task_id", "started_at", "id"),
        Index("ix_task_work_intervals_tenant_user_time", "tenant_id", "user_id", "started_at", "id"),
        UniqueConstraint("tenant_id", "request_id", name="uq_task_work_intervals_request"),
        Index("ix_task_work_intervals_task_ref", "task_id"),
        Index("ix_task_work_intervals_subtask_ref", "subtask_id"),
        Index("ix_task_work_intervals_user_ref", "user_id"),
        Index("ix_task_work_intervals_actor_ref", "created_by_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False)
    subtask_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("subtasks.id", ondelete="RESTRICT"), nullable=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    activity_event_id: Mapped[str] = mapped_column(String(36), ForeignKey("audit_events.id", ondelete="RESTRICT"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class TaskActivityContext(Base):
    """One personal work focus per parent; unrelated to shared workflow status."""
    __tablename__ = "task_activity_contexts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "task_id", name="uq_activity_user_parent"),
        UniqueConstraint("tenant_id", "user_id", "slot", name="uq_activity_user_slot"),
        CheckConstraint("status IN ('RUNNING','PAUSED','STOPPED','COMPLETED')", name="ck_activity_status"),
        CheckConstraint("elapsed_ms >= 0 AND version >= 1", name="ck_activity_counters"),
        CheckConstraint("(status='RUNNING' AND slot BETWEEN 1 AND 5 AND slot IS NOT NULL AND resumed_at IS NOT NULL) OR (status<>'RUNNING' AND slot IS NULL AND resumed_at IS NULL)", name="ck_activity_five_slots"),
        Index("ix_activity_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_activity_task_subtask", "task_id", "subtask_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False)
    subtask_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("subtasks.id", ondelete="RESTRICT"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    slot: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    resumed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    activity_event_id: Mapped[str] = mapped_column(String(36), ForeignKey("audit_events.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class TaskWorkCorrection(Base):
    """Immutable supersession link; original confirmed intervals are retained."""
    __tablename__ = "task_work_corrections"
    __table_args__ = (
        UniqueConstraint("original_interval_id", name="uq_work_correction_original"),
        UniqueConstraint("replacement_interval_id", name="uq_work_correction_replacement"),
        UniqueConstraint("tenant_id", "user_id", "request_id", name="uq_work_correction_request"),
        CheckConstraint("original_interval_id <> replacement_interval_id", name="ck_work_correction_distinct"),
        Index("ix_work_corrections_tenant_user", "tenant_id", "user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    original_interval_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_work_intervals.id", ondelete="RESTRICT"), nullable=False)
    replacement_interval_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_work_intervals.id", ondelete="RESTRICT"), nullable=False)
    activity_event_id: Mapped[str] = mapped_column(String(36), ForeignKey("audit_events.id", ondelete="RESTRICT"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_entity_type", "entity_type"),
        Index("ix_audit_logs_actor_id", "actor_id"),
        Index("ix_audit_logs_category", "category"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_status", "status"),
        Index("ix_audit_logs_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[AuditLogCategoryEnum] = mapped_column(
        SAEnum(
            AuditLogCategoryEnum,
            name="audit_log_category_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    entity_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    approval_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    before: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    after: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[AuditLogSourceEnum] = mapped_column(
        SAEnum(
            AuditLogSourceEnum,
            name="audit_log_source_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=AuditLogSourceEnum.MANUAL,
    )
    severity: Mapped[AuditLogSeverityEnum] = mapped_column(
        SAEnum(
            AuditLogSeverityEnum,
            name="audit_log_severity_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=AuditLogSeverityEnum.INFO,
    )
    status: Mapped[AuditLogStatusEnum] = mapped_column(
        SAEnum(
            AuditLogStatusEnum,
            name="audit_log_status_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=AuditLogStatusEnum.SUCCESS,
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trigger: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    route: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    metadata_payload: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    actor: Mapped[Optional[User]] = relationship("User", foreign_keys=[actor_id])


class AuditRetentionConfig(Base):
    __tablename__ = "audit_retention_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    retention_days: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    last_applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolCategory(Base):
    __tablename__ = "tool_categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[ToolCategoryStatusEnum] = mapped_column(
        SAEnum(
            ToolCategoryStatusEnum,
            name="tool_category_status_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ToolCategoryStatusEnum.ACTIVE,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    tools: Mapped[List["Tool"]] = relationship("Tool", back_populates="category")


class Tool(Base):
    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    website_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    preview_image_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    category_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("tool_categories.id"), nullable=True)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    pricing_type: Mapped[ToolPricingTypeEnum] = mapped_column(
        SAEnum(
            ToolPricingTypeEnum,
            name="tool_pricing_type_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ToolPricingTypeEnum.FREE,
        nullable=False,
    )
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[ToolStatusEnum] = mapped_column(
        SAEnum(
            ToolStatusEnum,
            name="tool_status_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ToolStatusEnum.PENDING,
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    approved_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    review_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    category: Mapped[Optional[ToolCategory]] = relationship("ToolCategory", back_populates="tools")
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])
    approver: Mapped[Optional["User"]] = relationship("User", foreign_keys=[approved_by])
    favorites: Mapped[List["UserFavoriteTool"]] = relationship(
        "UserFavoriteTool", back_populates="tool", cascade="all, delete-orphan"
    )


class UserFavoriteTool(Base):
    __tablename__ = "user_favorite_tools"
    __table_args__ = (
        UniqueConstraint("user_id", "tool_id", name="uq_user_favorite_tool"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tool_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user: Mapped["User"] = relationship("User")
    tool: Mapped["Tool"] = relationship("Tool", back_populates="favorites")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notification_recipient_event"),
        Index("ix_notification_inbox", "user_id", "created_at", "id",
              postgresql_where=text("dismissed_at IS NULL"), sqlite_where=text("dismissed_at IS NULL")),
        Index("ix_notification_delivery", "delivery_pending", "next_delivery_at"),
        Index("ix_notification_pending_chronology", "created_at", "id",
              postgresql_where=text("delivery_pending IS TRUE"), sqlite_where=text("delivery_pending IS TRUE")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[NotificationTypeEnum] = mapped_column(SAEnum(NotificationTypeEnum), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[Optional[NotificationEntityTypeEnum]] = mapped_column(
        SAEnum(
            NotificationEntityTypeEnum,
            name="notification_entity_type_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )
    entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    deep_link: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    related_task_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    related_reward_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    related_chat_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Additive Phase 6: legacy notifications keep null ownership/event fields.
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    alert_kind: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    delivery_pending: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    next_delivery_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="notifications")
    chat: Mapped[Optional["ChatConversation"]] = relationship("ChatConversation", back_populates="notifications")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (Index("uq_push_binding_key", "binding_key", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # Nullable for existing devices: authenticated re-enrollment binds ownership.
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    binding_key: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    device_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="push_subscriptions")


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "module", name="uq_notification_preferences_user_module"),
        CheckConstraint("near_deadline_hours > 0 AND overtime_threshold_minutes >= 0 AND (productive_capacity_hours IS NULL OR productive_capacity_hours > 0)", name="ck_notification_workload_policy"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sound_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    near_deadline_hours: Mapped[int] = mapped_column(Integer, default=24, server_default="24", nullable=False)
    productive_capacity_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    overtime_threshold_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    quiet_start: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    quiet_end: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user: Mapped[User] = relationship("User", back_populates="notification_preferences")

class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (
        Index("ix_chat_conversations_tenant_updated", "tenant_id", "updated_at"),
        Index("ix_chat_conversations_tenant_last_message", "tenant_id", "last_message_at"),
        Index("ix_chat_conversations_type", "type"),
        Index("ix_chat_conversations_team_id", "team_id"),
        Index("ix_chat_conversations_project_id", "project_id"),
        Index("ix_chat_conversations_direct_key", "tenant_id", "direct_key"),
        UniqueConstraint("tenant_id", "direct_key", name="uq_chat_conversation_direct_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    type: Mapped[ChatConversationTypeEnum] = mapped_column(SAEnum(ChatConversationTypeEnum), nullable=False)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    team_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    direct_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_by: Mapped[Optional["User"]] = relationship("User", back_populates="created_conversations")
    participants: Mapped[List["ChatParticipant"]] = relationship(
        "ChatParticipant", back_populates="conversation", cascade="all, delete-orphan"
    )
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="conversation", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )
    pinned_messages: Mapped[List["PinnedMessage"]] = relationship(
        "PinnedMessage", back_populates="conversation", cascade="all, delete-orphan"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification", back_populates="chat"
    )


class ChatParticipant(Base):
    __tablename__ = "chat_participants"
    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_chat_participant"),
        Index("ix_chat_participants_user_id", "user_id"),
        Index("ix_chat_participants_conversation_id", "conversation_id"),
        Index("ix_chat_participants_user_conversation", "user_id", "conversation_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ChatMemberRoleEnum] = mapped_column(
        SAEnum(ChatMemberRoleEnum), default=ChatMemberRoleEnum.MEMBER, nullable=False
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_read_message_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    last_read_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    conversation: Mapped["ChatConversation"] = relationship("ChatConversation", back_populates="participants")
    user: Mapped["User"] = relationship("User", back_populates="chat_participations")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_chat_messages_conversation_created_id", "conversation_id", "created_at", "id"),
        Index("ix_chat_messages_client_id", "conversation_id", "sender_id", "client_id"),
        Index("ix_chat_messages_content", "content"),
        Index("ix_chat_messages_sender_id", "sender_id"),
        Index("ix_chat_messages_reply_to", "reply_to_message_id"),
        UniqueConstraint("conversation_id", "sender_id", "client_id", name="uq_chat_message_client_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    message_type: Mapped[ChatMessageTypeEnum] = mapped_column(
        SAEnum(ChatMessageTypeEnum), default=ChatMessageTypeEnum.TEXT, nullable=False
    )
    client_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reply_to_message_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    conversation: Mapped["ChatConversation"] = relationship("ChatConversation", back_populates="messages")
    sender: Mapped["User"] = relationship("User", back_populates="chat_messages")
    reply_to: Mapped[Optional["ChatMessage"]] = relationship("ChatMessage", remote_side=[id])
    reactions: Mapped[List["MessageReaction"]] = relationship(
        "MessageReaction", back_populates="message", cascade="all, delete-orphan"
    )
    attachments: Mapped[List["MessageAttachment"]] = relationship(
        "MessageAttachment", back_populates="message", cascade="all, delete-orphan"
    )
    mentions: Mapped[List["MessageMention"]] = relationship(
        "MessageMention", back_populates="message", cascade="all, delete-orphan"
    )


class MessageReaction(Base):
    __tablename__ = "message_reactions"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", "emoji", name="uq_message_reaction"),
        Index("ix_message_reactions_message_id", "message_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    emoji: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    message: Mapped["ChatMessage"] = relationship("ChatMessage", back_populates="reactions")
    user: Mapped["User"] = relationship("User")


class MessageAttachment(Base):
    __tablename__ = "message_attachments"
    __table_args__ = (Index("ix_message_attachments_message_id", "message_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    message: Mapped["ChatMessage"] = relationship("ChatMessage", back_populates="attachments")


class PinnedMessage(Base):
    __tablename__ = "pinned_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "message_id", name="uq_pinned_message"),
        Index("ix_pinned_messages_conversation_id", "conversation_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    pinned_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    conversation: Mapped["ChatConversation"] = relationship("ChatConversation", back_populates="pinned_messages")
    message: Mapped["ChatMessage"] = relationship("ChatMessage")
    pinned_by_user: Mapped["User"] = relationship("User")


class MessageMention(Base):
    __tablename__ = "message_mentions"
    __table_args__ = (
        UniqueConstraint("message_id", "mentioned_user_id", name="uq_message_mention"),
        Index("ix_message_mentions_mentioned_user_id", "mentioned_user_id"),
    )

    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="CASCADE"), primary_key=True
    )
    mentioned_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    message: Mapped["ChatMessage"] = relationship("ChatMessage", back_populates="mentions")
    mentioned_user: Mapped["User"] = relationship("User")


class SmtpConfig(Base):
    __tablename__ = "smtp_config"
    tenant_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True, unique=True)


    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    encryption: Mapped[str] = mapped_column(String(50), default="tls", nullable=False)




class OwnerResetToken(Base):
    __tablename__ = "owner_reset_tokens"

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    otp_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    owner: Mapped["User"] = relationship("User")

class ApiConfig(Base):
    __tablename__ = "api_config"
    tenant_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True, unique=True)


    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class PointsTableConfig(Base):
    __tablename__ = "points_table_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    points_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    task_creation_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    clarity_points_per_star: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    manager_overdue_penalty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class ReleaseNotes(Base):
    __tablename__ = "release_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version_label: Mapped[str] = mapped_column(String(255), nullable=False)
    content_mode: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    details_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    css: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    js: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    updated_by: Mapped[Optional["User"]] = relationship("User")


class MultipleApiConfig(Base):
    __tablename__ = "multiple_api_configs"
    __table_args__ = (UniqueConstraint("provider", name="uq_multiple_api_config_provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    provider: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    api_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class MultipleSmtpConfig(Base):
    __tablename__ = "multiple_smtp_configs"
    tenant_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)


    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    encryption: Mapped[str] = mapped_column(String(50), default="tls", nullable=False)
    notification_types: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "notification_type", name="uq_email_template_tenant_type"),)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)


    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    notification_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class OAuthConfig(Base):
    __tablename__ = "oauth_config"
    tenant_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)


    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    client_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    client_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    redirect_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    scopes: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    n8n_integration: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class TaskTemplate(Base):
    __tablename__ = "task_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    priority: Mapped[TaskPriorityEnum] = mapped_column(
        SAEnum(TaskPriorityEnum), default=TaskPriorityEnum.MEDIUM, nullable=False
    )
    team: Mapped[str] = mapped_column(String(255), default="General", nullable=False)
    subtasks: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    attachments: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    estimated_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    featured_image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    department_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    recurrence_rule: Mapped[RecurrenceRuleEnum] = mapped_column(
        SAEnum(RecurrenceRuleEnum), default=RecurrenceRuleEnum.NONE, nullable=False
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    department: Mapped[Optional[Department]] = relationship("Department", back_populates="task_templates")
    creator: Mapped[User] = relationship("User", back_populates="task_templates")


# Add relationships to existing models
Department.task_templates: Mapped[List["TaskTemplate"]] = relationship("TaskTemplate", back_populates="department")
User.task_templates: Mapped[List["TaskTemplate"]] = relationship("TaskTemplate", back_populates="creator")


class MediaFile(Base):
    __tablename__ = "media_files"
    __table_args__ = (
        Index("ix_media_files_user_created", "user_id", "created_at"),
        Index("ix_media_files_department_created", "department_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    department_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    media_type: Mapped[MediaFileTypeEnum] = mapped_column(SAEnum(MediaFileTypeEnum), nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    crop_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[MediaFileStatusEnum] = mapped_column(
        SAEnum(MediaFileStatusEnum), default=MediaFileStatusEnum.PENDING, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    owner: Mapped["User"] = relationship(
        "User", back_populates="media_files", foreign_keys=[user_id]
    )
    department: Mapped[Optional["Department"]] = relationship("Department")


class MediaItem(Base):
    __tablename__ = "media_items"
    __table_args__ = (
        Index("ix_media_items_owner_created", "owner_id", "created_at"),
        Index("ix_media_items_category", "category"),
        Index(
            "ix_media_items_filename_trgm",
            "filename",
            postgresql_using="gin",
            postgresql_ops={"filename": "gin_trgm_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    ext: Mapped[str] = mapped_column(String(32), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category: Mapped[MediaCategoryEnum] = mapped_column(SAEnum(MediaCategoryEnum), nullable=False)
    storage_provider: Mapped[StorageProviderEnum] = mapped_column(
        SAEnum(StorageProviderEnum), nullable=False
    )
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    public_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    original_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("media_items.id", ondelete="SET NULL"), nullable=True
    )

    owner: Mapped["User"] = relationship(
        "User", back_populates="media_items", foreign_keys=[owner_id]
    )
    original: Mapped[Optional["MediaItem"]] = relationship(
        "MediaItem",
        remote_side="MediaItem.id",
        back_populates="versions",
        foreign_keys=[original_id],
    )
    versions: Mapped[List["MediaItem"]] = relationship(
        "MediaItem", back_populates="original", cascade="all, delete-orphan"
    )


class Level(Base):
    __tablename__ = "levels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    bg_image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    season_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("seasons.id", ondelete="CASCADE"), nullable=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    created_by: Mapped["User"] = relationship("User", back_populates="created_levels")
    season: Mapped[Optional["Season"]] = relationship("Season", back_populates="levels")
    nodes: Mapped[List["LevelNode"]] = relationship("LevelNode", back_populates="level", cascade="all, delete-orphan")
    edges: Mapped[List["LevelEdge"]] = relationship("LevelEdge", back_populates="level", cascade="all, delete-orphan")
    events: Mapped[List["LevelEvent"]] = relationship("LevelEvent", back_populates="level", cascade="all, delete-orphan")


class LevelNode(Base):
    __tablename__ = "level_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    level_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("levels.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[NodeTypeEnum] = mapped_column(SAEnum(NodeTypeEnum), nullable=False)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    xp_threshold: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reward_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("rewards.id", ondelete="SET NULL"), nullable=True
    )
    require_confirm: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    animation_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    level: Mapped["Level"] = relationship("Level", back_populates="nodes")
    reward: Mapped[Optional["Reward"]] = relationship("Reward", back_populates="level_nodes")
    events: Mapped[List["LevelEvent"]] = relationship("LevelEvent", back_populates="node", cascade="all, delete-orphan")
    outgoing_edges: Mapped[List["LevelEdge"]] = relationship(
        "LevelEdge",
        back_populates="source_node",
        foreign_keys="LevelEdge.from_node",
        cascade="all, delete-orphan"
    )
    incoming_edges: Mapped[List["LevelEdge"]] = relationship(
        "LevelEdge",
        back_populates="target_node",
        foreign_keys="LevelEdge.to_node",
        cascade="all, delete-orphan"
    )


class LevelEdge(Base):
    __tablename__ = "level_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    level_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("levels.id", ondelete="CASCADE"), nullable=False
    )
    from_node: Mapped[str] = mapped_column(
        String(36), ForeignKey("level_nodes.id", ondelete="CASCADE"), nullable=False
    )
    to_node: Mapped[str] = mapped_column(
        String(36), ForeignKey("level_nodes.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    level: Mapped["Level"] = relationship("Level", back_populates="edges")
    source_node: Mapped["LevelNode"] = relationship(
        "LevelNode",
        back_populates="outgoing_edges",
        foreign_keys=[from_node]
    )
    target_node: Mapped["LevelNode"] = relationship(
        "LevelNode",
        back_populates="incoming_edges",
        foreign_keys=[to_node]
    )



class LevelEvent(Base):
    __tablename__ = "level_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    level_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("levels.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("level_nodes.id", ondelete="CASCADE"), nullable=True
    )
    event_type: Mapped[EventTypeEnum] = mapped_column(SAEnum(EventTypeEnum), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    level: Mapped["Level"] = relationship("Level", back_populates="events")
    node: Mapped[Optional["LevelNode"]] = relationship("LevelNode", back_populates="events")
    user: Mapped["User"] = relationship("User", back_populates="level_events")


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    theme: Mapped[str] = mapped_column(String(255), nullable=False)
    bonus_multiplier: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    levels: Mapped[List["Level"]] = relationship("Level", back_populates="season", cascade="all, delete-orphan")
    user_progress: Mapped[List["UserProgress"]] = relationship("UserProgress", back_populates="season", cascade="all, delete-orphan")


class UserProgress(Base):
    __tablename__ = "user_progress"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    level_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("levels.id", ondelete="CASCADE"), nullable=False
    )
    season_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("seasons.id", ondelete="CASCADE"), nullable=True
    )
    current_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_points_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    level_unlocked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="user_progress")
    level: Mapped["Level"] = relationship("Level", back_populates="user_progress")
    season: Mapped[Optional["Season"]] = relationship("Season", back_populates="user_progress")


class NavigationPolicy(Base):
    __tablename__ = "navigation_policies"

    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pages: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(36), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(String(150), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    group: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


# Add relationships to existing models
User.level_events: Mapped[List["LevelEvent"]] = relationship("LevelEvent", back_populates="user", cascade="all, delete-orphan")
User.user_progress: Mapped[List["UserProgress"]] = relationship("UserProgress", back_populates="user", cascade="all, delete-orphan")
User.created_levels: Mapped[List["Level"]] = relationship("Level", back_populates="created_by", cascade="all, delete-orphan")
Level.created_by: Mapped["User"] = relationship("User", back_populates="created_levels")
Level.user_progress: Mapped[List["UserProgress"]] = relationship("UserProgress", back_populates="level", cascade="all, delete-orphan")
Reward.level_nodes: Mapped[List["LevelNode"]] = relationship("LevelNode", back_populates="reward")


def task_audit_guard_statements_v1(dialect):
    """Frozen Phase 1 DDL contract. Future changes need a new version/revision.

    Shared by the additive migration and fresh metadata installs; no I/O here.
    """
    distinct = "IS DISTINCT FROM" if dialect == "postgresql" else "IS NOT"
    def same(left, right):
        return f"NOT ({left} {distinct} {right})"
    def owner(tenant, task):
        return f"EXISTS (SELECT 1 FROM tasks t JOIN users u ON u.id=t.created_by_id WHERE t.id={task} AND u.tenant_id={tenant})"
    def member(tenant, user):
        return f"EXISTS (SELECT 1 FROM users u WHERE u.id={user} AND u.tenant_id={tenant})"
    def child(task, subtask):
        return f"({subtask} IS NULL OR EXISTS (SELECT 1 FROM subtasks s WHERE s.id={subtask} AND s.task_id={task}))"
    def activity(extra="true"):
        return "EXISTS (SELECT 1 FROM audit_events e WHERE e.id=NEW.activity_event_id AND e.audit_schema_version=2 AND e.tenant_id=NEW.tenant_id AND e.task_id=NEW.task_id AND " + same("e.subtask_id", "NEW.subtask_id") + f" AND ({extra}))"
    basic = f"{owner('NEW.tenant_id', 'NEW.task_id')} AND {child('NEW.task_id', 'NEW.subtask_id')}"
    audit_valid = f"NEW.tenant_id IS NOT NULL AND NEW.task_id IS NOT NULL AND NEW.actor_id IS NOT NULL AND {basic} AND {member('NEW.tenant_id', 'NEW.actor_id')} AND length(trim(NEW.event_type))>0 AND NEW.entity_type=CASE WHEN NEW.subtask_id IS NULL THEN 'task' ELSE 'subtask' END AND NEW.entity_id=COALESCE(NEW.subtask_id, NEW.task_id)"
    ledger_valid = f"NEW.task_id IS NOT NULL AND {basic} AND {member('NEW.tenant_id', 'NEW.user_id')} AND {activity()} AND NEW.deleted_at IS NULL AND NEW.component_type IN ('BASE','BONUS','PENALTY','ADJUSTMENT','REVERSAL') AND length(trim(NEW.policy_version))>0 AND length(trim(NEW.idempotency_key))>0 AND length(trim(NEW.reason))>0 AND (NEW.component_type<>'BONUS' OR NEW.points>=0) AND (NEW.component_type<>'PENALTY' OR NEW.points<=0) AND (NEW.subtask_id IS NULL OR EXISTS (SELECT 1 FROM subtasks s WHERE s.id=NEW.subtask_id AND s.point_policy_version=NEW.policy_version AND s.point_policy_version<>'legacy')) AND ((NEW.component_type='REVERSAL' AND NEW.reversal_of_id IS NOT NULL AND EXISTS (SELECT 1 FROM xp_ledger x WHERE x.id=NEW.reversal_of_id AND x.record_version=2 AND x.tenant_id=NEW.tenant_id AND x.user_id=NEW.user_id AND x.task_id=NEW.task_id AND {same('x.subtask_id','NEW.subtask_id')} AND x.policy_version=NEW.policy_version AND x.points=-NEW.points)) OR (NEW.component_type<>'REVERSAL' AND NEW.reversal_of_id IS NULL))"
    if dialect == "sqlite":
        ledger_valid += " AND typeof(NEW.points)='integer'"
    ledger_valid += f" AND {activity('e.event_type=NEW.event_type')}"
    positive_interval = "NEW.ended_at>NEW.started_at" if dialect == "postgresql" else "julianday(NEW.ended_at)>julianday(NEW.started_at)"
    interval_valid = f"{basic} AND {member('NEW.tenant_id','NEW.user_id')} AND {member('NEW.tenant_id','NEW.created_by_id')} AND {activity('e.actor_id=NEW.created_by_id')} AND {positive_interval} AND length(trim(NEW.request_id))>0"
    activation_time = "p.activated_at<=clock_timestamp() AND NEW.created_at>=p.activated_at" if dialect == "postgresql" else "julianday(p.activated_at)<=julianday('now') AND julianday(NEW.created_at)>=julianday(p.activated_at)"
    # Archived activation rows validate historical restores; the opt-in writer
    # separately selects ONLY the currently enabled policy for new children.
    policy_valid = f"NEW.point_policy_version='legacy' OR (NEW.created_at IS NOT NULL AND EXISTS (SELECT 1 FROM tasks t JOIN users u ON u.id=t.created_by_id JOIN task_workflow_settings p ON p.tenant_id=u.tenant_id WHERE t.id=NEW.task_id AND p.point_policy_version=NEW.point_policy_version AND {activation_time}))"
    priority_valid = "NEW.priority_override IS NULL OR NEW.priority_override IN ('LOW','MEDIUM','HIGH','URGENT')"
    actual_valid = "NEW.actual_end_at>=NEW.actual_start_at" if dialect == "postgresql" else "julianday(NEW.actual_end_at)>=julianday(NEW.actual_start_at)"
    schedule_valid = f"NEW.version>=1 AND length(trim(NEW.point_policy_version))>0 AND (NEW.planned_start_date IS NULL OR NEW.planned_end_date IS NULL OR NEW.planned_end_date>=NEW.planned_start_date) AND (NEW.actual_start_at IS NULL OR NEW.actual_end_at IS NULL OR {actual_valid})"
    guards = [
        ("activity_insert", "audit_events", "INSERT", "true", f"NEW.audit_schema_version NOT IN (1,2) OR (NEW.audit_schema_version=2 AND NOT COALESCE(({audit_valid}), false))"),
        ("activity_update", "audit_events", "UPDATE", "true", "OLD.audit_schema_version=2 OR NEW.audit_schema_version<>OLD.audit_schema_version"),
        ("activity_delete", "audit_events", "DELETE", "true", "OLD.audit_schema_version=2"),
        ("ledger_insert", "xp_ledger", "INSERT", "true", f"NEW.record_version NOT IN (1,2) OR (NEW.record_version=2 AND NOT COALESCE(({ledger_valid}), false))"),
        ("ledger_update", "xp_ledger", "UPDATE", "true", "OLD.record_version=2 OR NEW.record_version<>OLD.record_version"),
        ("ledger_delete", "xp_ledger", "DELETE", "true", "OLD.record_version=2"),
        ("interval_insert", "task_work_intervals", "INSERT", "true", f"NOT COALESCE(({interval_valid}), false)"),
        ("interval_update", "task_work_intervals", "UPDATE", "true", "true"),
        ("interval_delete", "task_work_intervals", "DELETE", "true", "true"),
        ("subtask_insert", "subtasks", "INSERT", "true", f"NOT COALESCE(({policy_valid}), false) OR NOT ({priority_valid}) OR NOT COALESCE(({schedule_valid}), false)"),
        ("subtask_update", "subtasks", "UPDATE", "true", f"NEW.point_policy_version {distinct} OLD.point_policy_version OR NOT ({priority_valid}) OR NOT COALESCE(({schedule_valid}), false) OR (NEW.task_id {distinct} OLD.task_id AND (OLD.point_policy_version<>'legacy' OR EXISTS (SELECT 1 FROM audit_events e WHERE e.subtask_id=OLD.id AND e.audit_schema_version=2)))"),
        ("task_owner", "tasks", "UPDATE", f"NEW.created_by_id {distinct} OLD.created_by_id", "EXISTS (SELECT 1 FROM audit_events e JOIN users u ON u.id=NEW.created_by_id WHERE e.task_id=OLD.id AND e.audit_schema_version=2 AND e.tenant_id<>u.tenant_id)"),
        ("user_tenant", "users", "UPDATE", f"NEW.tenant_id {distinct} OLD.tenant_id", "EXISTS (SELECT 1 FROM audit_events e WHERE e.audit_schema_version=2 AND (e.actor_id=OLD.id OR e.task_id IN (SELECT id FROM tasks WHERE created_by_id=OLD.id))) OR EXISTS (SELECT 1 FROM xp_ledger x WHERE x.record_version=2 AND x.user_id=OLD.id) OR EXISTS (SELECT 1 FROM task_work_intervals w WHERE w.user_id=OLD.id OR w.created_by_id=OLD.id)"),
        ("task_delete", "tasks", "DELETE", "true", "EXISTS (SELECT 1 FROM audit_events e WHERE e.task_id=OLD.id AND e.audit_schema_version=2) OR EXISTS (SELECT 1 FROM xp_ledger x WHERE x.task_id=OLD.id AND x.record_version=2) OR EXISTS (SELECT 1 FROM task_work_intervals w WHERE w.task_id=OLD.id)"),
        ("subtask_delete", "subtasks", "DELETE", "true", "EXISTS (SELECT 1 FROM audit_events e WHERE e.subtask_id=OLD.id AND e.audit_schema_version=2) OR EXISTS (SELECT 1 FROM xp_ledger x WHERE x.subtask_id=OLD.id AND x.record_version=2) OR EXISTS (SELECT 1 FROM task_work_intervals w WHERE w.subtask_id=OLD.id)"),
        ("user_delete", "users", "DELETE", "true", "EXISTS (SELECT 1 FROM audit_events e WHERE e.audit_schema_version=2 AND (e.actor_id=OLD.id OR e.task_id IN (SELECT id FROM tasks WHERE created_by_id=OLD.id))) OR EXISTS (SELECT 1 FROM xp_ledger x WHERE x.record_version=2 AND x.user_id=OLD.id) OR EXISTS (SELECT 1 FROM task_work_intervals w WHERE w.user_id=OLD.id OR w.created_by_id=OLD.id)"),
        ("policy_update", "task_workflow_settings", "UPDATE", "true", f"NEW.tenant_id {distinct} OLD.tenant_id OR NEW.point_policy_version {distinct} OLD.point_policy_version OR (OLD.activated_at IS NOT NULL AND NEW.activated_at {distinct} OLD.activated_at)"),
        ("policy_delete", "task_workflow_settings", "DELETE", "true", "EXISTS (SELECT 1 FROM subtasks s JOIN tasks t ON t.id=s.task_id JOIN users u ON u.id=t.created_by_id WHERE u.tenant_id=OLD.tenant_id AND s.point_policy_version=OLD.point_policy_version AND s.point_policy_version<>'legacy')"),
    ]
    # Freeze derived ownership while validating a new immutable reference.
    # Without these locks, a concurrent tenant reassignment could pass its own
    # history check before the inserting transaction becomes visible.
    insert_locks = {
        "activity_insert": ("NEW.audit_schema_version=2", ["NEW.actor_id"]),
        "ledger_insert": ("NEW.record_version=2", ["NEW.user_id"]),
        "interval_insert": ("true", ["NEW.user_id", "NEW.created_by_id"]),
        "subtask_insert": ("NEW.point_policy_version<>'legacy'", []),
    }
    statements = []
    for name, table, operation, condition, invalid in guards:
        name = "zea_" + name
        if dialect == "sqlite":
            statements.append(f"DROP TRIGGER IF EXISTS {name}")
            statements.append(f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {operation} ON {table} WHEN {condition} BEGIN SELECT CASE WHEN {invalid} THEN RAISE(ABORT, 'task audit invariant violated') END; END")
        elif dialect == "postgresql":
            locks = ""
            spec = insert_locks.get(name.removeprefix("zea_"))
            if spec:
                lock_when, user_ids = spec
                user_ids = ["(SELECT t.created_by_id FROM tasks t WHERE t.id=NEW.task_id)", *user_ids]
                locks = f"IF {lock_when} THEN PERFORM 1 FROM tasks WHERE id=NEW.task_id FOR SHARE; "
                if table != "subtasks":
                    locks += "PERFORM 1 FROM subtasks WHERE id=NEW.subtask_id FOR SHARE; "
                locks += f"PERFORM 1 FROM users WHERE id IN ({','.join(user_ids)}) ORDER BY id FOR SHARE; "
                if table == "subtasks":
                    locks += "PERFORM 1 FROM task_workflow_settings p WHERE p.point_policy_version=NEW.point_policy_version AND p.tenant_id=(SELECT u.tenant_id FROM users u JOIN tasks t ON t.created_by_id=u.id WHERE t.id=NEW.task_id) FOR SHARE; "
                locks += "END IF; "
            statements.append(f"CREATE OR REPLACE FUNCTION {name}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {locks}IF ({condition}) AND ({invalid}) THEN RAISE EXCEPTION 'task audit invariant violated' USING ERRCODE='23514'; END IF; RETURN {'OLD' if operation == 'DELETE' else 'NEW'}; END; $$")
            statements.append(f"DROP TRIGGER IF EXISTS {name} ON {table}")
            statements.append(f"CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}_guard()")
        else:
            raise RuntimeError("Task audit storage supports PostgreSQL and SQLite only")
    return statements


def normalize_workflow_created_at(target, context, *args):
    """Normalize new history on load without dirtying immutable ORM records.

    Existing writers/readers keep the legacy timestamp contract for version 1.
    """
    version = getattr(target, "audit_schema_version", getattr(target, "record_version", 1))
    value = target.created_at
    if version == 2 and value is not None:
        normalized = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        attributes.set_committed_value(target, "created_at", normalized)


event.listen(AuditEvent, "load", normalize_workflow_created_at)
event.listen(AuditEvent, "refresh", normalize_workflow_created_at)


def install_task_audit_guards(connection):
    inspector = inspect(connection)
    required = {"tasks", "users", "subtasks", "audit_events", "xp_ledger", "task_workflow_settings", "task_work_intervals"}
    if not required.issubset(inspector.get_table_names()):
        return
    if "audit_schema_version" not in {c["name"] for c in inspector.get_columns("audit_events")}:
        return
    for statement in task_audit_guard_statements_v1(connection.dialect.name):
        connection.execute(text(statement))
    if "workflow_version" in {c["name"] for c in inspector.get_columns("subtasks")}:
        from .services.task_audit_schema import task_audit_guard_statements_v2
        for statement in task_audit_guard_statements_v2(connection.dialect.name):
            connection.execute(text(statement))
    if "deleted_at" in {c["name"] for c in inspector.get_columns("subtasks")}:
        from .services.subtask_reward_schema import statements
        for statement in statements(connection.dialect.name):
            connection.execute(text(statement))
        from .services.subtask_reward_guards_v4 import statements as accounting_statements
        for statement in accounting_statements(connection.dialect.name):
            connection.execute(text(statement))


@event.listens_for(Base.metadata, "after_create")
def _task_audit_metadata_guards(metadata, connection, **kwargs):
    install_task_audit_guards(connection)
    if {"task_activity_contexts", "task_work_corrections"}.issubset(inspect(connection).get_table_names()):
        from .services.task_activity_schema import statements
        for statement in statements(connection.dialect.name):
            connection.execute(text(statement))

    if "notifications" in inspect(connection).get_table_names():
        from .services.notification_schema import statements as notification_statements
        for statement in notification_statements(connection.dialect.name):
            connection.execute(text(statement))


def _install_notification_hooks():
    from .services.workload_notifications import install_hooks
    install_hooks()


_install_notification_hooks()


