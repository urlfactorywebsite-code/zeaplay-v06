"""Only fixed, public-safe messages may cross the protocol boundary."""

MESSAGES = {
    "AUTH_REQUIRED": "Authenticated request authority is required or has expired.",
    "AUTH_DENIED": "The identity or grant is inactive, revoked, or lacks permission.",
    "NOT_FOUND": "Task not found or not visible to the current identity.",
    "INVALID_ARGUMENTS": "Arguments do not match the bounded tool schema.",
    "TIMEOUT": "The upstream operation exceeded its deadline.",
    "UPSTREAM_UNAVAILABLE": "The upstream is unavailable.",
    "UPSTREAM_INVALID": "The upstream returned an invalid response.",
    "CONFLICT": "The upstream state changed; retry after checking current state.",
    "OUTPUT_LIMIT": "The result exceeds the output limit; request a smaller page.",
    "INTERNAL_ERROR": "The prototype could not complete the request.",
}


class SafeError(Exception):
    def __init__(self, code: str):
        if code not in MESSAGES:
            raise ValueError("Unregistered error code")
        self.code = code
        super().__init__(MESSAGES[code])
