"""Offline runtime guard and conservative output/log sanitization."""

import json
import logging
import re
import sys

_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
# These opaque credentials have an exact prefix and 43-character secret. They
# remain credentials when pasted next to letters, punctuation or other text.
_OAUTH = re.compile(r'mcp_(?:at|rt|dt)\.[A-Za-z0-9_-]{43}')
_BEARER = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_ASSIGNMENT = re.compile(
    r"""(?i)(["']?\b(?:password|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)["']?\s*[:=]\s*)"""
    r"""(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]+)"""
)


def redact_text(value: str) -> str:
    return _ASSIGNMENT.sub(
        r"\1[REDACTED]",
        _BEARER.sub("Bearer [REDACTED]", _OAUTH.sub('[REDACTED_TOKEN]', _JWT.sub("[REDACTED_TOKEN]", value))),
    )


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Never render raw SDK exceptions, arguments, upstream bodies or prompts.
        data = record.msg if isinstance(record.msg, dict) else {"event": "sdk_event"}
        allowed = {
            "event",
            "correlation_id",
            "tool",
            "outcome",
            "duration_ms",
            "mock",
            "ready",
        }
        safe = {
            key: redact_text(value) if isinstance(value, str) else value
            for key, value in data.items()
            if key in allowed
        }
        return json.dumps({"level": record.levelname, **safe}, separators=(",", ":"))


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("mcp").setLevel(logging.CRITICAL)


def install_offline_guard() -> None:
    """Install after the event loop's private wake-up pair has been created.

    No DNS, connect, bind/listen, datagrams, DB connection or child execution is
    needed by a running stdio fixture service. This is defense in depth, not an
    OS sandbox for hostile Python code or an authenticated security boundary.
    """
    blocked = {
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyaddr",
        "socket.connect",
        "socket.bind",
        "socket.sendto",
        "socket.sendmsg",
        "sqlite3.connect",
        "subprocess.Popen",
        "os.system",
    }

    def guard(event: str, args: tuple) -> None:
        if event in blocked:
            raise PermissionError("Offline prototype operation denied")
        if event == "import" and str(args[0]).split(".")[0] in {
            "app",
            "sqlalchemy",
            "psycopg",
            "psycopg2",
            "redis",
        }:
            raise ImportError(
                "Application/database imports are forbidden in the prototype"
            )

    sys.addaudithook(guard)
