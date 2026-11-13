"""Real-handler Phase 1.2 checks after the original isolation guards are active."""
from pathlib import Path
import runpy
import unittest

fixture = runpy.run_path(str(Path(__file__).with_name("mcp_phase1_1_cases.py")))

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from jose import jwt  # noqa: E402
from backend.app import models as m  # noqa: E402
from backend.app.auth import decode_token_claims, hash_password  # noqa: E402

interop = {}


class Phase12(unittest.TestCase):
    setUp = fixture["Phase11"].setUp
    headers = fixture["Phase11"].headers
    request = fixture["Phase11"].request
    change_user = fixture["Phase11"].change_user
    token = fixture["Phase11"].token

    def refresh(self, token, prefix="", **kwargs):
        return self.client.post(prefix + "/auth/refresh", json={"refresh_token": token}, **kwargs)

    def test_json_form_login_and_current_tenant_refresh(self):
        self.change_user("member", hashed_password=hash_password("synthetic-phase12-password"))
        for prefix in ("", "/api"):
            for credentials in ({"json": {"email": "member@phase1.example.com", "password": "synthetic-phase12-password"}},
                                {"data": {"username": "member@phase1.example.com", "password": "synthetic-phase12-password"}}):
                login = self.client.post(prefix + "/auth/login", **credentials)
                self.assertEqual(login.status_code, 200)
                response = self.refresh(login.json()["token"]["refresh_token"], prefix)
                self.assertEqual(response.status_code, 200)
                claims = decode_token_claims(response.json()["access_token"])
                self.assertEqual((claims["sub"], claims["tenant_id"]), (self.ids["member"], str(self.tenant)))
                self.assertEqual(self.client.get(prefix + "/tasks/assigned/summary", headers={
                    "Authorization": "Bearer " + response.json()["access_token"]}).status_code, 200)

    def test_old_tenant_refresh_denied_and_new_tenant_login_works(self):
        old_access, old_refresh = self.headers(), self.token(refresh=True)
        self.change_user("member", tenant_id=self.foreign, hashed_password=hash_password("synthetic-phase12-password"))
        for prefix in ("", "/api"):
            self.assertEqual(self.refresh(old_refresh, prefix).status_code, 401)
            self.assertEqual(self.client.get(prefix + "/auth/me", headers=old_access).status_code, 401)
            login = self.client.post(prefix + "/auth/login", json={
                "email": "member@phase1.example.com", "password": "synthetic-phase12-password"})
            self.assertEqual(login.status_code, 200)
            current = self.refresh(login.json()["token"]["refresh_token"], prefix)
            self.assertEqual(current.status_code, 200)
            self.assertEqual(decode_token_claims(current.json()["access_token"])["tenant_id"], str(self.foreign))

    def test_missing_and_malformed_refresh_tenant_rejected(self):
        for tenant in ("OMIT", None, "", "default", 42, [], {}, "not-a-uuid"):
            token = self.token(refresh=True, tenant_id=tenant)
            for prefix in ("", "/api"):
                self.assertEqual(self.refresh(token, prefix).status_code, 401)

    def test_tenant_in_body_or_header_never_changes_signed_membership(self):
        old_refresh = self.token(refresh=True)
        for prefix in ("", "/api"):
            response = self.client.post(prefix + "/auth/refresh", headers={"X-Tenant-ID": str(self.foreign)},
                json={"refresh_token": old_refresh, "tenant_id": str(self.foreign)})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(decode_token_claims(response.json()["access_token"])["tenant_id"], str(self.tenant))
        self.change_user("member", tenant_id=self.foreign)
        for prefix in ("", "/api"):
            response = self.client.post(prefix + "/auth/refresh", headers={"X-Tenant-ID": str(self.foreign)},
                json={"refresh_token": old_refresh, "tenant_id": str(self.foreign)})
            self.assertEqual(response.status_code, 401)

    def test_inactive_refresh_denied_reactivation_is_not_revocation(self):
        old = self.token(refresh=True)
        self.change_user("member", status=m.UserStatusEnum.DEACTIVATED)
        for prefix in ("", "/api"):
            self.assertEqual(self.refresh(old, prefix).status_code, 403)
        self.change_user("member", status=m.UserStatusEnum.ACTIVE)
        for prefix in ("", "/api"):
            self.assertEqual(self.refresh(old, prefix).status_code, 200)
        print("OPEN_RISK: same-tenant reactivation restores unrevoked credentials; durable revocation NOT IMPLEMENTED")

    def test_tenant_return_requires_durable_revision_design(self):
        old = self.token(refresh=True)
        self.change_user("member", tenant_id=self.foreign)
        self.assertEqual(self.refresh(old).status_code, 401)
        self.change_user("member", tenant_id=self.tenant)
        self.assertEqual(self.refresh(old).status_code, 200)
        print("OPEN_RISK: tenant A->B rejects old A refresh; return B->A can revive it until expiry; revision migration REQUIRED")

    def test_refresh_expiry_type_signature_and_subject_validation(self):
        invalid = [self.token(refresh=True, exp=value) for value in ("OMIT", 0, int(time.time()), None, True, "9999999999", 1.5)]
        invalid += [self.token(refresh=True, token_type=value) for value in ("OMIT", "access", "presence", None, "")]
        invalid += [self.token(refresh=True, sub=value) for value in (None, [], {}, 42, "", " spaced ")]
        invalid += [self.token(refresh=True, scopes=value) for value in (None, "presence", {}, [None])]
        invalid += [self.token(refresh=True, user_id=self.ids["foreign"]), self.token()]
        claims = {"sub": self.ids["member"], "tenant_id": str(self.tenant), "token_type": "refresh", "exp": int(time.time()) + 300}
        invalid.append(jwt.encode(claims, "synthetic-untrusted-key", algorithm="HS256"))
        invalid.append(jwt.encode(claims, fixture["base"]["settings"].jwt_refresh_secret_key, algorithm="HS512"))
        for token in invalid:
            for prefix in ("", "/api"):
                self.assertEqual(self.refresh(token, prefix).status_code, 401)

    def test_valid_refresh_uses_current_database_role(self):
        old = self.token(refresh=True, roles=["owner"])
        for prefix in ("", "/api"):
            response = self.refresh(old, prefix)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(decode_token_claims(response.json()["access_token"])["roles"], ["user"])

    def test_presence_issuer_contract_and_real_node_interoperability_fixture(self):
        for prefix in ("", "/api"):
            response = self.request("GET", prefix + "/auth/presence-token")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            token = body["access_token"]
            claims = jwt.decode(token, fixture["base"]["settings"].jwt_secret_key,
                algorithms=["HS256"], issuer="zeaplay", audience="zeaplay-presence")
            self.assertEqual(claims["token_type"], "presence")
            self.assertEqual(claims["sub"], self.ids["member"])
            self.assertEqual(claims["tenant_id"], str(self.tenant))
            self.assertEqual(claims["roles"], ["user"])
            self.assertEqual(claims["scopes"], ["presence"])
            self.assertEqual(claims["exp"] - claims["iat"], 3600)
            self.assertEqual((body["token_type"], body["subject"]), ("bearer", self.ids["member"]))
            interop.update(presence=token, access=self.token(), refresh=self.token(refresh=True),
                           secret=fixture["base"]["settings"].jwt_secret_key, algorithm="HS256")

    def test_presence_credential_cannot_access_rest_refresh_or_mint_tokens(self):
        token = self.request("GET", "/auth/presence-token").json()["access_token"]
        with self.assertRaises(ValueError):
            decode_token_claims(token)
        for prefix in ("", "/api"):
            for path in ("/tasks/assigned/summary", "/auth/me", "/auth/presence-token"):
                self.assertEqual(self.client.get(prefix + path, headers={"Authorization": "Bearer " + token}).status_code, 401)
            self.assertEqual(self.refresh(token, prefix).status_code, 401)

    def test_presence_issuance_requires_active_authenticated_current_tenant(self):
        for prefix in ("", "/api"):
            self.assertEqual(self.client.get(prefix + "/auth/presence-token").status_code, 401)
            response = self.request("GET", prefix + "/auth/presence-token?user_id=" + self.ids["foreign"])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["subject"], self.ids["member"])
        stale = self.headers()
        self.change_user("member", status=m.UserStatusEnum.DEACTIVATED)
        self.assertEqual(self.client.get("/auth/presence-token", headers=stale).status_code, 403)
        self.change_user("member", status=m.UserStatusEnum.ACTIVE, tenant_id=uuid.uuid4())
        self.assertEqual(self.client.get("/auth/presence-token", headers=stale).status_code, 401)

    def test_api_mint_profile_stays_usable_and_separate(self):
        response = self.request("POST", "/auth/generate-token", name="owner", json={"scopes": ["presence"]})
        self.assertEqual(response.status_code, 200)
        token = response.json()["access_token"]
        claims = decode_token_claims(token)
        self.assertEqual(claims["token_type"], "access")
        self.assertNotIn("aud", claims)
        self.assertEqual(self.client.get("/tasks/assigned/summary", headers={"Authorization": "Bearer " + token}).status_code, 200)


