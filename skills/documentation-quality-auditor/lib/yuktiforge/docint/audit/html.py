"""coverage.html: a static, script-free page that shows the audit's measurements side by side (no single score)."""
from __future__ import annotations

import html
from typing import Any

e = lambda t: html.escape(str(t), quote=True)

CSS = ("body{font-family:Helvetica,Arial,sans-serif;max-width:1050px;margin:24px auto;padding:0 16px;color:#1F2937;background:#fff}h1{font-size:24px}h2{border-bottom:1px solid #CBD5E1;padding-bottom:4px;margin-top:28px}"
       "table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}th,td{border:1px solid #CBD5E1;padding:5px 8px;text-align:left;vertical-align:top}th{background:#F1F5F9}"
       ".PASS{color:#047857;font-weight:700}.FAIL{color:#B91C1C;font-weight:700}.NOT_TESTED{color:#B45309;font-weight:700}.bar{background:#E5E7EB;height:10px;border-radius:5px;width:160px;display:inline-block}.bar i{display:block;height:10px;border-radius:5px;background:#1D4ED8}"
       "@media (prefers-color-scheme: dark){body{background:#111827;color:#E5E7EB}th{background:#1F2937}th,td{border-color:#374151}.bar{background:#374151}}")


def bar(n: int, total: int) -> str:
    pct = 0 if total == 0 else round(100 * n / total)
    return f'<span class="bar"><i style="width:{pct}%"></i></span> {n}/{total}'


def render(ev: dict[str, Any]) -> str:
    gates = "".join(f"<tr><td>{e(k)}</td><td class='{e(v['status'])}'>{e(v['status'])}</td><td>{e(v['detail'])}</td></tr>" for k, v in ev["gates"].items())
    evd = ev["evidence"]
    docs = "".join(f"<tr><td>{e(d['document'])}</td><td>{e(d['audience'])}/{e(d['depth'])}</td><td>{bar(d['with_evidence'], d['statements'])}</td><td>{d['verified_with_valid_pointer']}/{d['verified']}</td>"
                   f"<td>{e(', '.join(f'{k} {v}' for k, v in d['labels'].items()))}</td></tr>" for d in evd["by_document"])
    scope = "".join(f"<tr><td>{e(t)}</td><td>{bar(v['documented'], v['total'])}</td><td>{e(', '.join(v['undocumented'][:8]) or '-')}</td></tr>" for t, v in ev["coverage"]["scope"].items())
    types = ev["coverage"]["document_types"]
    cons = "".join(f"<tr><td>{e(c['check'])}</td><td>{e(c['severity'])}</td><td>{e(c['detail'])}</td></tr>" for c in ev["consistency"]) or "<tr><td colspan=3>none</td></tr>"
    rev = ev["review"]
    states = "".join(f"<tr><td>{e(v['document'])}</td><td>{e(v['state'])}</td><td>{e(', '.join(f'{s}: {st}' for s, st in v['sections'].items()))}</td></tr>" for v in rev["documents"].values())
    fresh = ev["freshness"]
    fr = "Not tested: " + e(fresh["reason"]) if not fresh["checked"] else f"{fresh['stale_or_missing']} stale or missing evidence record(s) of {fresh['evidence_checked']} checked; by kind: {e(fresh['by_kind'])}; sections affected: {e(fresh['sections_affected'])}"
    inv = ev["invention"]
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Documentation audit</title><style>{CSS}</style></head><body><h1>Documentation audit</h1>"
            f"<p>Knowledge model scan {e(ev['model_scan_id'])} &middot; repository {e(ev['repository'].get('name'))} &middot; revision {e(ev['repository'].get('revision') or 'unknown')}. "
            "The measurements below are reported separately on purpose: a single number would hide which one is failing.</p>"
            f"<h2>Gates</h2><table><tr><th>Gate</th><th>Result</th><th>Detail</th></tr>{gates}</table>"
            f"<h2>Evidence completeness</h2><p>{evd['statements']} statements; {bar(evd['with_evidence'], evd['statements'])} cite evidence; {evd['verified_with_valid_pointer']} of {evd['verified']} VERIFIED statements have a valid pointer. Labels: {e(evd['labels'])}.</p>"
            f"<table><tr><th>Document</th><th>Profile</th><th>With evidence</th><th>VERIFIED with valid pointer</th><th>Labels</th></tr>{docs}</table>"
            f"<h2>Freshness</h2><p>{fr}</p>"
            f"<h2>System scope coverage</h2><table><tr><th>Entity type</th><th>Mentioned in at least one document</th><th>Not mentioned (first 8)</th></tr>{scope}</table>"
            f"<h2>Document type coverage</h2><p>Present: {e(', '.join(types['present']))}. Offered but missing: {e(', '.join(types['missing']) or 'none')}.</p>"
            f"<h2>Consistency</h2><table><tr><th>Check</th><th>Severity</th><th>Detail</th></tr>{cons}</table>"
            f"<h2>Invention checks</h2><p>{len(inv['unsupported_identifiers'])} quoted identifier(s) not in the model; {len(inv['fabricated_requirements'])} fabricated requirement(s); {len(ev['privacy'])} privacy issue(s).</p>"
            f"<h2>Review states</h2><table><tr><th>Document</th><th>State</th><th>Sections</th></tr>{states}</table><p>{e(rev['note'])}</p></body></html>")
