# macOS permissions

Atlas respects macOS's permission system -- it never attempts to bypass a
TCC prompt. This table will be filled in as each integration ships.

| Capability | macOS permission | Milestone | Status |
|---|---|---|---|
| Microphone (wake word + voice input) | Microphone | 2 | Not yet implemented |
| Calendar read | Calendar | 4 | Not yet implemented |
| Reminders read/write | Reminders | 4 | Not yet implemented |
| Mail read | Automation (Mail) | 6 | Not yet implemented |
| Notifications | Notifications | 4 | Not yet implemented |
| Launching/quitting apps | Automation | 4 | Not yet implemented |

None of these are required to run Atlas today -- V1 is text-only with no
tools registered, so no macOS permission dialog should appear yet.
