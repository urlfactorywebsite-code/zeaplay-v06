"""Authentication helpers for password hashing and JWT handling."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from jose import JWTError, jwt
from pydantic import ValidationError
from passlib.context import CryptContext

from fastapi.security import OAuth2PasswordBearer

from .config import get_settings
from .schemas import TokenPayload


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
settings = get_settings()

PRESENCE_TOKEN_TYPE = "presence"
PRESENCE_TOKEN_AUDIENCE = "zeaplay-presence"
PRESENCE_TOKEN_ISSUER = "zeaplay"
PRESENCE_TOKEN_MINUTES = 60


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a raw password."""
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(password, hashed_password)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _create_token(
    subject: str,
    expires_delta: timedelta,
    secret_key: str,
    token_type: str,
    extra_claims: Optional[Dict[str, object]] = None,
) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode: Dict[str, object] = {"sub": subject, "exp": expire, "token_type": token_type}
    if extra_claims:
        to_encode.update(extra_claims)
    return jwt.encode(to_encode, secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(
    subject: str,
    expires_minutes: Optional[int] = None,
    scopes: Optional[List[str]] = None,
    extra_claims: Optional[Dict[str, object]] = None,
) -> str:
    expires = expires_minutes or settings.access_token_expire_minutes
    claims: Dict[str, object] = {}
    if scopes:
        claims["scopes"] = scopes
    if extra_claims:
        claims.update(extra_claims)
    return _create_token(
        subject,
        expires_delta=timedelta(minutes=expires),
        secret_key=settings.jwt_secret_key,
        token_type="access",
        extra_claims=claims or None,
    )


def create_refresh_token(
    subject: str,
    expires_minutes: Optional[int] = None,
    extra_claims: Optional[Dict[str, object]] = None,
) -> str:
    expires = expires_minutes or settings.refresh_token_expire_minutes
    return _create_token(
        subject,
        expires_delta=timedelta(minutes=expires),
        secret_key=settings.jwt_refresh_secret_key,
        token_type="refresh",
        extra_claims=extra_claims,
    )


def create_presence_token(subject: str, *, tenant_id: str, roles: List[str],
                          sid: str, auth_epoch: int, jti: str, expires_at: datetime) -> str:
    """Issue the presence-only profile; never accepted by REST/refresh decoders."""
    issued_at = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": subject, "tenant_id": tenant_id, "roles": roles,
         "scopes": ["presence"], "token_type": PRESENCE_TOKEN_TYPE,
         "iss": PRESENCE_TOKEN_ISSUER, "aud": PRESENCE_TOKEN_AUDIENCE,
         "sid": sid, "auth_epoch": auth_epoch, "jti": jti,
         "iat": issued_at, "exp": min(expires_at, issued_at + timedelta(minutes=PRESENCE_TOKEN_MINUTES))},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm,
    )


def decode_presence_claims(token: str) -> dict:
    """Same dedicated claim contract as presence-server/src/auth.js."""
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm],
                            audience=PRESENCE_TOKEN_AUDIENCE, issuer=PRESENCE_TOKEN_ISSUER,
                            options={"require_exp": True, "require_iat": True})
        header = jwt.get_unverified_header(token)
        allowed = {"sub", "tenant_id", "roles", "scopes", "token_type", "iss", "aud",
                   "iat", "exp", "sid", "jti", "auth_epoch"}
        if (set(claims) != allowed or set(header) != {"alg", "typ"} or header["typ"] != "JWT"
                or claims["token_type"] != PRESENCE_TOKEN_TYPE
                or claims["aud"] != PRESENCE_TOKEN_AUDIENCE
                or type(claims["iat"]) is not int or type(claims["exp"]) is not int
                or not 0 < claims["exp"] - claims["iat"] <= 3600
                or claims["scopes"] != ["presence"] or not isinstance(claims["roles"], list)
                or not claims["roles"] or any(role not in ("user", "manager", "admin", "owner") for role in claims["roles"])):
            raise ValueError("Invalid presence profile")
        return claims  # Shared session validator checks identity, epoch, iat and exp.
    except (JWTError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid presence token") from exc


def decode_token_claims(token: str, *, refresh: bool = False) -> dict:
    """Validate the existing login/minted-token profile for every consumer."""
    secret = settings.jwt_refresh_secret_key if refresh else settings.jwt_secret_key
    try:
        payload = jwt.decode(
            token, secret, algorithms=[settings.jwt_algorithm],
            options={"require_exp": True},
        )
    except (JWTError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid token") from exc

    expected_type = "refresh" if refresh else "access"
    if payload.get("token_type") != expected_type:
        raise ValueError("Incorrect token type")
    # Reject malformed NumericDate claims rather than coercing strings/bools.
    if type(payload.get("exp")) is not int:
        raise ValueError("Invalid token expiration")
    if payload["exp"] <= int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("Expired token")
    return payload


def decode_token(token: str, *, refresh: bool = False) -> TokenPayload:
    payload = decode_token_claims(token, refresh=refresh)
    try:
        token_payload = TokenPayload(**payload)
    except ValidationError as exc:
        raise ValueError("Invalid token") from exc

    return token_payload
