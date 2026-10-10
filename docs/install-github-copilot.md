# Installing skills for GitHub Copilot

Skills for GitHub Copilot live in `.github/skills/<skill>/` inside your project. The packages for this agent already contain that path, so unzipping at your project root is the whole install.

```bash
unzip dist/<skill>-<version>-github-copilot.zip -d /path/to/your/project
```

Or, with YuktiForge installed, a preview-first install with overwrite protection, uninstall and rollback:

```bash
yuktiforge install dist/<skill>-<version>-github-copilot.zip --agent github-copilot --project /path/to/your/project          # preview
yuktiforge install dist/<skill>-<version>-github-copilot.zip --agent github-copilot --project /path/to/your/project --apply  # install
```

## What was tested

- `architecture-visualizer`: **VERIFIED** (GitHub Copilot CLI 1.0.95.) — all layers passed, including a real agent discovering and running the skill
- `api-contract-reviewer`: **VERIFIED** (GitHub Copilot CLI 1.0.95.) — all layers passed, including a real agent discovering and running the skill
- `repository-intelligence`: **UNVERIFIED** (GitHub Copilot CLI 1.0.95.) — not exercised: agent_discovery, agent_invocation
- `documentation-intelligence`: **UNVERIFIED** (GitHub Copilot CLI 1.0.95.) — not exercised: agent_discovery, agent_invocation
- `code-explainer`: **UNVERIFIED** (GitHub Copilot CLI 1.0.95.) — not exercised: agent_discovery, agent_invocation
- `behavior-reconstructor`: **UNVERIFIED** (GitHub Copilot CLI 1.0.95.) — not exercised: agent_discovery, agent_invocation
- `requirements-reconstructor`: **UNVERIFIED** (GitHub Copilot CLI 1.0.95.) — not exercised: agent_discovery, agent_invocation
- `architecture-documenter`: **UNVERIFIED** (GitHub Copilot CLI 1.0.95.) — not exercised: agent_discovery, agent_invocation
- `data-documenter`: **UNVERIFIED** (GitHub Copilot CLI 1.0.95.) — not exercised: agent_discovery, agent_invocation
- `api-integration-documenter`: **UNVERIFIED** (GitHub Copilot CLI 1.0.95.) — not exercised: agent_discovery, agent_invocation
- `operations-documenter`: **UNVERIFIED** (GitHub Copilot CLI 1.0.95.) — not exercised: agent_discovery, agent_invocation
- `documentation-quality-auditor`: **UNVERIFIED** (GitHub Copilot CLI 1.0.95.) — not exercised: agent_discovery, agent_invocation
- `documentation-publisher`: **UNVERIFIED** (GitHub Copilot CLI 1.0.95.) — not exercised: agent_discovery, agent_invocation
