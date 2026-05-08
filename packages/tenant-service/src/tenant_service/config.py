from __future__ import annotations

from accounting_shared import SharedSettings


class TenantSettings(SharedSettings):
    """Tenant-service specific settings."""

    default_coa_seed: bool = True

    @property
    def service_name(self) -> str:
        return "tenant-service"
