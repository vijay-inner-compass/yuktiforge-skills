# Architecture model (version 1.0)

Top level: `name`, `description`, `layers[]`, `boundaries[]`, `components[]`, `relations[]`.
The exact JSON Schema is in `architecture-model.schema.json`. All ids match `^[a-z0-9][a-z0-9_.-]{0,63}$`.

| Object | Fields |
|---|---|
| layer | `id`, `name`, `order` (top to bottom) |
| boundary | `id`, `name`, `kind` (system, trust, deployment, team, other), `parent` (boundary id) |
| component | `id`, `name`, `kind` (person, system, external-system, container, service, component, datastore, queue, infrastructure, module, package, library), `layer`, `boundary`, `technology`, `description`, `evidence` |
| relation | `id`, `source`, `target` (component ids), `label`, `kind` (uses, calls, reads-writes, publishes, subscribes, depends-on, data-flow, deploys-to, other), `technology`, `evidence` |
| evidence | `status` (verified, user-supplied, inferred; default user-supplied), `sources[]` (`kind`: file/analyzer/user/document, `ref`), `rationale` (required for inferred), `confidence` 0-1 |

Views and what they draw: `layered` (all components, grouped by layer), `c4-context` (person/system/external-system only),
`c4-container` (adds container/service/datastore/queue/infrastructure; boundaries become boxes).
