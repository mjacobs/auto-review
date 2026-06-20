---
description: Check beads and plugin versions
---

Check the installed versions of beads components and verify compatibility.

**Note:** The MCP server checks the bd CLI version against its bundled minimum on startup. This command provides detailed version info and update instructions.

Use the beads MCP tools to:
1. Run `bd version` via bash to get the CLI version
2. Check the vendored skill/plugin version (see `skills-lock.json`; `bd prime` is the authoritative CLI guidance)
3. Compare versions and report any mismatches

Display:
- bd CLI version (from `bd version`)
- Vendored skill/plugin version (from `skills-lock.json`)
- MCP server version (from the connection / `stats` tool)
- MCP server status (from `stats` tool or connection test)
- Compatibility status (✓ compatible or ⚠️ update needed)

If versions are mismatched, provide instructions:
- Update bd CLI: `curl -fsSL https://raw.githubusercontent.com/gastownhall/beads/main/scripts/install.sh | bash`
- Update plugin: `/plugin update beads`
- Restart Claude Code after updating

Suggest checking for updates if the user is on an older version.
