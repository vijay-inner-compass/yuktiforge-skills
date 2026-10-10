# Compatibility matrix

Derived from recorded test evidence bound to the exact package content (`compatibility/evidence/`). Anything not exercised is UNVERIFIED.

| Skill | claude-code | github-copilot | codex | antigravity |
|---|---|---|---|---|
| `architecture-visualizer` | VERIFIED | VERIFIED | VERIFIED | UNVERIFIED |
| `api-contract-reviewer` | VERIFIED | VERIFIED | VERIFIED | UNVERIFIED |
| `repository-intelligence` | VERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| `documentation-intelligence` | VERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| `code-explainer` | VERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| `behavior-reconstructor` | VERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| `requirements-reconstructor` | VERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| `architecture-documenter` | VERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| `data-documenter` | VERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| `api-integration-documenter` | VERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| `operations-documenter` | VERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| `documentation-quality-auditor` | VERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| `documentation-publisher` | VERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |

Status meanings: **VERIFIED** every layer passed including a real agent discovering and running the skill; **UNVERIFIED** nothing failed but something was not exercised, or the evidence is stale; **FAILED** a tested layer failed; **UNSUPPORTED** the skill does not target the agent.

| Skill | Agent | Status | Agent version | package valid | clean install | script execution | agent discovery | agent invocation | lifecycle | Why |
|---|---|---|---|---|---|---|---|---|---|---|
| `architecture-visualizer` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `architecture-visualizer` | github-copilot | **VERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `architecture-visualizer` | codex | **VERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `architecture-visualizer` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `api-contract-reviewer` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `api-contract-reviewer` | github-copilot | **VERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `api-contract-reviewer` | codex | **VERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `api-contract-reviewer` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `repository-intelligence` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `repository-intelligence` | github-copilot | **UNVERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `repository-intelligence` | codex | **UNVERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `repository-intelligence` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `documentation-intelligence` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `documentation-intelligence` | github-copilot | **UNVERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `documentation-intelligence` | codex | **UNVERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `documentation-intelligence` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `code-explainer` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `code-explainer` | github-copilot | **UNVERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `code-explainer` | codex | **UNVERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `code-explainer` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `behavior-reconstructor` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `behavior-reconstructor` | github-copilot | **UNVERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `behavior-reconstructor` | codex | **UNVERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `behavior-reconstructor` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `requirements-reconstructor` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `requirements-reconstructor` | github-copilot | **UNVERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `requirements-reconstructor` | codex | **UNVERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `requirements-reconstructor` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `architecture-documenter` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `architecture-documenter` | github-copilot | **UNVERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `architecture-documenter` | codex | **UNVERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `architecture-documenter` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `data-documenter` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `data-documenter` | github-copilot | **UNVERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `data-documenter` | codex | **UNVERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `data-documenter` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `api-integration-documenter` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `api-integration-documenter` | github-copilot | **UNVERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `api-integration-documenter` | codex | **UNVERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `api-integration-documenter` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `operations-documenter` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `operations-documenter` | github-copilot | **UNVERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `operations-documenter` | codex | **UNVERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `operations-documenter` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `documentation-quality-auditor` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `documentation-quality-auditor` | github-copilot | **UNVERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `documentation-quality-auditor` | codex | **UNVERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `documentation-quality-auditor` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `documentation-publisher` | claude-code | **VERIFIED** | 2.1.284 (Claude Code) | PASS | PASS | PASS | PASS | PASS | PASS | all layers passed, including a real agent discovering and running the skill |
| `documentation-publisher` | github-copilot | **UNVERIFIED** | GitHub Copilot CLI 1.0.95. | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `documentation-publisher` | codex | **UNVERIFIED** | codex-cli 0.159.0 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
| `documentation-publisher` | antigravity | **UNVERIFIED** | 2.15.1 | PASS | PASS | PASS | NOT_TESTED | NOT_TESTED | PASS | not exercised: agent_discovery, agent_invocation |
