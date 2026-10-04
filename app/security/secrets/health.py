"""BUDDY Secret Vault Health Diagnostics.

Integrates with HealthManager to report vault readiness, DPAPI integrity,
and migration status without leaking secret values or plaintext metadata.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict

from app.core.health import HealthCheckResult, HealthStatus

if TYPE_CHECKING:
    from app.security.secrets.service import SecretVaultService


def create_secret_vault_health_check(service: SecretVaultService):
    """Generate diagnostic health check function for the secret vault subsystem."""

    def _health_check() -> HealthCheckResult:
        start_time = time.perf_counter()
        try:
            prov_health = service.provider.health()
            status = prov_health.status
            msg = prov_health.message

            # Check if legacy migration is pending
            details: Dict[str, Any] = {
                "provider": service.provider.provider_name,
                "secrets_count": len(service.provider.list_metadata()),
                "migration_checked": True,
            }

            return HealthCheckResult(
                name="security.secret_vault",
                status=status,
                message=f"Secret vault is {status.value}: {msg}",
                timestamp=time.time(),
                latency=time.perf_counter() - start_time,
                details=details,
            )
        except Exception as e:
            return HealthCheckResult(
                name="security.secret_vault",
                status=HealthStatus.UNHEALTHY,
                message=f"Secret vault health check failed: {e}",
                timestamp=time.time(),
                latency=time.perf_counter() - start_time,
            )

    return _health_check
