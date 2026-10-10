# Installing skills for Claude Code

Skills for Claude Code live in `.claude/skills/<skill>/` inside your project. The packages for this agent already contain that path, so unzipping at your project root is the whole install.

```bash
unzip dist/<skill>-<version>-claude-code.zip -d /path/to/your/project
```

Or, with YuktiForge installed, a preview-first install with overwrite protection, uninstall and rollback:

```bash
yuktiforge install dist/<skill>-<version>-claude-code.zip --agent claude-code --project /path/to/your/project          # preview
yuktiforge install dist/<skill>-<version>-claude-code.zip --agent claude-code --project /path/to/your/project --apply  # install
```

## What was tested

- `architecture-visualizer`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
- `api-contract-reviewer`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
- `repository-intelligence`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
- `documentation-intelligence`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
- `code-explainer`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
- `behavior-reconstructor`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
- `requirements-reconstructor`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
- `architecture-documenter`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
- `data-documenter`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
- `api-integration-documenter`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
- `operations-documenter`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
- `documentation-quality-auditor`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
- `documentation-publisher`: **VERIFIED** (2.1.284 (Claude Code)) — all layers passed, including a real agent discovering and running the skill
