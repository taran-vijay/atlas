"""Sanitized, append-only audit log for tool activity.

Every tool dispatch should be recorded here: what was called, at what
permission tier, whether it required confirmation, and whether it was
approved. Message/content bodies are not logged by default -- only enough
to reconstruct what happened, per docs/security-model.md.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path

    def record(
        self,
        *,
        tool_name: str,
        permission: str,
        approved: bool,
        success: bool,
        extra: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "timestamp": time.time(),
            "tool": tool_name,
            "permission": permission,
            "approved": approved,
            "success": success,
            "extra": extra or {},
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
