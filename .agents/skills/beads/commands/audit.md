---
description: Log and label agent interactions (append-only JSONL)
argument-hint: "record|label"
---

Append-only audit logging for agent interactions (prompts, responses, tool calls) in `.beads/interactions.jsonl`.

Each line is one event. Labeling is done by appending a new `"label"` event referencing a previous entry.

## Usage

- **Record an interaction**:
  - `bd audit record --kind llm_call --model "claude-3-5-haiku" --prompt "..." --response "..."`
  - `bd audit record --kind tool_call --tool-name "go test" --exit-code 1 --error "..." --issue-id bd-42`
  - Logging full prompts/responses/tool args/output is **opt-in**, not the default — by default record only metadata (kind, model, tool name, exit code). Before recording free-form text, redact common secret patterns (API keys/tokens, passwords, `Authorization`/bearer headers, connection strings, private keys) since prompts, responses, errors, and tool args often contain them.

- **Pipe JSON via stdin**:
  - `cat event.json | bd audit record`

- **Label an entry**:
  - `bd audit label int-a1b2 --label good --reason "Worked perfectly"`
  - `bd audit label int-a1b2 --label bad --reason "Hallucinated a file path"`

## Notes

- Audit entries are **append-only** (no in-place edits).
- `bd dolt push` includes `.beads/interactions.jsonl` in the commit allowlist, so anything recorded is **durably synced to the Dolt remote** — treat the file as published. If it may hold secrets or private content, exclude it from sync (e.g. via `.gitignore`/allowlist) or restrict it to a private remote rather than logging sensitive values.


