#!/usr/bin/env python3
"""Smoke test for the installed skill: runs the skill on the bundled example repository and checks the result against known facts. Run:  python3 tests/smoke.py
(uses <skill>/.venv automatically if it exists). Exit 0 = the skill works on this machine."""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
ENTRY = SKILL / "scripts" / "yuktiforge_docs.py"
SHOP = SKILL / "examples" / "shop"
SKILL_ID = re.search(r"^skill_id:\s*(\S+)", (SKILL / "skillspec.yaml").read_text(encoding="utf-8"), re.M).group(1)

# skill -> (action, extra args, document types that must exist, text that must appear in the documents)
DOCS = {
    "code-explainer": ("explain", [], ["code-explanation"], ["api.shop.service.OrderService"]),
    "behavior-reconstructor": ("reconstruct", [], ["functional-spec", "business-rule-catalog", "use-cases"], ["POST /orders"]),
    "requirements-reconstructor": ("reconstruct", [], ["brd-draft", "srs-draft", "business-rule-catalog"], ["POST /orders", "NEEDS_STAKEHOLDER_VALIDATION"]),
    "architecture-documenter": ("document", [], ["system-architecture", "solution-architecture", "technology-architecture", "hld", "lld"], ["POST /orders"]),
    "data-documenter": ("document", [], ["data-dictionary", "database-doc"], ["orders"]),
    "api-integration-documenter": ("document", [], ["api-catalog", "dataflow"], ["POST /orders", "billing.example.com"]),
    "operations-documenter": ("document", [], ["operations-runbook"], ["DB_PATH", "KAFKA_BROKER"]),
    "documentation-intelligence": ("run", [], ["system-architecture", "hld", "api-catalog", "data-dictionary", "business-rule-catalog", "operations-runbook"], ["POST /orders", "DB_PATH"]),
    "documentation-quality-auditor": ("prepare", [], ["system-architecture", "api-catalog", "data-dictionary"], ["POST /orders"]),
    "documentation-publisher": ("prepare", [], ["system-architecture", "api-catalog", "data-dictionary"], ["POST /orders"]),
}


def run(*args):
    return subprocess.run([sys.executable, str(ENTRY), *args], capture_output=True, text=True, timeout=600)


def fail(msg, r=None):
    print("FAIL:", msg)
    if r is not None:
        print((r.stderr or r.stdout).strip()[-1500:])
    return 1


def main() -> int:
    d = run("doctor")
    print(d.stdout.strip())
    if d.returncode != 0:
        print(d.stderr.strip() or "doctor reported a problem")
        return d.returncode
    action, extra, types, needles = DOCS[SKILL_ID]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "ws"
        r = run(action, "--repo", str(SHOP), "--out", str(out), *extra)
        if r.returncode != 0:
            return fail(f"{action} failed", r)
        docs = out / "docs"
        val = json.loads((docs / "validation.json").read_text())
        if not val["all_ok"]:
            return fail("generated documents have validation defects")
        text = ""
        for t in types:
            found = sorted(docs.glob(f"{t}.*.md"))
            if not found:
                return fail(f"missing document: {t}")
            text += found[0].read_text(encoding="utf-8")
        missing = [n for n in needles if n not in text]
        if missing:
            return fail(f"documents do not state known facts: {missing}")
        if "[VERIFIED]" not in text:
            return fail("documents carry no evidence labels")
        model = json.loads((out / "model" / "system-knowledge.json").read_text())
        routes = sorted(e["name"] for e in model["entities"] if e["type"] == "api" and e.get("subtype") == "route")
        print("routes:", routes)
        if routes != ["ANY /healthz", "GET /health", "POST /orders"]:
            return fail("model does not contain the known routes")
        extras = ""
        if SKILL_ID == "documentation-quality-auditor":
            a = run("audit", "--input", str(docs), "--model", str(out / "model"), "--repo", str(SHOP))
            print(a.stdout.strip()[-600:])
            ev = json.loads((docs / "audit" / "evaluation.json").read_text())
            failed = ev["verdict"]["failed"]
            if a.returncode not in (0, 1) or failed:
                return fail(f"audit gates failed: {failed}", a)
            extras = f"; audit gates failed: {len(failed)}"
        elif SKILL_ID == "documentation-publisher":
            pk = run("publish", "--model", str(out / "model"), "--out", str(out / "pack"), "--formats", "html")
            if pk.returncode != 0 or not (out / "pack" / "pack-manifest.json").is_file():
                return fail("publish failed", pk)
            extras = "; html pack written and link-checked"
        elif SKILL_ID in ("architecture-documenter", "data-documenter", "api-integration-documenter", "operations-documenter", "documentation-intelligence"):
            g = run("diagrams", "--model", str(out / "model"), "--out", str(out / "diagrams"))
            idx = out / "diagrams" / "diagrams.json"
            if not idx.is_file():
                print("diagrams: not rendered (Graphviz not found; doctor lists it). Documents above were checked.")
            else:
                dj = json.loads(idx.read_text())
                if dj["failed"] or dj["dfd_balance_errors"]:
                    return fail("diagrams failed", g)
                extras = f"; diagrams generated: {dj['diagrams']}"
        print("smoke: pass" + extras)
        return 0


if __name__ == "__main__":
    sys.exit(main())
