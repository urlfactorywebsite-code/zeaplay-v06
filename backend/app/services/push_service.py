from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

from fastapi import HTTPException
from pywebpush import WebPushException, webpush
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import models
from ..config import get_settings

logger = logging.getLogger(__name__)


def _read_env(key: str) -> str | None:
    env_value = os.getenv(key) or os.getenv(f"VEE_{key}")
    if env_value:
        return env_value

    return getattr(get_settings(), key.lower(), None)


def get_vapid_public_key() -> str | None:
    return _read_env("VAPID_PUBLIC_KEY")


def _get_vapid_private_key() -> str | None:
    return _read_env("VAPID_PRIVATE_KEY")


def _get_vapid_subject() -> str | None:
    return _read_env("VAPID_SUBJECT")


def save_subscription(
    db: Session,
    *,
    user_id: str,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None = None,
    device_label: str | None = None,
    binding_protocol: str | None = None,
) -> models.PushSubscription:
    # Serialize enrollment even when an endpoint has no row yet. Ownership
    # changes must not race a queued delivery from the previous account.
    if db.bind.dialect.name == "postgresql":
        lock = int.from_bytes(
            hashlib.sha256(endpoint.encode()).digest()[:8], "big", signed=True
        )
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    elif (
        db.bind.dialect.name == "sqlite"
        and not db.connection().connection.driver_connection.in_transaction
    ):
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    user = db.get(models.User, user_id)
    if not user or user.status != models.UserStatusEnum.ACTIVE:
        raise HTTPException(403, "Active subscription owner required")
    existing = db.execute(
        select(models.PushSubscription)
        .where(models.PushSubscription.endpoint == endpoint)
        .with_for_update()
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing:
        changed_owner = (
            existing.user_id != user_id or existing.tenant_id != user.tenant_id
        )
        if changed_owner and not (
            hmac.compare_digest(existing.p256dh, p256dh)
            and hmac.compare_digest(existing.auth, auth)
        ):
            raise HTTPException(403, "Subscription ownership could not be verified")
        if binding_protocol == "user-v1":
            if changed_owner or not existing.binding_key:
                existing.binding_key = str(uuid.uuid4())
        else:
            existing.binding_key = None
        existing.tenant_id = user.tenant_id
        existing.user_id = user_id
        existing.p256dh = p256dh
        existing.auth = auth
        existing.user_agent = user_agent
        existing.device_label = device_label
        existing.revoked_at = None
        existing.last_seen_at = now
        return existing

    subscription = models.PushSubscription(
        user_id=user_id,
        tenant_id=user.tenant_id,
        binding_key=str(uuid.uuid4()) if binding_protocol == "user-v1" else None,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        user_agent=user_agent,
        device_label=device_label,
        created_at=now,
        last_seen_at=now,
    )
    db.add(subscription)
    return subscription


def revoke_subscription(db: Session, *, endpoint: str, user_id: str) -> bool:
    subscription = db.execute(
        select(models.PushSubscription)
        .where(
            models.PushSubscription.endpoint == endpoint,
            models.PushSubscription.user_id == user_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if not subscription:
        return False
    subscription.revoked_at = datetime.now(timezone.utc)
    return True


def send_push(
    db: Session,
    *,
    user_ids: Iterable[str],
    payload: dict,
    retry_failures: bool = False,
    attempt: int = 0,
) -> int:
    public_key = get_vapid_public_key()
    private_key = _get_vapid_private_key()
    subject = _get_vapid_subject()
    if not public_key or not private_key or not subject:
        logger.warning("Push delivery skipped: VAPID configuration is incomplete")
        return 0

    recipients = list({user_id for user_id in user_ids if user_id})
    if not recipients:
        logger.info("Push delivery skipped: no recipient user ids")
        return 0

    subscriptions = (
        db.execute(
            select(models.PushSubscription)
            .join(models.User)
            .where(
                models.PushSubscription.user_id.in_(recipients),
                models.PushSubscription.revoked_at.is_(None),
                models.PushSubscription.binding_key.is_not(None),
                models.PushSubscription.tenant_id == models.User.tenant_id,
                models.User.status == models.UserStatusEnum.ACTIVE,
            )
            .with_for_update(of=models.PushSubscription)
        )
        .scalars()
        .all()
    )

    if not subscriptions:
        logger.info("Push delivery skipped: no active subscriptions for recipients")
        return 0

    if retry_failures:
        # Resume the bounded fanout at a different device on each retry. A
        # repeatedly timing-out endpoint cannot starve the owner's other devices.
        subscriptions.sort(key=lambda subscription: subscription.id)
        offset = attempt % len(subscriptions)
        subscriptions = subscriptions[offset:] + subscriptions[:offset]

    delivered = 0
    started = time.monotonic()
    now = datetime.now(timezone.utc)
    failure = None
    for subscription in subscriptions:
        if retry_failures and time.monotonic() - started >= 3:
            raise TimeoutError("Push delivery time budget exceeded")
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=json.dumps({**payload, "binding_key": subscription.binding_key}),
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
                timeout=3 if retry_failures else 10,
            )
            subscription.last_seen_at = now
            delivered += 1
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            logger.warning(
                "Push delivery failed for subscription %s: status=%s",
                subscription.id,
                status,
            )
            if status in {404, 410}:
                subscription.revoked_at = now
            elif retry_failures:
                failure = exc
        except Exception as exc:
            if not retry_failures:
                raise
            failure = exc
    if failure is not None:
        raise failure
    return delivered
