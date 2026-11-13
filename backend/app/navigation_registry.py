"""Stable page identities and permission ceilings; never accept these from clients.

Route ceilings derive from existing roles and operation capabilities. API
dependencies still apply independently: a navigation policy only removes access.
"""
from .models import RoleEnum
from .permissions import API_ADMIN_ROLES, NAVIGATION_MANAGERS

ALL = tuple(role.value for role in RoleEnum)
STAFF = ("manager", "admin", "owner")
OWNER = ("owner",)
ADMINS = tuple(role.value for role in NAVIGATION_MANAGERS)


def page(id, label, route, roles=ALL, *, parent=None, protected=False, location="sidebar", desktop=True, mobile=True, icon=None):
    return {"id": id, "defaultLabel": label, "route": route, "permittedRoles": list(roles),
                "parentId": parent, "isSystemProtected": protected, "navigationLocation": location,
                "desktop": desktop, "mobile": mobile, "icon": icon or id}


PAGES = [
    page("dashboard", "Dashboard", "/dashboard"),
    page("tasks", "All Tasks", "/tasks"),
    page("tasks.list", "All Tasks", "/tasks", parent="tasks", protected=True, location="task-tab", icon="tasks"),
    page("kanban", "Kanban Board", "/tasks/kanban", parent="tasks", location="task-tab"),
    page("gantt", "Gantt Chart", "/tasks/gantt", STAFF, parent="tasks", location="task-tab"),
    page("calendar", "Calendar", "/tasks/calendar", parent="tasks", location="task-tab"),
    page("tickets", "Ticket", "/tickets"),
    page("tool-library", "Tool Library", "/tool-library"),
    page("users", "Users", "/admin/users", STAFF),
    page("reports", "Reports", "/reports", STAFF),
    page("achievements", "Achievements", "/achievements"),
    page("settings", "Settings", "/settings", protected=True),
    page("points", "Points", "/admin/points-table", OWNER, parent="achievements", desktop=False),
    page("templates", "Templates", "/template-editor", OWNER, parent="achievements", desktop=False),
    page("levels", "Levels", "/levels", parent="achievements", desktop=False),
    page("chat", "Chat", "/chat", desktop=False, mobile=False),
    page("settings.profile", "General / Profile", "/settings/profile", parent="settings", protected=True, location="settings-tab"),
    page("settings.support", "Support", "/settings/support", parent="settings", location="settings-tab"),
    page("settings.master-control", "Master Control", "/settings/master-control", OWNER, parent="settings", location="settings-tab"),
    page("settings.api", "API", "/settings/api", tuple(role.value for role in API_ADMIN_ROLES), parent="settings", location="settings-tab"),
    page("settings.mcp-management", "MCP Management", "/settings/mcp-management", tuple(role.value for role in API_ADMIN_ROLES), parent="settings", location="settings-tab"),
    page("settings.logs", "Logs", "/settings/logs", STAFF, parent="settings", location="settings-tab"),
    page("settings.media-library", "Media Library", "/settings/media-library", parent="settings", location="settings-tab"),
    page("settings.sidebar-management", "Sidebar Management", "/settings/sidebar-management", ADMINS, parent="settings", protected=True, location="settings-tab"),
]
BY_ID = {entry["id"]: entry for entry in PAGES}


def default_rules():
    return {p["id"]: {"enabled": True, "hidden": False, "allowedRoles": p["permittedRoles"][:]} for p in PAGES}


def api_pages(path: str, method: str = "GET") -> tuple[str, ...]:
    """Shared resources remain available through another authorized page.

    Fine-grained object/operation permissions remain the endpoint's responsibility.
    Do not use a client-supplied page header to authorize requests.
    """
    path = path.removeprefix("/api").rstrip("/")
    if path == "/support":
        return ("settings.support",)
    if path == "/mcp-management" or path.startswith("/mcp-management/"):
        return ("settings.mcp-management",)
    if path.startswith("/tasks/calendar"):
        return ("calendar",)
    if path == "/tasks/kanban" or path.startswith("/kanban"):
        return ("kanban",)
    if path.startswith(("/tasks", "/comments")):
        return ("tasks.list", "kanban", "calendar", "gantt", "dashboard")
    if path.startswith("/tickets"):
        return ("tickets",)
    if path.startswith("/chat"):
        return ("chat",)
    if path.startswith("/tool-library"):
        return ("tool-library",)
    if path.startswith("/logs"):
        return ("settings.logs",)
    # Avatar upload/finalization is also a protected Profile capability.
    if path in ("/media/presign", "/media/confirm", "/media/avatar/finalize"):
        return ("settings.media-library", "settings.profile")
    if path.startswith("/media"):
        return ("settings.media-library",)
    if path.startswith("/feature-flags"):
        return ("settings.master-control",)
    if path == "/auth/generate-token":
        return ("settings.api",)
    if path.startswith("/users") and method != "GET" and not path.startswith("/users/me"):
        return ("users",)
    # Internal server AI consumes tenant credentials without using these HTTP
    # administration endpoints. Navigation hiding never grants endpoint access.
    if path.startswith(("/config/smtp", "/config/oauth", "/config/api", "/config/email-templates", "/webhooks", "/internal/webhooks", "/integrations/n8n")):
        return ("settings.api",)
    if path.startswith("/config/points"):
        return ("@points",)
    if path.startswith("/levels") and method != "GET":
        return ("levels",)
    if path.startswith(("/levels", "/rewards", "/achievements", "/badges")):
        return ("achievements",)
    return ()
