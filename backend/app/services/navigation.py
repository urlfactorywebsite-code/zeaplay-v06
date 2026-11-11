"""Tenant policy evaluation shared by page checks and API enforcement."""
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from .. import models
from ..navigation_registry import BY_ID, PAGES, default_rules
from ..permissions import NAVIGATION_MANAGERS


def load_policy(db, tenant_id):
    try:
        row = db.get(models.NavigationPolicy, str(tenant_id))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(503, "Navigation configuration is unavailable. Apply the navigation migration before serving this release.") from exc
    rules = default_rules()
    if row:
        if not isinstance(row.pages, dict):
            raise HTTPException(503, "Stored navigation configuration requires administrator repair.")
        for key, rule in row.pages.items():
            if key not in BY_ID:
                continue
            if (not isinstance(rule, dict) or set(rule) != {"enabled", "hidden", "allowedRoles"}
                    or type(rule["enabled"]) is not bool or type(rule["hidden"]) is not bool
                    or not isinstance(rule["allowedRoles"], list)
                    or any(not isinstance(role, str) for role in rule["allowedRoles"])
                    or len(rule["allowedRoles"]) != len(set(rule["allowedRoles"]))
                    or not set(rule["allowedRoles"]).issubset(BY_ID[key]["permittedRoles"])):
                raise HTTPException(503, "Stored navigation configuration requires administrator repair.")
            if BY_ID[key]["isSystemProtected"] and (not rule["enabled"] or rule["hidden"] or set(rule["allowedRoles"]) != set(BY_ID[key]["permittedRoles"])):
                raise HTTPException(503, "Protected recovery configuration requires administrator repair.")
        rules.update({key: value for key, value in row.pages.items() if key in BY_ID})
    return row, rules


def access(page_id, role, rules, *, switch_only=False):
    entry = BY_ID[page_id]
    rule = rules[page_id]
    if not switch_only and (role not in entry["permittedRoles"] or role not in rule["allowedRoles"]):
        return "forbidden"
    if not rule["enabled"]:
        return "disabled"
    if entry["parentId"]:
        parent = access(entry["parentId"], role, rules, switch_only=switch_only)
        if parent != "allowed":
            return parent
    return "allowed"


def public_policy(db, user):
    row, rules = load_policy(db, user.tenant_id)
    role = user.role.value
    pages = []
    for entry in PAGES:
        rule = rules[entry["id"]]
        state = access(entry["id"], role, rules)
        parent_hidden = bool(entry["parentId"] and rules[entry["parentId"]]["hidden"])
        pages.append({**entry, **rule, "access": state,
                      "visible": state == "allowed" and not rule["hidden"] and not parent_hidden})
    return dict(tenantId=str(user.tenant_id), version=row.version if row else 0,
                updatedBy=row.updated_by if row else None,
                updatedAt=row.updated_at if row else None,
                roles=[role.value for role in models.RoleEnum],
                canManage=user.role in NAVIGATION_MANAGERS,
                canChangeAccess=user.role == models.RoleEnum.OWNER, pages=pages)


def enforce_pages(db, user, page_ids):
    if not page_ids:
        return
    _, rules = load_policy(db, user.tenant_id)
    states = [access(key.lstrip("@"), user.role.value, rules,
                     switch_only=key.startswith("@") and user.role.value not in BY_ID[key.lstrip("@")]["permittedRoles"])
              for key in page_ids]
    if "allowed" in states:
        return
    state = "disabled" if "disabled" in states else "forbidden"
    raise HTTPException(403, {"code": f"module_{state}", "message": "This module is disabled by your organization." if state == "disabled" else "Your role does not have access to this module."})
