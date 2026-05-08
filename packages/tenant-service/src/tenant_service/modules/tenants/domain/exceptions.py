from __future__ import annotations


class TenantNotFoundError(Exception):
    """Raised when a tenant is not found."""

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        super().__init__(f"Tenant not found: {tenant_id}")


class TenantSlugExistsError(Exception):
    """Raised when a tenant slug already exists."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Tenant slug already exists: {slug}")


class UserAlreadyMemberError(Exception):
    """Raised when a user is already a member of the tenant."""

    def __init__(self, user_id: str, tenant_id: str) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        super().__init__(f"User {user_id} is already a member of tenant {tenant_id}")


class InsufficientPermissionError(Exception):
    """Raised when a user lacks permission for an action."""

    def __init__(self, message: str = "Insufficient permissions") -> None:
        super().__init__(message)
