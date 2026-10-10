# Installing documentation-quality-auditor 0.1.0

This folder is a complete skill. You do **not** need YuktiForge or its Creator to use it.

## Put it where your agent looks (project scope)

Unzip the package for your agent into the **root of your project**. The archive already contains the right folder:

| Agent | Folder created |
|---|---|
| claude-code | `.claude/skills/documentation-quality-auditor/` |
| github-copilot | `.github/skills/documentation-quality-auditor/` |
| codex | `.agents/skills/documentation-quality-auditor/` |
| antigravity | `.agents/skills/documentation-quality-auditor/` |

```bash
unzip documentation-quality-auditor-0.1.0-<agent>.zip -d /path/to/your/project
```

Or use YuktiForge for a preview, overwrite protection, uninstall and rollback:
`yuktiforge install documentation-quality-auditor-0.1.0-<agent>.zip --agent <agent> --project /path/to/your/project`.

Whether this skill has been **tested** in your agent is stated in the release's `compatibility-matrix.md`; an agent that is not marked
VERIFIED there was not tested, and the folder layout alone is not a guarantee.

## Prerequisites (nothing is installed for you)

* Python 3.12+
* Python packages `pydantic` and `PyYAML` at the versions in `requirements.lock`. Install them yourself, or create the skill's private
  environment once (this is the only step that downloads anything, and only when you run it):

```bash
python3 <skill folder>/scripts/bootstrap.py
```

Then check: `python3 <skill folder>/scripts/yuktiforge_docs.py doctor`, and `python3 <skill folder>/tests/smoke.py`.

The scan reads files only: it never builds, imports, installs or runs anything in the repository it scans, and uses no network.
`requirements.lock` pins exact versions but carries **no hashes**. This skill ships its own copy of the code it needs under `lib/`.

## Integrity

`yuktiforge.manifest.json` lists every file with its SHA-256; `yuktiforge verify <installed folder>` re-checks them.
The release carries a `SHA256SUMS` file for the zips.