if __name__ == "__main__":
    loader = unittest.defaultTestLoader
    original = loader.loadTestsFromTestCase(fixture["Phase11"])
    # The old assertion explicitly required presence to be an API-access token.
    # Replace that obsolete contract with the profile-separation tests above.
    original = unittest.TestSuite(test for test in original if test._testMethodName !=
                                 "test_current_minted_and_presence_tokens_keep_valid_profile")
    suite = unittest.TestSuite([loader.loadTestsFromTestCase(fixture["Fixture"]),
        loader.loadTestsFromTestCase(fixture["IsolationControls"]), original,
        loader.loadTestsFromTestCase(Phase12)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    for gate in fixture["base"]["SECURITY_GATES"]:
        print("SECURITY_GATE " + json.dumps(gate, sort_keys=True))
    if not result.wasSuccessful() or any(gate["result"] == "FAIL" for gate in fixture["base"]["SECURITY_GATES"]):
        raise SystemExit(1)
    output = Path(os.environ["ZEA_PHASE12_INTEROP_FILE"]).resolve()
    if output.parent != Path.cwd() or not interop:
        raise RuntimeError("Interop output must stay inside the owned scratch directory")
    output.write_text(json.dumps(interop), encoding="utf-8")
    print("INTEROP: synthetic Python-issued profiles prepared for isolated Node verification; token values suppressed")
