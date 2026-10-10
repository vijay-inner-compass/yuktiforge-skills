---
name: architecture-visualizer
description: Creates architecture diagrams (layered, C4 context, C4 container) with SVG, PNG, PDF and HTML exports from a natural-language description, a structured YAML/JSON model, documentation, or a source repository in any language. Use when the user asks to diagram, visualize, or document a system's architecture. Every element is marked verified, user-supplied or inferred, and unanalyzed languages are reported.
---

# Architecture Visualizer

<!-- yuktiforge:skill-dir -->

Turns an architecture description into a validated canonical model, then renders it deterministically
with Graphviz. The tool never invents architecture: it only draws what the model says, and the model
only contains what a file, the user, or a stated inference supports.

## Prerequisites (check first)

Run `python3 scripts/yuktiforge_viz.py doctor` (path relative to this skill's folder). It reports the Python packages and tools
this skill needs. If something is missing, tell the user what, and point them to `INSTALL.md`; do not install anything yourself
without the user's approval. If `rsvg-convert` is missing, PNG/PDF are reported "unavailable": say so.

## Evidence rules (non-negotiable)

- `verified`: a file or analyzer proves it (cite `path` or `path:line`). Only analyzers produce these.
- `user-supplied`: the user or a document they gave you states it. Cite the document in `sources`.
- `inferred`: you are guessing from indirect hints. Requires a `rationale`; prefer asking the user instead.
- Never add a relation because it "usually exists". If unsure, ask, or leave it out and say so.
- Never assign layers or boundaries the user did not state; unlayered components appear under "Unassigned".

## Workflow

1. **Pick the input path**
   - *Natural-language or documentation*: YOU write the model YAML (schema: `references/model-schema.md`,
     example: `references/example-model.yaml`). The tool cannot read prose. Keep names exactly as stated.
   - *Structured YAML/JSON*: use it as the model.
   - *Source repository*: run `python3 scripts/yuktiforge_viz.py analyze --repo <dir> --granularity package` (multi-language, manifests)
     or `--granularity module` (Python import graph). Read `coverage` in the output: languages with
     `depth: none` were NOT analyzed. Put user-stated layers/externals/runtime links in an overlay file and pass
     `--overlay`.
   - *No source code at all* (specification-only, infrastructure-only) is fully supported through the first two paths.
2. **Validate**: `python3 scripts/yuktiforge_viz.py validate --model model.yaml` (or the `--repo ... --overlay ...` form). Fix every
   `error` (missing ids, dangling edges, duplicates, unsupported "verified" claims). Review warnings.
3. **Build**: `python3 scripts/yuktiforge_viz.py build --model model.yaml --view layered --out docs/architecture`
   Views: `layered`, `c4-context`, `c4-container`, `c4-component`, `deployment`, `integration`, `data-flow`, `erd`. Check `python3 scripts/yuktiforge_viz.py views` — any other view is NOT implemented;
   do not promise it.
4. **Inspect the result yourself**: open `diagram.png`, and read `validation.json`. Look for overlapping or hidden
   edges, labels crossing text, and every `warning`. Fix the model/overlay and rebuild if something is wrong.
5. **Report honestly** (read the legend of the picture too: it states omitted kinds, unanalyzed languages and unparseable files): list the files produced (`architecture.json`, `diagram.dot`, `diagram.svg`, `diagram.png`,
   `diagram.pdf`, `preview.html`, `validation.json`), the evidence summary, inferred items with their rationale,
   unanalyzed languages, and any validation warnings. Do not say "complete" if languages were unanalyzed.

## Known limits

- Graphviz is the only renderer (D2 is not supported). Connectors are polyline, not orthogonal, because
  orthogonal routing cannot place edge labels reliably.
- Layout is chosen by trying a fixed list of Graphviz layouts and keeping the best-scoring one (see `layout.trials` in
  `validation.json`). Remaining readability findings (`edges-coincide`, `label-detached`, `edge-crosses-title`,
  `edge-on-border`) are warnings; label/label overlap, layers that do not stack, and ink touching the image edge are errors.
- A diagram whose layers have internal edges can be sprawling (those layers cascade diagonally) because clarity is preferred over compactness.
- Components of kinds a view does not draw, languages with no analyzer, and files that could not be parsed are named in the
  diagram legend: never describe those parts as "absent"; they are unknown or omitted.
- `event-driven`, `infrastructure` and `sequence` views are not implemented. The entity-relationship view needs `entity` components with `attributes`, and the DFD notation view is drawn from whatever components the model has without checking balance between levels (the documentation pipeline does that).
- Analyzers: package manifests (npm, Python, Maven, Go modules, Cargo) and Python imports only.
  C#, Kotlin, Swift, C/C++, PHP, Ruby, Gradle/NuGet manifests, etc. are detected as languages but NOT analyzed.
