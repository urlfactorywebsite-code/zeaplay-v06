"""Trusted, explicitly test-only login broker. This is NOT production delegation."""

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .auth import AuthorizationContext
from .errors import SafeError
from .request_identity import CredentialBinding
from .rest import BackendClient
from .upstream import Principal


class Account(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    email: str = Field(min_length=3, max_length=255)
    password: SecretStr
    capability: SecretStr


class BrokerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: str
    run_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    backend_origin: str
    attestation_secret: SecretStr
    accounts: dict[str, Account] = Field(min_length=1, max_length=8)


class TrustedTestBroker:
    def __init__(self, config: BrokerConfig, backend: BackendClient):
        if config.mode != "isolated-test" or backend.origin != config.backend_origin.rstrip("/"):
            raise ValueError("Production credential brokering is disabled")
        if len(config.attestation_secret.get_secret_value()) < 32:
            raise ValueError("Missing fixture attestation")
        self.config, self.backend = config, backend
        self._bindings: dict[str, CredentialBinding] = {}

    @classmethod
    def load(cls, path: Path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32768:
            raise ValueError("Invalid private broker configuration")
        config = BrokerConfig.model_validate_json(path.read_bytes())
        backend = BackendClient(config.backend_origin)
        return cls(config, backend)

    async def start(self):
        # Existing/production apps have no such route or test-only secret.
        nonce = secrets.token_hex(32)
        proof = await self.backend.json("GET", "/__phase2b__/attest", params={"nonce": nonce})
        expected = hmac.new(self.config.attestation_secret.get_secret_value().encode(),
                            (self.config.run_id + ":" + nonce).encode(), hashlib.sha256).hexdigest()
        if proof.get("run_id") != self.config.run_id or not isinstance(proof.get("proof"), str) or not hmac.compare_digest(expected, proof["proof"]):
            raise SafeError("AUTH_DENIED")
        self._bindings.clear()
        try:
            for alias, account in self.config.accounts.items():
                handle = account.capability.get_secret_value()
                if len(handle) < 32 or handle in self._bindings:
                    raise ValueError("Invalid broker capability")
                login = await self.backend.json("POST", "/auth/login", body={
                    "email": account.email, "password": account.password.get_secret_value()})
                credential = login["token"]["access_token"]
                if not isinstance(credential, str) or len(credential) > 8192:
                    raise SafeError("AUTH_DENIED")
                # Backend validates its own JWT and durable session; no shared
                # JWT signing secret, local signature bypass or untrusted token.
                principal = Principal.model_validate(await self.backend.json("GET", "/auth/me", credential=credential))
                # UserRead omits tenant_id. Read the issued claim ONLY after
                # the same credential successfully passed backend validation.
                payload = credential.split(".")[1]
                claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                tenant = str(uuid.UUID(claims["tenant_id"]))
                if claims["sub"] != principal.id or principal.role not in claims["roles"] or principal.status != "ACTIVE":
                    raise SafeError("AUTH_DENIED")
                context = AuthorizationContext(principal.id, tenant, "isolated-test-broker",
                    secrets.token_hex(16), frozenset({"tasks:read", "workload:read"}),
                    principal.role, principal.department_id, policy_revision="isolated-rest-v1")
                self._bindings[handle] = CredentialBinding(context, credential)
        except BaseException:
            self._bindings.clear()
            raise

    def resolve(self, capability: str | None) -> CredentialBinding | None:
        binding = self._bindings.get(capability or "")
        return binding if binding and not binding.revoked else None

    def for_stdio(self, alias: str | None) -> CredentialBinding | None:
        account = self.config.accounts.get(alias or "")
        return self.resolve(account.capability.get_secret_value()) if account else None

    def resolver(self, alias: str | None = None):
        def resolve_context(ctx):
            if ctx.request is None:
                return self.for_stdio(alias)
            return self.resolve(ctx.request.headers.get("x-zeaplay-test-broker"))
        return resolve_context

    async def close(self):
        for binding in self._bindings.values():
            binding.revoked = True
        self._bindings.clear()
        await self.backend.close()
