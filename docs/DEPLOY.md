# Deploy the DepGuard demo (Cloud Run) + Langfuse trace

The demo (`depguard/webapp.py`) is a FastAPI app that streams per-alert triage verdicts over
SSE. The frozen `corpus/` is baked into the image, so the container needs **no network and no
API key** to serve verifiable verdicts. Deployment itself needs the owner's `gcloud` auth —
everything below is copy-paste ready.

> **First thing cut if the build slips** (plan house rule 13): the CLI + MCP server + Loom
> stand on their own. This page is a bonus, not load-bearing.

## Run locally

```bash
pip install -e ".[demo]"
uvicorn depguard.webapp:app --reload --port 8080
# open http://localhost:8080  → paste a package.json, click Triage
```

## Build & test the image

```bash
docker build -t depguard-demo .
docker run --rm -p 8080:8080 depguard-demo
curl -s localhost:8080/healthz          # {"ok":true,"corpus_snapshot_id":"depguard-corpus-..."}
```

## Deploy to Cloud Run (owner runs — needs gcloud auth)

```bash
# one-time
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com artifactregistry.googleapis.com

# build in the cloud + deploy (source-based; no local Docker needed)
gcloud run deploy depguard-demo \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --port 8080

# → prints a Service URL like https://depguard-demo-xxxx-uc.a.run.app
```

To also emit **Langfuse** traces from the deployed demo, set the keys as env vars:

```bash
gcloud run services update depguard-demo --region us-central1 \
  --set-env-vars LANGFUSE_PUBLIC_KEY=pk-...,LANGFUSE_SECRET_KEY=sk-...,LANGFUSE_HOST=https://cloud.langfuse.com
```

## Capture the Langfuse trace screenshot (owner)

Each triaged trajectory is replayed 1:1 as OTel GenAI spans and exported to Langfuse when the
`LANGFUSE_*` keys are set (`depguard/otel.py`, wired into `webapp.py`). To produce and capture
a trace:

```bash
export LANGFUSE_PUBLIC_KEY=pk-...  LANGFUSE_SECRET_KEY=sk-...  LANGFUSE_HOST=https://cloud.langfuse.com
uvicorn depguard.webapp:app --port 8080
# in the browser, run a triage (the canned npm example is fine)
```

Then open the trace in Langfuse (a `depguard.triage` root span with one `execute_tool` child
per tool call, carrying `gen_ai.*` semconv attributes) and screenshot it to
**`docs/img/langfuse-trace.png`**. That path is referenced by the README; until the PNG is
dropped in, the README link is a placeholder.
