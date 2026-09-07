"""Registry that owns every tool and enforces the permission gate.

This is the single choke point between an LLM's tool call and anything that
touches the local OS, network, or user data. No component should call
Tool.execute() directly -- everything routes through ToolRegistry.dispatch().
"""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from atlas.core.tools.base import PermissionLevel, Tool, ToolResult

ConfirmationCallback = Callable[[str, dict[str, Any]], Awaitable[bool]]
ActionAuditCallback = Callable[[str, dict[str, Any], ToolResult], Awaitable[None]]
_LOGGER = logging.getLogger(__name__)


class ToolNotFoundError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


class ToolRegistry:
    def __init__(
        self,
        *,
        confirm: ConfirmationCallback | None = None,
        audit: ActionAuditCallback | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._confirm = confirm
        self._audit = audit

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(name) from exc

    def list_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_llm_schema() for tool in self._tools.values()]

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        try:
            tool = self.get(name)
        except ToolNotFoundError:
            return ToolResult(
                success=False,
                content="",
                error=f"Unknown tool: '{name}'.",
            )

        arguments = self._normalize_arguments(tool, arguments)

        try:
            tool.validate_arguments(arguments)
        except (TypeError, ValueError) as exc:
            return ToolResult(
                success=False,
                content="",
                error=f"Invalid arguments for '{tool.name}': {exc}",
            )

        try:
            preflight_error = await tool.preflight(arguments)
        except Exception:  # noqa: BLE001 - a tool boundary must contain implementation failures.
            return ToolResult(
                success=False,
                content="",
                error=f"'{tool.name}' could not check whether it can run safely.",
            )
        if preflight_error is not None:
            return await self._finalize(
                tool,
                arguments,
                ToolResult(success=False, content="", error=preflight_error, verification="not_run"),
            )

        try:
            if tool.permission in (PermissionLevel.CONFIRM, PermissionLevel.PRIVILEGED):
                if self._confirm is None:
                    raise PermissionDeniedError(
                        f"'{tool.name}' requires confirmation but no confirmation "
                        "handler is configured"
                    )
                approved = await self._confirm(tool.name, arguments)
                if not approved:
                    return await self._finalize(
                        tool,
                        arguments,
                        ToolResult(
                        success=False, content="", error="User declined confirmation"
                        ),
                    )
            result = await self._execute_with_safe_retry(tool, arguments)
            return await self._finalize(tool, arguments, result)
        except PermissionDeniedError as exc:
            return await self._finalize(
                tool, arguments, ToolResult(success=False, content="", error=str(exc))
            )
        except Exception:  # noqa: BLE001 - a tool boundary must contain implementation failures.
            return await self._finalize(
                tool,
                arguments,
                ToolResult(
                    success=False,
                    content="",
                    error=f"'{tool.name}' could not complete safely.",
                ),
            )

    async def _finalize(
        self, tool: Tool, arguments: dict[str, Any], result: ToolResult
    ) -> ToolResult:
        if tool.permission != PermissionLevel.READ_ONLY and self._audit is not None:
            try:
                await self._audit(tool.name, arguments, result)
            except Exception:  # recording must not change an action outcome.
                _LOGGER.exception("action_audit_failed tool=%s", tool.name)
        return result

    async def _execute_with_safe_retry(self, tool: Tool, arguments: dict[str, Any]) -> ToolResult:
        """Retry only read-only failures; mutations are never repeated automatically."""
        attempts = 2 if tool.permission == PermissionLevel.READ_ONLY else 1
        result: ToolResult | None = None
        for attempt in range(1, attempts + 1):
            result = await tool.execute(arguments)
            if result.success or attempt == attempts:
                break
        assert result is not None
        result = replace(result, attempts=attempt)
        if not result.success:
            return replace(result, verification="not_run")
        try:
            verified = await tool.verify(arguments, result)
        except Exception:  # noqa: BLE001 - verification failure must contain a tool boundary.
            return ToolResult(
                success=False,
                content="",
                error=f"'{tool.name}' completed but Atlas could not verify the outcome.",
                attempts=attempt,
                verification="failed",
            )
        if verified is False:
            return ToolResult(
                success=False,
                content="",
                error=f"'{tool.name}' did not produce the expected result.",
                attempts=attempt,
                verification="failed",
            )
        return replace(result, verification="verified" if verified else "not_applicable")

    @staticmethod
    def _normalize_arguments(tool: Tool, arguments: dict[str, Any]) -> dict[str, Any]:
        """Canonicalize safe integer strings emitted by local tool-calling models.

        Coercion is limited to properties that the tool's own JSON schema declares
        as integers; every other validation rule still runs unchanged.
        """
        normalized = arguments.copy()
        properties = tool.parameters.get("properties", {})
        if not isinstance(properties, dict):
            return normalized
        for key, schema in properties.items():
            value = normalized.get(key)
            if (
                isinstance(schema, dict)
                and schema.get("type") == "integer"
                and isinstance(value, str)
                and re.fullmatch(r"[+-]?\d+", value.strip())
            ):
                normalized[key] = int(value)
        return normalized
