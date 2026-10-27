from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_active_user
from ..integrations import trigger_n8n_event
from ..services import notifications as notification_service
from ..services.badge_engine import BadgeEvent, process_badge_event

router = APIRouter(prefix="/comments", tags=["comments"])


def _get_task(db: Session, task_id: str) -> models.Task:
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _ensure_comment_access(task: models.Task, user: models.User) -> None:
    if user.role in {models.RoleEnum.ADMIN, models.RoleEnum.MANAGER, models.RoleEnum.OWNER}:
        return
    if task.created_by_id != user.id and task.assigned_to_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot access comments for this task")


@router.get("/task/{task_id}", response_model=List[schemas.CommentRead])
def list_comments_for_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> List[schemas.CommentRead]:
    task = _get_task(db, task_id)
    _ensure_comment_access(task, current_user)

    stmt = (
        select(models.Comment)
        .where(models.Comment.task_id == task_id)
        .order_by(models.Comment.created_at.desc())
    )
    return db.execute(stmt).scalars().all()


@router.post("", response_model=schemas.CommentRead, status_code=status.HTTP_201_CREATED)
def create_comment(
    payload: schemas.CommentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> schemas.CommentRead:
    task = _get_task(db, payload.task_id)

    if current_user.role not in {models.RoleEnum.ADMIN, models.RoleEnum.MANAGER, models.RoleEnum.OWNER} and payload.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only comment as yourself")

    _ensure_comment_access(task, current_user)

    comment = models.Comment(task_id=payload.task_id, user_id=payload.user_id, content=payload.content)
    db.add(comment)

    commenter = db.get(models.User, payload.user_id)
    commenter_name = commenter.name if commenter else "Someone"
    recipient_ids = {task.assigned_to_id, task.created_by_id}
    recipient_ids.discard(None)
    if payload.user_id in recipient_ids:
        recipient_ids.remove(payload.user_id)
    for recipient_id in recipient_ids:
        notification_service.create_notification(
            db,
            user_id=recipient_id,
            actor_id=str(current_user.id),
            notification_type=models.NotificationTypeEnum.COMMENT_ADDED,
            message=f"{commenter_name} commented on: '{task.title}'.",
            title="New comment",
            body=payload.content,
            entity_type=models.NotificationEntityTypeEnum.TASK,
            entity_id=task.id,
            deep_link=f"/tasks/{task.id}",
            related_task_id=task.id,
        )

    process_badge_event(
        db,
        event=BadgeEvent(
            entity="comment",
            event="created",
            actor_id=current_user.id,
            assigned_to_id=task.assigned_to_id,
            created_by_id=payload.user_id,
            priority=task.priority.value,
        ),
    )

    db.commit()
    db.refresh(comment)

    background_tasks.add_task(
        trigger_n8n_event,
        "comment.created",
        {
            "comment": schemas.CommentRead.model_validate(comment).model_dump(),
            "taskId": task.id,
        },
    )

    return comment


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> None:
    comment = db.get(models.Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

    task = _get_task(db, comment.task_id)
    if current_user.role not in {models.RoleEnum.ADMIN, models.RoleEnum.MANAGER, models.RoleEnum.OWNER} and comment.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own comments")
    _ensure_comment_access(task, current_user)

    comment_snapshot = schemas.CommentRead.model_validate(comment).model_dump()

    process_badge_event(
        db,
        event=BadgeEvent(
            entity="comment",
            event="deleted",
            actor_id=current_user.id,
            assigned_to_id=task.assigned_to_id,
            created_by_id=comment.user_id,
            priority=task.priority.value,
        ),
    )
    db.delete(comment)
    db.commit()

    background_tasks.add_task(
        trigger_n8n_event,
        "comment.deleted",
        {"commentId": comment_id, "taskId": task.id, "comment": comment_snapshot},
    )
