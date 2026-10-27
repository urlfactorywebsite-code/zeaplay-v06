from fastapi import APIRouter, Depends
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_active_user, get_current_owner


router = APIRouter(prefix="/updates", tags=["updates"])

DEFAULT_VERSION_LABEL = "2026 Zea.Play V1.1.2"
DEFAULT_DETAILS = "Add release notes here to share updates with the team."


def _ensure_release_notes_table(db: Session) -> None:
    inspector = inspect(db.bind)
    if "release_notes" not in inspector.get_table_names():
        models.ReleaseNotes.__table__.create(bind=db.bind, checkfirst=True)


def _get_or_create_release_notes(db: Session) -> models.ReleaseNotes:
    _ensure_release_notes_table(db)
    notes = db.get(models.ReleaseNotes, 1)
    if notes:
        return notes
    notes = models.ReleaseNotes(
        id=1,
        version_label=DEFAULT_VERSION_LABEL,
        content_mode="text",
        details_text=DEFAULT_DETAILS,
        html=None,
        css=None,
        js=None,
    )
    db.add(notes)
    db.commit()
    db.refresh(notes)
    return notes


@router.get("/latest", response_model=schemas.ReleaseNotesRead)
def get_release_notes(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_active_user),
) -> models.ReleaseNotes:
    return _get_or_create_release_notes(db)


@router.put("/latest", response_model=schemas.ReleaseNotesRead)
def update_release_notes(
    payload: schemas.ReleaseNotesUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_owner),
) -> models.ReleaseNotes:
    notes = _get_or_create_release_notes(db)
    update_data = payload.model_dump(exclude_unset=True)
    if update_data:
        for key, value in update_data.items():
            setattr(notes, key, value)
        notes.updated_by_id = current_user.id
        db.commit()
        db.refresh(notes)
    return notes
