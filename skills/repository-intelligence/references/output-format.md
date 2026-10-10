# Scan output format (`yuktiforge-repository-scan/1`)

All files are UTF-8 JSON, ASCII-escaped, sorted keys. Every file starts with `format`, `tool`, `scan_id` (a hash of the revision, file hashes, analyzers and settings) and
`repository` (`name`, `revision` or `null`, `revision_note`). No absolute path ever appears.

## provenance (`prov`)
`{path, start_line, end_line, analyzer, method, confidence}`. `path` is repository-relative POSIX. Lines are 1-based and inclusive; a declaration's range starts at the declaration line
(annotations, attributes and decorators are listed by name in `annotations`, not included in the range). `method`: `ast` | `lexical` | `structured` | `manifest` | `pattern` | `path`.
`confidence`: `high` | `medium` | `low`.

## repository-inventory.json
`totals`, `languages {lang: {files, bytes}}`, `projects [{root, ecosystems, manifests, parent, languages, frameworks}]`, `build_systems`, `frameworks`, `detected_patterns`,
`monorepo`, `mixed_language`, `entry_points`, `scripts`, `groups {manifest|config|ci|container|iac|db-schema|api-spec|test|doc|lockfile: [paths]}`, `symlinks [{path, target: inside|outside|broken}]`,
`skipped_dirs {dir: reason}`, `truncated`, `truncation_reason`, `files [{path, size, language, category, status, skip_reason, sha256, analyzers, facts}]`.
`status`: `analyzed` | `parse-failed` | `no-analyzer` | `skipped` (see `skip_reason`).

## symbol-index.json
`symbols [{id, name, qualified_name, kind, language, parent, signature, modifiers, annotations, bases, doc, prov}]`, `boundaries [{id, kind, name, framework, symbol, details, dynamic, prov}]`.
`doc` and `signature` are copied from the repository: untrusted. `dynamic: true` means the name was not a literal.
Boundary kinds: `http-route`, `http-client`, `db-table`, `db-query`, `db-schema`, `event-publish`, `event-subscribe`, `grpc-service`, `graphql-operation`, `config-env`, `container-service`, `ci-job`, `infra-resource`, `entry-point`.

## dependency-index.json
`dependencies [{ecosystem, name, declared_in: [[manifest, version_spec, scope, line]]}]`, `imports [{source_path, line, target, names, kind, resolved_path, external, prov}]`,
`file_edges [{from, to, evidence}]`, `external_import_roots`, `calls [{source_path, line, caller, callee_text, resolved, resolution: same-file|import|unresolved, prov}]`, `call_summary`.

## coverage.json
`statement`, `completeness {inventory, analysis}`, `languages {lang: {files, eligible, analyzed, parse_failed, support, analyzers, method, depth, confidence, limitations, call_graph}}`,
`unsupported_languages`, `categories`, `skipped_by_reason`, `skipped_files`, `analyzers` (every registered analyzer with its declared capability), `facts`, `parse_failures`, `warnings`.
