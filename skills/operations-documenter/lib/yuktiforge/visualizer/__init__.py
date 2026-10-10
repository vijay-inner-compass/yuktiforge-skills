"""architecture-visualizer: universal architecture model + deterministic rendering.

Layering (enforced by tests): model/validate/render know nothing about source languages.
Language-specific knowledge lives only in `visualizer.analyzers`.
"""
