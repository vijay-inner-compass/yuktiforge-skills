# Evidence labels and states

| Label | Meaning |
|---|---|
| `VERIFIED` | Observed in source text or a structured file; cites `path:start-end`. |
| `INFERRED` | Derived by a stated rule from verified facts (for example a component grouping). Carries the rule. |
| `USER_SUPPLIED` | A named person said so (`model assert`). Never shown as verified. |
| `UNKNOWN` | Could not be established. Listed with what would establish it. |
| `NEEDS_STAKEHOLDER_VALIDATION` | A business, security or compliance owner must confirm. |

Document states: `DRAFT`, `NEEDS_REVIEW`, `APPROVED_BY_USER` (a named person approved that exact content), `STALE` (the model changed after the approval).
A generated requirement or business rule is a **candidate**; approval is a separate, recorded human act and is never implied by wording, labels or a validation pass.
