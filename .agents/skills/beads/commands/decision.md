---
description: Record, list, and manage project decisions with rationale tracking
argument-hint: "record|list|show|supersede"
---

Record and track project decisions as beads issues with structured rationale, alternatives considered, and links to affected work.

Decisions use `--type decision`. The description field holds the structured decision record.

## Record a Decision

When the user wants to record a decision (or you invoke `bd decision record`):

1. Gather the following (ask if not provided):
   - **Title**: Short summary of what was decided (required)
   - **Rationale**: Why this was chosen (required)
   - **Alternatives**: What else was considered (optional but encouraged)
   - **Affects**: Issue IDs this decision impacts (optional)
   - **Priority**: How important (default P2)

2. Create the issue using the beads MCP `create` tool with `type: decision`,
   passing the title and the structured description below as tool arguments.
   Do NOT build a shell `bd create` command that interpolates the user-supplied
   title or description text — passing them as tool arguments avoids shell
   command/heredoc injection. (If you must use the CLI, pass the description via
   `--body-file <path>` — or `--body-file -` to read from stdin — never an inline
   `"<title>"` or a `$(cat <<EOF ...)` heredoc.)

   Description content:

```markdown
## Decision

<one-sentence summary of what was decided>

## Rationale

<why this was chosen>

## Alternatives Considered

- **<alt 1>**: <why rejected>
- **<alt 2>**: <why rejected>

## Affects

- <issue IDs or area descriptions>
```

3. If `--affects` issue IDs were provided, link them:
```bash
bd dep add <decision-id> <affected-id> --type related
```

4. Show the created decision to the user.

## List Decisions

```bash
bd list --type decision
```

To see all decisions including closed/superseded:
```bash
bd list --type decision --all
```

## Show a Decision

```bash
bd show <decision-id>
```

Include comments for discussion history:
```bash
bd comments <decision-id>
```

## Supersede a Decision

When a decision is replaced by a new one:

1. Record the new decision (as above)
2. Link the new decision to the old one:
   ```bash
   bd dep add <new-id> <old-id> --type related
   ```
3. Add a comment on the old decision:
   ```bash
   bd comments add <old-id> "Superseded by <new-id>: <brief reason>"
   ```
4. Close the old decision:
   ```bash
   bd close <old-id> --reason "Superseded by <new-id>"
   ```

## Add Context to an Existing Decision

Use comments to append discussion, implementation notes, or revisit rationale:
```bash
bd comments add <decision-id> "Implementation note: ..."
```

## Search Decisions

```bash
bd search "keyword" --type decision
```

## Conventions

- **Status**: `open` = active decision, `closed` = superseded or reversed
- **Description format**: Use the structured template above for consistency
- **Linking**: Use `related` dependency type to connect decisions to affected issues
- **Labels**: Use labels for categorizing decisions (e.g., `architecture`, `tooling`, `process`)
