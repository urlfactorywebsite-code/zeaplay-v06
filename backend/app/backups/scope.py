"""Workspace ownership for the legacy schema, including tables without tenant keys.

Required relationships form an acyclic ownership graph. Shared reference/configuration
tables are explicit; new datasets cannot silently become globally readable.
"""

import uuid
from functools import lru_cache

from sqlalchemy import Uuid, and_, case, false, or_, select, true

from ..database import Base
from .registry import FIELDS, references

SHARED = {
    "departments",
    "kanban_columns",
    "achievements",
    "badges",
    "badge_rules",
    "reward_icons",
    "rewards",
    "audit_retention_config",
    "tool_categories",
    "points_table_config",
    "release_notes",
    "seasons",
    "feature_flags",
}
ACTOR_OWNED = {"reward_logs", "audit_events", "audit_logs"}


@lru_cache(maxsize=512)
def predicate(name, tenant_id):
    table = Base.metadata.tables[name]
    conditions = []
    if "tenant_id" in table.c:
        column = table.c.tenant_id
        tenant = (
            uuid.UUID(str(tenant_id))
            if isinstance(column.type, Uuid)
            else str(tenant_id)
        )
        if name == "audit_events":
            # Historical events have no tenant column value. Preserve their
            # existing actor-derived scope; version 2 always requires its key.
            conditions.append(or_(
                column == tenant,
                and_(table.c.audit_schema_version == 1, column.is_(None)),
            ))
        else:
            conditions.append(column == tenant)
    if name in ACTOR_OWNED:
        conditions.append(
            visible_reference(
                table.c.actor_id, Base.metadata.tables["users"], "id", tenant_id
            )
        )
    required = [
        (field, target, column)
        for field, target, column in references(table)
        if not table.c[field].nullable
    ]
    for field, target, column in required:
        conditions.append(visible_reference(table.c[field], target, column, tenant_id))
    if not conditions and name not in SHARED:
        # Fail closed if a dataset without an ownership policy is registered.
        return false()
    return and_(*conditions) if conditions else true()


def visible_reference(value, target, column, tenant_id):
    return value.in_(
        select(target.c[column])
        .where(predicate(target.name, str(tenant_id)))
        .correlate(None)
    )


def columns(table, tenant_id):
    """Drop optional references to another workspace, retaining the owned record."""
    optional = {
        field: (target, column)
        for field, target, column in references(table)
        if table.c[field].nullable
    }
    result = []
    for field in FIELDS[table.name].split():
        value = table.c[field]
        if field in optional:
            target, column = optional[field]
            value = case(
                (visible_reference(value, target, column, tenant_id), value), else_=None
            )
        result.append(value.label(field))
    return result
