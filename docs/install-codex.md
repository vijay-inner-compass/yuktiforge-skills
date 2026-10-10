# Installing skills for OpenAI Codex

Skills for OpenAI Codex live in `.agents/skills/<skill>/` inside your project. The packages for this agent already contain that path, so unzipping at your project root is the whole install.

```bash
unzip dist/<skill>-<version>-codex.zip -d /path/to/your/project
```

Or, with YuktiForge installed, a preview-first install with overwrite protection, uninstall and rollback:

```bash
yuktiforge install dist/<skill>-<version>-codex.zip --agent codex --project /path/to/your/project          # preview
yuktiforge install dist/<skill>-<version>-codex.zip --agent codex --project /path/to/your/project --apply  # install
```

## What was tested

- `architecture-visualizer`: **VERIFIED** (codex-cli 0.159.0) — all layers passed, including a real agent discovering and running the skill
- `api-contract-reviewer`: **VERIFIED** (codex-cli 0.159.0) — all layers passed, including a real agent discovering and running the skill
- `repository-intelligence`: **UNVERIFIED** (codex-cli 0.159.0) — not exercised: agent_discovery, agent_invocation
- `documentation-intelligence`: **UNVERIFIED** (codex-cli 0.159.0) — not exercised: agent_discovery, agent_invocation
- `code-explainer`: **UNVERIFIED** (codex-cli 0.159.0) — not exercised: agent_discovery, agent_invocation
- `behavior-reconstructor`: **UNVERIFIED** (codex-cli 0.159.0) — not exercised: agent_discovery, agent_invocation
- `requirements-reconstructor`: **UNVERIFIED** (codex-cli 0.159.0) — not exercised: agent_discovery, agent_invocation
- `architecture-documenter`: **UNVERIFIED** (codex-cli 0.159.0) — not exercised: agent_discovery, agent_invocation
- `data-documenter`: **UNVERIFIED** (codex-cli 0.159.0) — not exercised: agent_discovery, agent_invocation
- `api-integration-documenter`: **UNVERIFIED** (codex-cli 0.159.0) — not exercised: agent_discovery, agent_invocation
- `operations-documenter`: **UNVERIFIED** (codex-cli 0.159.0) — not exercised: agent_discovery, agent_invocation
- `documentation-quality-auditor`: **UNVERIFIED** (codex-cli 0.159.0) — not exercised: agent_discovery, agent_invocation
- `documentation-publisher`: **UNVERIFIED** (codex-cli 0.159.0) — not exercised: agent_discovery, agent_invocation

> Codex and Antigravity both read `.agents/skills/`; GitHub Copilot also reads it. Installing the same skill in several of these folders can make an agent list it twice; `yuktiforge install` warns about that.
