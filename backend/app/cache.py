import json
import logging
from collections.abc import Iterable
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import urlencode

try:
    import redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry
except ImportError:  # pragma: no cover
    redis = None

from .config import get_settings

_REDIS_CLIENT: Any | None = None
_WARNING_LOCK = Lock()
_last_warning = float("-inf")
log = logging.getLogger(__name__)
_CACHE_ERRORS = (redis.exceptions.RedisError,) if redis is not None else ()


def _warn_unavailable() -> None:
    global _last_warning
    with _WARNING_LOCK:
        now = monotonic()
        if now - _last_warning >= 30:
            _last_warning = now
            # Cache keys, URLs and exception bodies can contain private data.
            log.warning("Cache unavailable; using authoritative database reads")


def _get_client() -> Any | None:
    global _REDIS_CLIENT
    if redis is None:
        return None
    settings = get_settings()
    redis_url = settings.redis_url or settings.cache_redis_url
    if not redis_url:
        return None
    if _REDIS_CLIENT is None:
        _REDIS_CLIENT = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
            retry=Retry(NoBackoff(), 0),
        )
    return _REDIS_CLIENT


def _cache_prefix() -> str:
    return get_settings().cache_prefix


def get_cache_prefix() -> str:
    return _cache_prefix()


def get_redis_client() -> Any | None:
    return _get_client()


def build_cache_key(
    *,
    resource: str,
    tenant_id: str,
    user_id: str,
    path: str,
    params: Iterable[tuple[str, str]],
) -> str:
    query = urlencode(list(params), doseq=True)
    return f"{_cache_prefix()}:{resource}:tenant:{tenant_id}:user:{user_id}:path:{path}?{query}"


def tenant_prefix(*, resource: str, tenant_id: str) -> str:
    return f"{_cache_prefix()}:{resource}:tenant:{tenant_id}:"


def get_cached_json(cache_key: str) -> Any | None:
    client = _get_client()
    if client is None:
        return None
    try:
        payload = client.get(cache_key)
    except _CACHE_ERRORS:
        _warn_unavailable()
        return None
    if not payload:
        return None
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        _warn_unavailable()
        return None


def set_cached_json(cache_key: str, value: Any, *, ttl_seconds: int) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        client.setex(cache_key, ttl_seconds, json.dumps(value))
    except _CACHE_ERRORS:
        _warn_unavailable()


def invalidate_prefix(prefix: str) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        batch = []
        for key in client.scan_iter(match=f"{prefix}*", count=100):
            batch.append(key)
            if len(batch) == 100:
                client.delete(*batch)
                batch.clear()
        if batch:
            client.delete(*batch)
    except _CACHE_ERRORS:
        _warn_unavailable()
