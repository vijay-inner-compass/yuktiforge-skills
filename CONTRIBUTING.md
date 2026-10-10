# Contributing and authoring skills

A skill is a folder with a native `SKILL.md` (YAML frontmatter with `name` and `description`), optional `scripts/`, `references/`, `schemas/`, `examples/` and `tests/`.
To add a skill to a release, add an entry to `release/release.yaml` in the YuktiForge repository; the catalog, README table, zips and checksums are generated from it.

A skill can only be marked `release` if it passes the release gates: description and purpose, declared inputs and outputs, install instructions, a real license,
declared dependencies, at least one agent where it was **verified** by a recorded test run and none where it failed, resolvable documentation links, a manifest that matches the files,
and a clean source revision. Otherwise it is published as `preview` or the release fails.

Skills made by the YuktiForge Creator start as `preview`: someone has to read the generated code and tests before it is promoted.

Please do not add claims (language support, security, compatibility) without evidence a maintainer can re-run.
