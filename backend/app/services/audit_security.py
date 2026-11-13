"""Event-time attribution; unknown historical ownership is never inferred."""
from contextvars import ContextVar
import re
from sqlalchemy import inspect, text

principal = ContextVar("audit_principal", default=None)


def bind_principal(user):
    principal.set((str(user.id), user.tenant_id))


def event_tenant(entry):
    if entry.tenant_id is not None:
        return entry.tenant_id
    actor = principal.get()
    return actor[1] if actor and str(entry.actor_id) == actor[0] else None


_sensitive = re.compile(r"password|passwd|secret|token|authorization|cookie|credential|api.?key|private.?key", re.I)
_inline = re.compile(r"(?i)(bearer\s+)[^\s,;]+|eyJ[\w-]+\.[\w-]+\.[\w-]+")


def redact(value):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if _sensitive.search(str(key)) else redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _inline.sub("[REDACTED]", value)
    return value


def audit_read(row, user):
    from ..schemas import AuditLogRead
    item = AuditLogRead.model_validate(row)
    # Free-form legacy values have no trustworthy field schema. Preserve them in
    # storage, but never export a potentially credential-bearing string.
    for field in ("old_value", "new_value"):
        if getattr(item, field) is not None:
            setattr(item, field, "[REDACTED]")
    for field in ("before", "after", "metadata", "reason", "user_agent"):
        setattr(item, field, redact(getattr(item, field)))
    if row.actor and row.actor.tenant_id != user.tenant_id:
        item.actor = None
    return item


def require_audit_schema(engine):
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Audit attribution requires migrated PostgreSQL")
    with engine.connect() as connection:
        inspector = inspect(connection)
        if (not inspector.has_table("audit_logs")
            or "tenant_id" not in {column["name"] for column in inspector.get_columns("audit_logs")}
            or not connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE "
                "tgrelid = 'audit_logs'::regclass AND tgname = 'audit_tenant_immutable' "
                "AND tgenabled IN ('O', 'A'))"))):
            raise RuntimeError("Apply Alembic m3c5e7f9a1d3 before starting this release")
