"""Capabilities shared by navigation ceilings and operation dependencies."""
from .models import RoleEnum

API_ADMIN_ROLES = (RoleEnum.OWNER, RoleEnum.ADMIN)
# These are separate capabilities even though their current role sets coincide.
# API permission changes must not silently grant navigation-policy management.
NAVIGATION_MANAGERS = (RoleEnum.OWNER, RoleEnum.ADMIN)
