"""The 'paste your package.json' demo surface, honestly staged.

A FastAPI app: `GET /` serves a minimal paste-and-stream page; `POST /triage` streams
Server-Sent Events (per-alert plan → tool steps → verdict with evidence citation). Alerts are
NOT from a live scanner — they are *synthesized* by querying the frozen corpus for advisories
affecting each pasted dependency, so every verdict is reproducible against
`corpus_snapshot_id` (the UI says so, plainly). The triage itself runs the deterministic
`script_arm` (no LLM, no key).

Coverage-aware fallback: if the manifest fails to parse OR no pasted
dependency hits the corpus, we fall back to a canned famous lockfile so the demo shows real
verdicts instead of an empty table — an empty result is the real demo-death, not stale data.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from depguard.snapshot import Snapshot
# transport-agnostic triage core (shared with the CLI; re-exported for tests)
from depguard.triage import CANNED, triage_events  # noqa: F401

app = FastAPI(title="DepGuard demo")
_SNAP = Snapshot()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "corpus_snapshot_id": _SNAP.snapshot_id}


@app.post("/triage")
async def triage(request: Request) -> StreamingResponse:
    body = await request.json()
    ecosystem = body.get("ecosystem", "npm")
    manifest_text = body.get("manifest_text", "")

    async def stream():
        for event in triage_events(ecosystem, manifest_text, _SNAP):
            yield f"data: {json.dumps(event)}\n\n"
            await asyncio.sleep(0.03)  # gentle pacing so the stream is visible in the UI

    return StreamingResponse(stream(), media_type="text/event-stream")


INDEX_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>DepGuard — dependency-CVE triage demo</title>
<style>
 body{font:15px/1.5 system-ui,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem;color:#111}
 h1{margin-bottom:.2rem} .note{background:#fff8e1;border:1px solid #f0d000;padding:.6rem .8rem;border-radius:6px;font-size:13px}
 textarea{width:100%;height:150px;font-family:ui-monospace,monospace;font-size:13px}
 button{padding:.5rem 1rem;font-size:15px;cursor:pointer} select{padding:.35rem}
 .v{border:1px solid #ddd;border-radius:6px;padding:.5rem .7rem;margin:.4rem 0}
 .aff{border-left:4px solid #d33} .safe{border-left:4px solid #2a2} .wd{border-left:4px solid #888}
 .muted{color:#666;font-size:13px} code{background:#f4f4f4;padding:0 .2rem}
</style></head><body>
<h1>DepGuard</h1>
<p class="muted">Which of your dependency-scanner alerts are <em>actually</em> exploitable — with a minimal safe upgrade and a cited advisory range.</p>
<p class="note" id="note">Alerts are derived from a <b>frozen 2026-07 corpus</b> so every verdict is verifiable. This is <b>not</b> a live scanner.</p>
<p><label>Ecosystem: <select id="eco"><option>npm</option><option>PyPI</option></select></label>
&nbsp;<button onclick="load()">example</button></p>
<textarea id="mf" placeholder='{"dependencies":{"lodash":"4.17.20"}}'></textarea>
<p><button onclick="run()">Triage</button> <span class="muted" id="meta"></span></p>
<div id="out"></div>
<script>
const EX={npm:'{"dependencies":{"lodash":"4.17.20","minimist":"1.2.0","axios":"1.3.6","cross-spawn":"7.0.5"}}',
          PyPI:'{"django":"2.2","requests":"2.6.0","pillow":"8.0.0","redis":"4.3.4"}'};
function load(){document.getElementById('mf').value=EX[document.getElementById('eco').value];}
async function run(){
 const out=document.getElementById('out'); out.innerHTML=''; document.getElementById('meta').textContent='running…';
 const body={ecosystem:document.getElementById('eco').value,manifest_text:document.getElementById('mf').value};
 const r=await fetch('/triage',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
 const rd=r.body.getReader(); const dec=new TextDecoder(); let buf='';
 for(;;){const {value,done}=await rd.read(); if(done)break; buf+=dec.decode(value,{stream:true});
  let i; while((i=buf.indexOf('\\n\\n'))>=0){const line=buf.slice(0,i).replace(/^data: /,''); buf=buf.slice(i+2);
   const e=JSON.parse(line); render(e,out);}}
}
function render(e,out){
 if(e.type==='meta'){document.getElementById('note').textContent=e.note;
   document.getElementById('meta').textContent=e.n_alerts+' alert(s) · '+e.snapshot_id;}
 if(e.type==='verdict'){const d=document.createElement('div');
   const cls=e.withdrawn?'wd':(e.affected?'aff':'safe');
   const verdict=e.withdrawn?'WITHDRAWN advisory → not actionable':(e.affected?'AFFECTED':'not affected (false positive)');
   const fix=e.minimal_fixed_version?(' · fix → <code>'+e.minimal_fixed_version+'</code>'):'';
   const ev=e.evidence?(' · <span class="muted">'+e.evidence.advisory_id+' '+e.evidence.range_type+'</span>'):'';
   d.className='v '+cls; d.innerHTML='<b>'+verdict+'</b>'+fix+ev+' <span class="muted">['+e.alert_id+']</span>';
   out.appendChild(d);}
 if(e.type==='done'){const d=document.createElement('div'); d.className='muted';
   d.textContent=e.n_affected+' of '+e.n_alerts+' alert(s) are actually affected.'; out.appendChild(d);}
}
</script></body></html>"""
