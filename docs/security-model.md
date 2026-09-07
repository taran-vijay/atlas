# Security model

Atlas treats model output as untrusted input. A local model can propose a tool
call, but it cannot execute a command, inspect private data, or change the
computer by itself.

## Permission tiers

Each tool declares one permission tier:

| Tier | Behavior |
|---|---|
| `READ_ONLY` | Runs only for an explicit request for local machine or file data. |
| `CONFIRM` | Shows the user the requested action and target before execution. |
| `PRIVILEGED` | Uses confirmation and receives extra scrutiny for higher-impact operations such as moving a file to Trash. |

`ToolRegistry.dispatch()` is the only execution path. It validates tool
arguments, performs a safety preflight, enforces approval, contains tool
failures, and verifies a result where that is possible. There is intentionally
no general-purpose shell-execution tool.

## Reliable tool results

Tool results use a structured success/error format. Atlas retries only failed
read-only operations, never repeats a mutation automatically, and reports a
partial result if one requested tool is unavailable. It does not reuse stale
machine data or invent values for a failed result.

## Untrusted content and unsupported services

Tool output is treated as data rather than instructions. The assistant prompt
instructs the model not to follow directions contained in tool results or
quoted documents. Atlas also recognizes unsupported services such as Calendar
and Mail and tells the user that no integration exists rather than fabricating
events or messages.

## Local records and secrets

Conversation history, explicit memories, action history, voice preferences,
and logs are local to the Mac. Confirmation-gated actions are retained in the
local action history without recording clipboard content. The project has no
hardcoded API keys and requires no cloud account for its default local path.

`AuditLogger` is available for append-only sanitized tool audit records as the
project expands its integrations.
