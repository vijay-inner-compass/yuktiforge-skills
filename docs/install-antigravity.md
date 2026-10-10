# Installing skills for Antigravity

Skills for Antigravity live in `.agents/skills/<skill>/` inside your project. The packages for this agent already contain that path, so unzipping at your project root is the whole install.

```bash
unzip dist/<skill>-<version>-antigravity.zip -d /path/to/your/project
```

Or, with YuktiForge installed, a preview-first install with overwrite protection, uninstall and rollback:

```bash
yuktiforge install dist/<skill>-<version>-antigravity.zip --agent antigravity --project /path/to/your/project          # preview
yuktiforge install dist/<skill>-<version>-antigravity.zip --agent antigravity --project /path/to/your/project --apply  # install
```

## What was tested

- `architecture-visualizer`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation
- `api-contract-reviewer`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation
- `repository-intelligence`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation
- `documentation-intelligence`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation
- `code-explainer`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation
- `behavior-reconstructor`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation
- `requirements-reconstructor`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation
- `architecture-documenter`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation
- `data-documenter`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation
- `api-integration-documenter`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation
- `operations-documenter`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation
- `documentation-quality-auditor`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation
- `documentation-publisher`: **UNVERIFIED** (2.15.1) — not exercised: agent_discovery, agent_invocation

> Codex and Antigravity both read `.agents/skills/`; GitHub Copilot also reads it. Installing the same skill in several of these folders can make an agent list it twice; `yuktiforge install` warns about that.

> Antigravity is a desktop application with no command-line mode, so discovery and invocation could not be exercised automatically. The folder layout comes from the documentation bundled with the Antigravity IDE (2.5.5); the newer Antigravity 2.15.1 ships no readable docs. If you test it, please record the result.
