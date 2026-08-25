"""Platform integration interface.

core/tools depends only on this interface. Concrete OS integrations
(platforms/macos, eventually platforms/windows) implement it -- core code
never imports a platform package directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CalendarEvent:
    title: str
    start_iso: str
    end_iso: str
    location: str | None = None


class PlatformIntegration(ABC):
    @abstractmethod
    async def list_calendar_events(self, start_iso: str, end_iso: str) -> list[CalendarEvent]:
        ...

    @abstractmethod
    async def send_notification(self, title: str, message: str) -> None:
        ...
