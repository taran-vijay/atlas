"""macOS PlatformIntegration implementation (Milestone 4 -- not yet built).

Planned approach:
  - Calendar/Reminders via EventKit (pyobjc)
  - Mail via an AppleScript/JXA bridge (no modern native read API exists)
  - Notifications via `osascript -e 'display notification ...'`
Every capability here requires an explicit macOS permission grant --
see docs/permissions.md.
"""
from __future__ import annotations

from atlas.platforms.base import CalendarEvent, PlatformIntegration


class MacOSIntegration(PlatformIntegration):
    async def list_calendar_events(self, start_iso: str, end_iso: str) -> list[CalendarEvent]:
        raise NotImplementedError("Calendar integration ships in Milestone 4")

    async def send_notification(self, title: str, message: str) -> None:
        raise NotImplementedError("Notifications integration ships in Milestone 4")
