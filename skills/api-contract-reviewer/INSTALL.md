# Installing api-contract-reviewer 0.1.0

This folder is a complete skill. You do **not** need YuktiForge or its Creator to use it.

## Put it where your agent looks (project scope)

Unzip the package for your agent into the **root of your project**. The archive already contains the right folder:

| Agent | Folder created |
|---|---|
| claude-code | `.claude/skills/api-contract-reviewer/` |
| github-copilot | `.github/skills/api-contract-reviewer/` |
| codex | `.agents/skills/api-contract-reviewer/` |
| antigravity | `.agents/skills/api-contract-reviewer/` |

```bash
unzip api-contract-reviewer-0.1.0-<agent>.zip -d /path/to/your/project
```

Or use YuktiForge for a preview, overwrite protection, uninstall and rollback:
`yuktiforge install api-contract-reviewer-0.1.0-<agent>.zip --agent <agent> --project /path/to/your/project`.

Whether this skill has been **tested** in your agent is stated in the release's `compatibility-matrix.md`; an agent that is not marked
VERIFIED there was not tested, and the folder layout alone is not a guarantee.

## Integrity

`yuktiforge.manifest.json` lists every file with its SHA-256; `yuktiforge verify <installed folder>` re-checks them.
The release carries a `SHA256SUMS` file for the zips.
