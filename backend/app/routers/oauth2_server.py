"""Legacy OAuth password endpoint; uses the same durable authentication authority."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import verify_password
from ..database import get_db
from ..models import User, UserStatusEnum
from ..services.auth_sessions import issue_api

router = APIRouter(prefix="/oauth2", tags=["oauth2"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


@router.post("/token", response_model=TokenResponse)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == form_data.username).with_for_update()
                     .execution_options(populate_existing=True))
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(401, "Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})
    if user.status != UserStatusEnum.ACTIVE:
        raise HTTPException(401, "Invalid or expired session")
    token, _ = issue_api(db, user, minutes=60, scopes=[])
    db.commit()
    return {"access_token": token, "token_type": "bearer"}
