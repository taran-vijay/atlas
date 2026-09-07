# macOS permissions and approvals

Atlas respects macOS permission prompts and never attempts to bypass them.
Its own confirmation dialog is separate from a macOS privacy permission:
confirmation authorizes one requested action, while macOS controls access to
protected services.

## Available today

| Capability | Protection | Behavior |
|---|---|---|
| System status | None | Read-only tools run only when the user explicitly asks. |
| Local file inspection | Normal file access | Atlas can only inspect paths the current user can read. |
| Open apps/files, clipboard write, file/folder actions | Atlas confirmation | The desktop app shows the exact requested action and target before execution. |
| Voice output | None | Speech is generated or played locally; no microphone access is needed. |

File actions are scoped tools, not arbitrary shell access. Atlas verifies
results where the operating system makes verification possible and records a
local action-history entry for confirmation-gated actions.

## Not implemented

| Capability | Expected macOS permission | Status |
|---|---|---|
| Voice input, wake word, speech-to-text | Microphone | Not implemented |
| Calendar and Reminders | Calendars / Reminders | Not implemented |
| Mail and Messages | Automation / app-specific access | Not implemented |
| Notifications | Notifications | Not implemented |

Atlas explicitly reports unavailable integrations instead of pretending it can
read them.
