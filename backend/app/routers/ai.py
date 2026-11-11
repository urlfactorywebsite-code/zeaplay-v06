"""Authenticated AI gateway. Provider credentials never leave the backend."""
import random
import re
import time
from threading import Lock
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..config import get_settings
from ..database import get_db
from ..dependencies import get_current_active_user

router = APIRouter(prefix="/ai", tags=["ai"])
_usage: dict[str, tuple[int, int, float]] = {}
_lock = Lock()


class GenerateRequest(BaseModel):
    model: str = Field(pattern=r"^[a-zA-Z0-9._-]+$", max_length=100)
    contents: str = Field(min_length=1, max_length=500_000)
    config: dict[str, Any] = Field(default_factory=dict)


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    sessionId: str | None = Field(default=None, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)


def _keys(db: Session, tenant_id: str) -> list[str]:
    configured = re.split(r"[,;\s]+", get_settings().gemini_api_keys.strip())
    keys = [key for key in configured if key]
    if not keys:
        config = db.query(models.ApiConfig).filter(models.ApiConfig.tenant_id == str(tenant_id)).first()
        if config and config.api_key:
            keys = [config.api_key]
    return list(dict.fromkeys(keys))


def _post(url: str, body: dict, key: str | None = None) -> httpx.Response:
    try:
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            return client.post(url, json=body, headers={"x-goog-api-key": key} if key else {})
    except httpx.HTTPError:
        raise HTTPException(502, "AI service could not be reached.") from None


def _request(url: str, body: dict, keys: list[str], webhook: bool = False) -> httpx.Response:
    if not keys:
        if webhook:
            response = _post(url, body)
            if response.is_success:
                return response
            raise HTTPException(502, "AI service request failed.")
        raise HTTPException(503, "Configure a provider key on the server or in API configuration.")
    candidates = random.sample(keys, len(keys))
    today = int(time.time() // 86400)
    for key in candidates:
        with _lock:
            day, count, cooldown = _usage.get(key, (today, 0, 0))
            count = count if day == today else 0
            if cooldown > time.time() or count >= get_settings().gemini_daily_limit:
                continue
            _usage[key] = (today, count + 1, cooldown)
        payload = {**body, "apiKey": key, "geminiApiKey": key} if webhook else body
        response = _post(url, payload, None if webhook else key)
        if response.is_success:
            return response
        if response.status_code == 429:
            with _lock:
                _usage[key] = (today, count + 1, time.time() + 86400)
            continue
        if response.status_code in (401, 403):
            continue
        raise HTTPException(502, "AI service request failed.")
    raise HTTPException(429, "AI provider keys are unavailable or have reached their limits.")


def _reply(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, list):
        return next((text for item in payload if (text := _reply(item))), "")
    if isinstance(payload, dict):
        return next((text for key in ("reply", "message", "output", "text", "response", "data") if (text := _reply(payload.get(key)))), "")
    return ""


def _redact(text: str, keys: list[str]) -> str:
    for key in keys:
        text = text.replace(key, "[REDACTED_SECRET]")
    return text


@router.post("/generate")
def generate(payload: GenerateRequest, db: Session = Depends(get_db), user: models.User = Depends(get_current_active_user)):
    keys = _keys(db, str(user.tenant_id))
    generation = {key: value for key, value in payload.config.items() if key in {"temperature", "responseMimeType", "responseSchema", "topP", "topK", "maxOutputTokens"}}
    body: dict[str, Any] = {"contents": [{"role": "user", "parts": [{"text": payload.contents}]}], "generationConfig": generation}
    instruction = payload.config.get("systemInstruction")
    if isinstance(instruction, str):
        body["systemInstruction"] = {"parts": [{"text": instruction}]}
    response = _request(f"https://generativelanguage.googleapis.com/v1beta/models/{payload.model}:generateContent", body, keys)
    try:
        data = response.json()
        text = "".join(part.get("text", "") for candidate in data.get("candidates", [])[:1] for part in candidate.get("content", {}).get("parts", []))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(502, "AI service returned an invalid response.") from None
    return {"text": _redact(text, keys)}


@router.post("/message")
def message(payload: MessageRequest, db: Session = Depends(get_db), user: models.User = Depends(get_current_active_user)):
    keys = _keys(db, str(user.tenant_id))
    # The destination is server configuration, never a client-supplied URL.
    body = {**payload.payload, "message": payload.message, "sessionId": payload.sessionId}
    body.pop("apiKey", None)
    body.pop("geminiApiKey", None)
    response = _request(get_settings().ai_webhook_url, body, keys, webhook=True)
    try:
        text = _reply(response.json())
    except ValueError:
        text = response.text
    return {"reply": _redact(text, keys)}
