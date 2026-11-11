"""Authenticated forwarding of the existing support form to its fixed webhook."""
from datetime import datetime
from typing import Literal
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from .. import models
from ..database import get_db
from ..dependencies import get_current_active_user
from ..services.navigation import enforce_pages

router = APIRouter(prefix="/support", tags=["support"])
WEBHOOK_URL = "https://n8n.urlfactory.website/webhook/task-support"


class SupportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=255)
    email: str = Field(min_length=1, max_length=320)
    employerId: str | None = Field(default=None, max_length=255)
    subject: str = Field(min_length=1, max_length=1000)
    category: Literal["Bug", "Feature Request", "Access Issue", "Other"]
    priority: Literal["Low", "Medium", "High", "Critical"]
    description: str = Field(min_length=1, max_length=100_000)
    attachment: str | None = Field(default=None, max_length=14_000_000)
    fileType: Literal["image", "pdf"] | None = None
    submittedAt: datetime
    user_id: str | None = None


@router.post("")
def submit_support(payload: SupportRequest, db: Session = Depends(get_db), user: models.User = Depends(get_current_active_user)):
    enforce_pages(db, user, ("settings.support",))
    body = payload.model_dump(mode="json")
    body["user_id"] = str(user.id)
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.post(WEBHOOK_URL, json=body)
    except httpx.HTTPError:
        raise HTTPException(502, "Support service could not be reached.") from None
    if not response.is_success:
        raise HTTPException(502, "Support service could not accept the request.")
    return {"status": "submitted"}
