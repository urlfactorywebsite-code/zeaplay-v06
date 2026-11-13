"""Request-local authority; only a trusted transport/broker can bind it."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from .auth import AuthorizationContext
from .errors import SafeError


@dataclass(eq=False)
class CredentialBinding:
    context: AuthorizationContext
    credential: str = field(repr=False)
    revoked: bool = False
    allowed_tools: frozenset[str] | None = None


@dataclass
class _Request:
    binding: CredentialBinding
    visible_ids: set[str] = field(default_factory=set)


class RequestAuthorization:
    """Never stores a process-wide current user or accepts identity from tool input.

    The REST backend is the canonical resource-policy authority. Only IDs from
    validated successful responses under this exact binding are attested here;
    fixture RBAC is deliberately not substituted for backend task/group rules.
    """

    def __init__(self):
        self._request: ContextVar[_Request | None] = ContextVar("zea_request", default=None)

    @contextmanager
    def bind(self, binding: CredentialBinding | None):
        token = self._request.set(_Request(binding) if binding else None)
        try:
            yield
        finally:
            self._request.reset(token)

    def require(self, scope: str) -> AuthorizationContext:
        current = self._request.get()
        if current is None:
            raise SafeError("AUTH_REQUIRED")
        binding = current.binding
        context = binding.context
        if binding.revoked or context.revoked or not context.active or scope not in context.scopes:
            raise SafeError("AUTH_DENIED")
        return context

    def binding(self, context: AuthorizationContext) -> CredentialBinding:
        current = self._request.get()
        if current is None or current.binding.context is not context:
            raise SafeError("AUTH_REQUIRED")
        self.require("tasks:read" if "tasks:read" in context.scopes else "workload:read")
        return current.binding

    def ensure_current(self, context: AuthorizationContext, scope: str) -> None:
        if self.require(scope) is not context:
            raise SafeError("AUTH_DENIED")

    def attest(self, context: AuthorizationContext, ids: list[str]) -> None:
        self.binding(context)
        self._request.get().visible_ids.update(ids)

    def can_read_task(self, context: AuthorizationContext, task: dict) -> bool:
        self.binding(context)
        return task.get("id") in self._request.get().visible_ids
