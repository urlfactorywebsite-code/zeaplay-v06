"""Future authorization seam. Fixtures are not an authentication system."""

from dataclasses import dataclass
from typing import Protocol

from .errors import SafeError


@dataclass(frozen=True)
class AuthorizationContext:
    user_id: str
    tenant_id: str
    client_id: str
    grant_id: str
    scopes: frozenset[str]
    role: str
    department_id: str | None = None
    active: bool = True
    revoked: bool = False
    policy_revision: str = "fixture-v1"


class AuthorizationProvider(Protocol):
    def require(self, scope: str) -> AuthorizationContext: ...
    def ensure_current(self, context: AuthorizationContext, scope: str) -> None: ...
    def can_read_task(self, context: AuthorizationContext, task: dict) -> bool: ...


class FixtureAuthorization:
    """Local launch configuration selects one frozen synthetic principal."""

    def __init__(self, context: AuthorizationContext | None):
        self.context = context

    def require(self, scope: str) -> AuthorizationContext:
        current = self.context
        if current is None:
            raise SafeError("AUTH_REQUIRED")
        if not current.active or current.revoked or scope not in current.scopes:
            raise SafeError("AUTH_DENIED")
        return current

    def ensure_current(self, context: AuthorizationContext, scope: str) -> None:
        if self.require(scope) != context:
            raise SafeError("AUTH_DENIED")

    def can_read_task(self, context: AuthorizationContext, task: dict) -> bool:
        if task["tenant_id"] != context.tenant_id:
            return False
        if context.role in {"owner", "admin"}:
            return True
        if context.user_id in (
            task["created_by_id"],
            task["assigned_to_id"],
            *task["follower_ids"],
        ):
            return True
        return bool(
            context.role == "manager"
            and context.department_id
            and context.department_id == task["assignee_department_id"]
        )
