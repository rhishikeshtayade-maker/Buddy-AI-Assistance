"""BUDDY Tool Execution Engine.

Coordinates the end-to-end execution lifecycle: registry lookup, input validation,
permission enforcement, confirmation/authentication boundaries, bounded timeout execution,
state verification, structured result generation, event emission, and audit logging.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from app.core.events import EventBus
from app.core.exceptions import (
    AuthenticationError,
    ConfirmationError,
    PathSecurityError,
    PermissionDeniedError,
    SecurityError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolTimeoutError,
    VerificationError,
)
from app.security.audit import AuditLogger, AuditRecord
from app.security.authentication import Authenticator, MockAuthenticator
from app.security.confirmation import ConfirmationManager
from app.security.permissions import PermissionDecision, PermissionEngine
from app.tools.events import (
    ToolConfirmationRequiredEvent,
    ToolDeniedEvent,
    ToolExecutionCompletedEvent,
    ToolExecutionFailedEvent,
    ToolExecutionStartedEvent,
    ToolPermissionCheckedEvent,
    ToolRequestedEvent,
    ToolVerificationFailedEvent,
)
from app.tools.models import (
    ToolExecutionStatus,
    ToolRequest,
    ToolResult,
    ToolRiskLevel,
)
from app.tools.registry import ToolRegistry

logger = logging.getLogger("buddy.tools.executor")


class ToolExecutor:
    """Orchestrates secure tool invocation and empirical state verification."""

    def __init__(
        self,
        registry: ToolRegistry,
        permission_engine: Optional[PermissionEngine] = None,
        confirmation_manager: Optional[ConfirmationManager] = None,
        authenticator: Optional[Authenticator] = None,
        event_bus: Optional[EventBus] = None,
        audit_logger: Optional[AuditLogger] = None,
        default_timeout: float = 10.0,
    ) -> None:
        self._registry = registry
        self._permission_engine = permission_engine or PermissionEngine()
        self._confirmation_manager = confirmation_manager or ConfirmationManager()
        self._authenticator = authenticator or MockAuthenticator()
        self._event_bus = event_bus
        self._audit_logger = audit_logger or AuditLogger()
        self._default_timeout = default_timeout

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def confirmation_manager(self) -> ConfirmationManager:
        return self._confirmation_manager

    @property
    def permission_engine(self) -> PermissionEngine:
        return self._permission_engine

    async def _publish(self, event: Any) -> None:
        if self._event_bus:
            try:
                await self._event_bus.publish(event)
            except Exception as e:
                logger.error("Failed to publish tool event %s: %s", type(event).__name__, e)

    async def execute(
        self,
        request: ToolRequest,
        confirmation_token: Optional[str] = None,
        auth_credential: Optional[str] = None,
    ) -> ToolResult:
        """Execute a tool request through all security and verification stages.

        Args:
            request: The structured tool execution request.
            confirmation_token: Confirmation token if tool requires explicit approval.
            auth_credential: User PIN or authentication secret if required.

        Returns:
            Strongly typed ToolResult with empirical verification status.
        """
        start_time = time.perf_counter()
        req_id = request.request_id
        tool_name = request.tool_name

        audit = AuditRecord(
            request_id=req_id,
            tool_name=tool_name,
            conversation_id=request.conversation_id,
        )

        await self._publish(
            ToolRequestedEvent(
                request_id=req_id,
                tool_name=tool_name,
                arguments=request.arguments,
                conversation_id=request.conversation_id,
                requested_by=request.requested_by,
            )
        )

        # 1. Lookup tool in registry
        tool = self._registry.get_tool(tool_name)
        if not tool:
            err_msg = f"Unknown tool: '{tool_name}' is not registered."
            logger.warning(err_msg)
            audit.execution_status = ToolExecutionStatus.DENIED.value
            audit.error_category = "ToolNotFound"
            audit.metadata = {"reason": err_msg}
            self._audit_logger.record(audit)
            await self._publish(ToolDeniedEvent(request_id=req_id, tool_name=tool_name, reason=err_msg))

            return ToolResult(
                request_id=req_id,
                tool_name=tool_name,
                success=False,
                verified=False,
                status=ToolExecutionStatus.DENIED,
                error=err_msg,
                execution_latency=time.perf_counter() - start_time,
            )

        definition = tool.definition
        audit.risk_level = definition.risk_level.name

        # 2. Validate input parameters against tool schema
        try:
            validated_args = await tool.validate_input(request.arguments)
        except Exception as val_err:
            err_msg = f"Invalid arguments for tool '{tool_name}': {val_err}"
            logger.warning(err_msg)
            audit.execution_status = ToolExecutionStatus.FAILED.value
            audit.error_category = "ValidationError"
            audit.metadata = {"error": str(val_err)}
            self._audit_logger.record(audit)
            await self._publish(ToolExecutionFailedEvent(request_id=req_id, tool_name=tool_name, error=err_msg))

            return ToolResult(
                request_id=req_id,
                tool_name=tool_name,
                success=False,
                verified=False,
                status=ToolExecutionStatus.FAILED,
                error=err_msg,
                execution_latency=time.perf_counter() - start_time,
            )

        # 3. Permission Engine Evaluation
        decision: PermissionDecision = self._permission_engine.evaluate(request, definition)
        audit.permission_decision = "ALLOWED" if decision.allowed else "DENIED"

        await self._publish(
            ToolPermissionCheckedEvent(
                request_id=req_id,
                tool_name=tool_name,
                risk_level=decision.risk_level,
                allowed=decision.allowed,
                requires_confirmation=decision.requires_confirmation,
                requires_authentication=decision.requires_authentication,
                reason=decision.reason,
            )
        )

        if not decision.allowed:
            audit.execution_status = ToolExecutionStatus.DENIED.value
            self._audit_logger.record(audit)
            await self._publish(ToolDeniedEvent(request_id=req_id, tool_name=tool_name, reason=decision.reason))
            return ToolResult(
                request_id=req_id,
                tool_name=tool_name,
                success=False,
                verified=False,
                status=ToolExecutionStatus.DENIED,
                error=decision.reason,
                execution_latency=time.perf_counter() - start_time,
            )

        # 4. Authentication Check if required
        if decision.requires_authentication:
            audit.authentication_decision = "REQUIRED"
            authenticated = await self._authenticator.authenticate(
                challenge=f"Execute tool '{tool_name}'",
                credential=auth_credential,
            )
            if not authenticated:
                err_msg = f"Authentication required for tool '{tool_name}' (risk {decision.risk_level.name})."
                audit.authentication_decision = "FAILED"
                audit.execution_status = ToolExecutionStatus.AUTHENTICATION_REQUIRED.value
                self._audit_logger.record(audit)
                await self._publish(ToolDeniedEvent(request_id=req_id, tool_name=tool_name, reason=err_msg))

                return ToolResult(
                    request_id=req_id,
                    tool_name=tool_name,
                    success=False,
                    verified=False,
                    status=ToolExecutionStatus.AUTHENTICATION_REQUIRED,
                    error=err_msg,
                    execution_latency=time.perf_counter() - start_time,
                )
            audit.authentication_decision = "PASSED"

        # 5. Confirmation Check if required
        if decision.requires_confirmation:
            if not confirmation_token:
                # Issue new confirmation token and hold execution
                token_obj = self._confirmation_manager.request_confirmation(request)
                audit.confirmation_decision = "REQUIRED"
                audit.execution_status = ToolExecutionStatus.CONFIRMATION_REQUIRED.value
                self._audit_logger.record(audit)

                await self._publish(
                    ToolConfirmationRequiredEvent(
                        request_id=req_id,
                        tool_name=tool_name,
                        token=token_obj.token,
                        expires_at=token_obj.expires_at,
                        arguments=request.arguments,
                    )
                )

                return ToolResult(
                    request_id=req_id,
                    tool_name=tool_name,
                    success=False,
                    verified=False,
                    status=ToolExecutionStatus.CONFIRMATION_REQUIRED,
                    error=f"Confirmation required. Token issued: {token_obj.token}",
                    metadata={"confirmation_token": token_obj.token, "expires_at": token_obj.expires_at},
                    execution_latency=time.perf_counter() - start_time,
                )

            # Validate provided confirmation token
            try:
                self._confirmation_manager.validate_and_consume(
                    token=confirmation_token,
                    request_id=req_id,
                    tool_name=tool_name,
                    arguments=request.arguments,
                )
                audit.confirmation_decision = "CONFIRMED"
            except ConfirmationError as conf_err:
                err_msg = f"Confirmation validation failed: {conf_err}"
                audit.confirmation_decision = "REJECTED"
                audit.execution_status = ToolExecutionStatus.DENIED.value
                audit.error_category = "ConfirmationError"
                self._audit_logger.record(audit)
                await self._publish(ToolDeniedEvent(request_id=req_id, tool_name=tool_name, reason=err_msg))

                return ToolResult(
                    request_id=req_id,
                    tool_name=tool_name,
                    success=False,
                    verified=False,
                    status=ToolExecutionStatus.DENIED,
                    error=err_msg,
                    execution_latency=time.perf_counter() - start_time,
                )

        # 6. Execute with bounded timeout
        timeout = definition.timeout_seconds or self._default_timeout
        audit.execution_status = ToolExecutionStatus.EXECUTING.value
        await self._publish(ToolExecutionStartedEvent(request_id=req_id, tool_name=tool_name))

        raw_output: Any = None
        try:
            raw_output = await asyncio.wait_for(
                tool.execute(validated_args),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            err_msg = f"Tool execution timed out after {timeout:.1f} seconds."
            logger.error("Tool '%s' timed out (req_id=%s)", tool_name, req_id)
            audit.execution_status = ToolExecutionStatus.TIMEOUT.value
            audit.error_category = "TimeoutError"
            audit.execution_latency = time.perf_counter() - start_time
            self._audit_logger.record(audit)

            await self._publish(
                ToolExecutionFailedEvent(
                    request_id=req_id,
                    tool_name=tool_name,
                    status=ToolExecutionStatus.TIMEOUT,
                    error=err_msg,
                )
            )

            return ToolResult(
                request_id=req_id,
                tool_name=tool_name,
                success=False,
                verified=False,
                status=ToolExecutionStatus.TIMEOUT,
                error=err_msg,
                execution_latency=time.perf_counter() - start_time,
            )
        except Exception as exec_err:
            err_msg = f"Tool execution failed: {exec_err}"
            logger.error("Tool '%s' execution error: %s", tool_name, exec_err, exc_info=True)
            audit.execution_status = ToolExecutionStatus.FAILED.value
            audit.error_category = type(exec_err).__name__
            audit.execution_latency = time.perf_counter() - start_time
            self._audit_logger.record(audit)

            await self._publish(
                ToolExecutionFailedEvent(
                    request_id=req_id,
                    tool_name=tool_name,
                    status=ToolExecutionStatus.FAILED,
                    error=err_msg,
                )
            )

            return ToolResult(
                request_id=req_id,
                tool_name=tool_name,
                success=False,
                verified=False,
                status=ToolExecutionStatus.FAILED,
                error=err_msg,
                execution_latency=time.perf_counter() - start_time,
            )

        # 7. Post-Execution Empirical Verification
        verified = False
        try:
            verified = await tool.verify(validated_args, raw_output)
        except Exception as v_err:
            logger.error("Verification raised unexpected exception for '%s': %s", tool_name, v_err)
            verified = False

        latency = time.perf_counter() - start_time
        audit.verified = verified
        audit.execution_latency = latency

        if not verified:
            err_msg = "Verification failed: actual system state did not match expected outcome."
            logger.warning("Tool '%s' verification failed (req_id=%s)", tool_name, req_id)
            audit.execution_status = ToolExecutionStatus.VERIFICATION_FAILED.value
            audit.error_category = "VerificationFailed"
            self._audit_logger.record(audit)

            await self._publish(ToolVerificationFailedEvent(request_id=req_id, tool_name=tool_name, error=err_msg))

            return ToolResult(
                request_id=req_id,
                tool_name=tool_name,
                success=False,
                verified=False,
                status=ToolExecutionStatus.VERIFICATION_FAILED,
                output=raw_output,
                error=err_msg,
                execution_latency=latency,
            )

        # 8. Succeeded and Verified
        audit.execution_status = ToolExecutionStatus.SUCCEEDED.value
        self._audit_logger.record(audit)

        await self._publish(
            ToolExecutionCompletedEvent(
                request_id=req_id,
                tool_name=tool_name,
                status=ToolExecutionStatus.SUCCEEDED,
                execution_latency=latency,
            )
        )

        return ToolResult(
            request_id=req_id,
            tool_name=tool_name,
            success=True,
            verified=True,
            status=ToolExecutionStatus.SUCCEEDED,
            output=raw_output,
            execution_latency=latency,
        )
