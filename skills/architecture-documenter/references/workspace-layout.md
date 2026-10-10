# Workspace layout

Every generating action writes under the `--out` directory you give it:

| Path | Content |
|---|---|
| `scan/` | `repository-inventory.json`, `symbol-index.json`, `dependency-index.json`, `coverage.json` (what was and was not analyzed) |
| `model/` | `system-knowledge.json` (entities, relationships, evidence, gaps, conflicts), `traceability.json`, `change-impact.json`, `store/` (SQLite: user statements and approvals survive re-runs) |
| `docs/` | one `<type>.<audience>.<depth>.md` per document with `.json`, `.evidence-map.json`, `.coverage.json`; `manifest.json`, `glossary.md`, `contradictions.json`, `requirements-traceability.json`, `validation.json` |
| `diagrams/` | one folder per diagram with `diagram.svg/png/pdf/dot`, `mapping.json`, `checks.json`; `diagrams.json` lists what was and was not generated and why |

Re-running with the same `--out` is safe: unchanged sections are kept as they are, and a person's statements, approvals and reviews are never overwritten.
The repository is only read.
