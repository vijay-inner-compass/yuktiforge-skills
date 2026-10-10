# Tutorial: install a skill, use it, undo it

Everything below was produced by running the commands on a real project folder; the output is quoted, not typed. Values such as hashes and sizes change with each build.
Agents were run headless, so there are no window screenshots; the transcripts below are the evidence. The only image in this project is the diagram in the README.

## What you need

* A skill zip for your agent from `dist/` (this tutorial uses `api-contract-reviewer` for codex). Python 3.12+ and the `yuktiforge` command are needed only for the optional installer; **unzipping is enough** to install.
* The agent itself, installed and logged in (Claude Code, GitHub Copilot CLI, Codex or Antigravity).

## Install with unzip (no YuktiForge needed)

```bash
unzip dist/api-contract-reviewer-0.1.0-codex.zip -d /path/to/your/project
```

## Install with YuktiForge (preview, protection, rollback)

### 1. Preview the install (writes nothing)

Nothing is written until you add `--apply`.

```text
$ yuktiforge install dist/api-contract-reviewer-0.1.0-codex.zip --agent codex --project <project>
PREVIEW: install api-contract-reviewer 0.1.0 for codex
  into  .agents/skills/api-contract-reviewer/  (21 files)
nothing written (add --apply to install)
```

### 2. Install



```text
$ yuktiforge install dist/api-contract-reviewer-0.1.0-codex.zip --agent codex --project <project> --apply
APPLY: install api-contract-reviewer 0.1.0 for codex
  into  .agents/skills/api-contract-reviewer/  (21 files)
installed api-contract-reviewer 0.1.0 -> .agents/skills/api-contract-reviewer/
```

### 3. See what is installed



```text
$ yuktiforge list --project <project>
codex           api-contract-reviewer        0.1.0    ok         managed  .agents/skills/api-contract-reviewer
```

### 4. Verify integrity

Every installed file is re-hashed against the manifest and the audit log's hash chain is checked.

```text
$ yuktiforge verify --project <project>
OK   codex/api-contract-reviewer ok
```

### 5. Installing again needs your confirmation

An existing skill is never overwritten silently; the refusal below is the expected behaviour. Add `--yes` to replace it (the old copy is kept).

```text
$ yuktiforge install dist/api-contract-reviewer-0.1.0-codex.zip --agent codex --project <project> --apply
APPLY: reinstall-same api-contract-reviewer 0.1.0 for codex
  into  .agents/skills/api-contract-reviewer/  (21 files)
  replaces version 0.1.0
error: .agents/skills/api-contract-reviewer already exists; confirm the overwrite (--yes) to replace it. A backup is kept.
```

### 6. Uninstall (preview, then apply)



```text
$ yuktiforge uninstall --project <project> --agent codex --skill api-contract-reviewer --apply
APPLY: remove codex/api-contract-reviewer (status ok); a backup is kept and `rollback` restores it
removed; backup at .yuktiforge/backups/codex/api-contract-reviewer/0001
```

### 7. Roll back (undo the uninstall)



```text
$ yuktiforge rollback --project <project> --agent codex --skill api-contract-reviewer --apply
APPLY: roll back codex/api-contract-reviewer to its most recent backup
restored version 0.1.0
```

### 8. Verify again



```text
$ yuktiforge verify --project <project>
OK   codex/api-contract-reviewer ok
```


## Use it

Ask your agent for the task. For example, with a file `api.json` in the project: *"Review api.json for contract problems using the api-contract-reviewer skill."*
Agents that were run for this release did exactly that, headless, in a disposable project:

