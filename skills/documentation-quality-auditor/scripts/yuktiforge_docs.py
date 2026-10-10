#!/usr/bin/env python3
"""documentation-quality-auditor: entry point of the installed skill. Needs only the files in this skill folder, Python 3.12+, and `pydantic` and `PyYAML`
(pinned in requirements.lock). Run `python3 scripts/yuktiforge_docs.py doctor` first. If packages are missing and `<skill>/.venv` exists, this re-runs itself there."""
import os
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
VENV_PY = SKILL / ".venv" / "bin" / "python"
if sys.version_info < (3, 12):
    sys.exit("documentation-quality-auditor needs Python 3.12 or newer (found %d.%d)" % sys.version_info[:2])
sys.path.insert(0, str(SKILL / "lib"))
try:
    import pydantic  # noqa: F401
    import yaml  # noqa: F401
except ImportError:
    if VENV_PY.is_file() and Path(sys.executable).resolve() != VENV_PY.resolve() and not os.environ.get("YUKTIFORGE_DOCS_REEXEC"):
        os.environ["YUKTIFORGE_DOCS_REEXEC"] = "1"
        os.execv(str(VENV_PY), [str(VENV_PY), __file__, *sys.argv[1:]])
    sys.stderr.write("Missing Python packages (pydantic, PyYAML). Nothing was installed.\n"
                     "Create the skill's private environment once:  python3 %s\n" % (SKILL / "scripts" / "bootstrap.py"))
    sys.exit(3)

from yuktiforge.docint.skillmain.full import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(skill="documentation-quality-auditor"))
