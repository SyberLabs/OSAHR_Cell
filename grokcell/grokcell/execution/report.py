"""Self-contained, escaped presenter report generated from actual run records."""
from __future__ import annotations

import html
import json
from pathlib import Path


def render_report(runs: list[dict], *, title="GrokCell | SyberLabs decision execution") -> str:
    """No remote assets, network requests, model calls, or executable candidate text."""
    sections = []
    for run in runs:
        audit = run["audit"]
        journal = audit["journal"]
        receipts = audit["accepted"]
        evidence_mode = "LIVE PROVIDERS" if audit["live_execution_enabled"] else "OFFLINE FIXTURES"
        verifier = audit.get("verification_mode", "offline")
        steps = "".join(
            '<tr><td>' + html.escape(item["step"]) + '</td><td>' + html.escape(item["operation"].upper())
            + '</td><td>' + html.escape(item["status"]) + '</td><td>' + str(item["reserved"])
            + '</td></tr>' for item in journal)
        sections.append(f'''<section class="run" id="{html.escape(run['workflow'])}">
<div class="eyebrow">{evidence_mode} · {html.escape(verifier.upper())} VERIFICATION</div>
<h2>{html.escape(run['workflow'].replace('_', ' ').title())}</h2>
<p>{html.escape(run['description'])}</p>
<div class="metrics"><div><strong>{audit['calls']}</strong><span>Recorded adapter calls</span></div>
<div><strong>{audit['revision']}</strong><span>Accepted-state revision</span></div>
<div><strong>{'PASS' if run.get('replay_equal') else 'NOT RUN'}</strong><span>Process-restart replay</span></div>
<div><strong>{audit['liability_microusd']}</strong><span>Accounted liability (µUSD)</span></div></div>
<div class="boundary"><b>Admission is not deployment permission.</b> Receipt scope: {html.escape(audit.get('admission_scope','offline_preview'))}.</div>
<div class="columns"><div><h3>Candidate artifact</h3><pre>{html.escape(run['candidate'])}</pre></div>
<div><h3>Recorded execution</h3><table><thead><tr><th>Step</th><th>Operation</th><th>Status</th><th>Reserved µUSD</th></tr></thead><tbody>{steps}</tbody></table></div></div>
<details><summary>Inspect receipts and complete audit</summary><pre>{html.escape(json.dumps(audit, indent=2))}</pre></details>
</section>''')
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>''' + html.escape(title) + '''</title><style>
:root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#dbe9f3;background:#101a25;color-scheme:dark}*{box-sizing:border-box}body{margin:0}main{max-width:1200px;margin:auto;padding:48px 30px}.brand{font-size:14px;letter-spacing:.22em;color:#9ac4cf}h1{font-size:clamp(36px,5vw,62px);max-width:900px;line-height:1.07;letter-spacing:-.035em;margin:28px 0 20px}h2{font-size:30px;margin:12px 0}h3{font-size:17px}p{color:#bccbd8;line-height:1.7;max-width:870px}.intro{font-size:19px}.status{border-left:4px solid #e1ba72;padding:14px 18px;background:#27303a;color:#f5dfb3;margin:24px 0}.rail{display:flex;gap:9px;flex-wrap:wrap;padding:22px 0}.rail span{border:1px solid #355366;border-radius:5px;padding:10px 16px;font-size:13px;letter-spacing:.1em}nav{display:flex;gap:12px;margin:16px 0 32px}button{background:#204356;border:1px solid #528895;color:#e8f6f9;font:inherit;border-radius:6px;padding:10px 18px;cursor:pointer}button[aria-pressed=true]{background:#aad9d9;color:#13212a}.run{border-top:1px solid #385062;padding-top:32px;margin:30px 0 60px}.eyebrow{font-size:12px;letter-spacing:.1em;color:#e1ba72}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:28px 0}.metrics div{background:#192b39;padding:22px;border:1px solid #294252;border-radius:7px}.metrics strong{font-size:29px;display:block}.metrics span{font-size:12px;color:#a3bdc9}.boundary{background:#1b3540;border-left:3px solid #7bbbbd;padding:14px;font-size:14px;overflow-wrap:anywhere}.columns{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0c151e;border:1px solid #294252;border-radius:7px;padding:18px;font:12px/1.7 ui-monospace,monospace;max-height:510px;overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px}td,th{text-align:left;padding:12px 8px;border-bottom:1px solid #294252;overflow-wrap:anywhere}summary{cursor:pointer;padding:15px 0;color:#aad9d9}footer{border-top:1px solid #385062;padding:28px 0;color:#94a8b6;font-size:13px;line-height:1.7}@media(max-width:760px){main{padding:30px 18px}.metrics{grid-template-columns:1fr 1fr}.columns{grid-template-columns:1fr}nav{flex-wrap:wrap}}
</style></head><body><main><div class="brand">SYBERLABS / GROKCELL</div>
<h1>Models propose.<br>Execution earns acceptance.</h1>
<p class="intro">A small decision-execution contract for bounded work, inspectable evidence, and recoverable state. Two workflows. One runtime.</p>
<div class="status"><b>Technical preview, not a production or performance claim.</b> Provider and verification modes are labeled on each run. Fixture calls are not live Jev or Hugging Face calls. Passing these contracts is not universal correctness.</div>
<div class="rail"><span>READ</span><span>DECIDE</span><span>CALL</span><span>CHECK</span><span>ADMIT</span><span>YIELD</span></div>
<nav aria-label="Workflow selection"><button data-show="all" aria-pressed="true">Both workflows</button><button data-show="repair" aria-pressed="false">Component repair</button><button data-show="dependency" aria-pressed="false">Dependency assessment</button></nav>
''' + "".join(sections) + '''<footer><b>Evidence before claims.</b> This report contains recorded execution; navigation does not rerun a model. In offline repair mode, verification compares known fixture bytes and does not execute candidate Python. Dependency checks validate supplied facts and preserve required human review; they do not establish compatibility. No autonomous deployment, cost-superiority, or external-validation claim is made.</footer></main>
<script>document.querySelectorAll('button[data-show]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('button[data-show]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));document.querySelectorAll('.run').forEach(s=>{s.hidden=b.dataset.show!=='all'&&s.id!==b.dataset.show;});}));</script></body></html>'''


def write_report(path: Path, runs: list[dict]):
    with Path(path).open("x", encoding="utf-8") as handle:
        handle.write(render_report(runs))
