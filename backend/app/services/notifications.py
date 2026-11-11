"""Notification helper utilities."""

from typing import Optional

from sqlalchemy.orm import Session

from .. import models
from .notification_dispatcher import dispatch_notification


def create_notification(
    db: Session,
    *,
    user_id: str,
    notification_type: models.NotificationTypeEnum,
    message: str,
    title: Optional[str] = None,
    body: Optional[str] = None,
    entity_type: Optional[models.NotificationEntityTypeEnum] = None,
    entity_id: Optional[str] = None,
    deep_link: Optional[str] = None,
    related_task_id: Optional[str] = None,
    related_reward_id: Optional[str] = None,
    related_chat_id: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> Optional[models.Notification]:
    # Task mutations, their legacy watcher loop and the transactional hook all
    # share one durable recipient/event key instead of creating parallel alerts.
    task_id = related_task_id or (entity_id if entity_type == models.NotificationEntityTypeEnum.TASK else None)
    if task_id and notification_type in {
        models.NotificationTypeEnum.TASK_CREATED, models.NotificationTypeEnum.TASK_ASSIGNED,
        models.NotificationTypeEnum.TASK_UPDATED, models.NotificationTypeEnum.TASK_COMPLETED,
        models.NotificationTypeEnum.TASK_OVERDUE, models.NotificationTypeEnum.TASK_DELETED,
    }:
        from .workload_notifications import emit, task_notice
        task = db.get(models.Task, task_id)
        if task:
            if notification_type == models.NotificationTypeEnum.TASK_OVERDUE:
                from .task_activity import deadline
                from zoneinfo import ZoneInfo
                due = deadline(task, None, ZoneInfo("UTC"))
                emit(db, task=task, kind="task_overdue", source=f"due:{task.id}:None:{due.isoformat() if due else ''}", message=f"Task '{task.title}' is overdue.")
            elif notification_type == models.NotificationTypeEnum.TASK_DELETED:
                task_notice(db, task, "task_deleted", message)
            else:
                db.flush()
                # Repeated identical PATCH requests are not new task events.
                if task.id in db.info.get("phase6_task_kinds", {}):
                    task_notice(db, task, "assignment" if notification_type == models.NotificationTypeEnum.TASK_ASSIGNED else "task_updated", message)
            return None
    return dispatch_notification(
        db,
        user_id=user_id,
        notification_type=notification_type,
        message=message,
        title=title,
        body=body,
        entity_type=entity_type,
        entity_id=entity_id,
        deep_link=deep_link,
        related_task_id=related_task_id,
        related_reward_id=related_reward_id,
        related_chat_id=related_chat_id,
        actor_id=actor_id,
    )
