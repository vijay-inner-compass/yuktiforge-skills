"""Doctor output for the tier that renders and publishes."""
from __future__ import annotations

from yuktiforge.docint.publish import tools


def report() -> None:
    for name, info in tools.tool_report().items():
        print(f"  {name:20s} {info['path'] or 'not found (the matching output is reported UNAVAILABLE, nothing fails silently)'}")