* **claude-code** 2.1.284 (Claude Code) ran `api-contract-reviewer`: `python3 .claude/skills/api-contract-reviewer/scripts/api_contract_reviewer.py api.json` and answered `6` (12.4 s)
* **codex** codex-cli 0.159.0 ran `api-contract-reviewer`: `/bin/zsh -lc 'python3 .agents/skills/api-contract-reviewer/scripts/api_contract_reviewer.py api.json'` and answered `6` (32.5 s)
* **github-copilot** GitHub Copilot CLI 1.0.94. ran `api-contract-reviewer`: `python3 .github/skills/api-contract-reviewer/scripts/api_contract_reviewer.py api.json` and answered `6` (18.7 s)
* **claude-code** 2.1.284 (Claude Code) ran `architecture-visualizer`: `python3 .claude/skills/architecture-visualizer/scripts/yuktiforge_viz.py doctor` and answered `pass` (26.6 s)
* **codex** codex-cli 0.159.0 ran `architecture-visualizer`: `/bin/zsh -lc 'python3 .agents/skills/architecture-visualizer/scripts/yuktiforge_viz.py doctor'` and answered `pass` (46.5 s)
* **github-copilot** GitHub Copilot CLI 1.0.94. ran `architecture-visualizer`: `cd <project> && ls && python3 .github/skills/architecture-visualizer/scripts/yuktiforge_viz.py build --model clinic.model.yaml --view layered --out docs/architecture 2>&1 | tail -20; python3 -c "import json;print(json.load(open('docs/architecture/validation.json'))['result'])"` and answered `pass` (30.8 s)

You can also run the skill's script yourself, with no agent:

```text
$ python3 .agents/skills/api-contract-reviewer/scripts/api_contract_reviewer.py .agents/skills/api-contract-reviewer/examples/defective-api/input.txt
{
  "issue_count": 3,
  "issues": [
    {
      "message": "The document lacks a top-level 'security' definition, and no operation defines its own security requirements.",
      "path": "Document Level",
      "rule": "no-security"
    },
    {
      "message": "Operation is missing the required 'operationId'.",
      "path": "GET /pets",
      "rule": "missing-operation-id"
    },
    {
      "message": "Operation does not declare any explicit 4xx, 5xx, or 'default' error response.",
      "path": "GET /pets",
      "rule": "no-error-response"
    }
  ]
}
```

## Troubleshooting

| What you see | Why | What to do |
|---|---|---|
| `already exists; confirm the overwrite (--yes)` | a skill with that name is already in the folder | add `--yes`; the previous copy is kept and `yuktiforge rollback` restores it |
| `was modified after installation` when uninstalling | you (or something) edited the installed files | `--force` removes it anyway; the edited copy is kept and rollback restores it, reported as "NOT identical to the shipped package" |
| `checksum mismatch` / `hash mismatch against the manifest` | the zip is damaged or was changed | download it again and check `SHA256SUMS`; nothing is installed in this case |
| `is not a directory` / `is a symlink` | something else occupies the skill folder path | move it away; the installer will not write through a symlink or over a file |
| the agent lists the skill twice | the same skill is in two folders the agent reads (Copilot reads `.github/`, `.claude/` and `.agents/`; Codex and Antigravity read `.agents/`) | keep one copy; `yuktiforge install` warns when it sees this |
| `Missing Python packages (pydantic, PyYAML)` (architecture-visualizer) | the skill's dependencies are not installed | run the skill's `scripts/bootstrap.py` (the only step that downloads anything) or install the versions in `requirements.lock` |
| `tool dot: NOT FOUND` | Graphviz is not installed | install Graphviz (for example `brew install graphviz librsvg`); without `rsvg-convert` only SVG/HTML are produced |
| `Not logged in` when testing an agent | the agent CLI is not authenticated in that environment | log in to the agent; the test is then recorded as NOT_TESTED, never as a failure of the skill |
| `yuktiforge verify` says `untracked` | the skill was not installed by YuktiForge | nothing is wrong; its integrity simply cannot be checked |

## Known limitations

* Tested on macOS (Apple silicon) only; Linux and Windows are untested.
* Antigravity has no command-line mode: its folder layout is documented and installed correctly, but discovery and invocation were not exercised automatically.
* `requirements.lock` pins versions without hashes.
* The audit log is hash-chained: editing or removing a middle entry is detected, but deleting the **last** entry is not.
* Results are for the agent versions recorded in the compatibility matrix.
* Skills made by the YuktiForge Creator are `preview` until a person has reviewed them.
