# Channel Brain — FastAPI Backend

Session 2 milestone. One endpoint. Streams answers from Claude.

## What lives here

- `main.py` — FastAPI app with `POST /api/query/stream` and `GET /health`
- `requirements.txt` — backend-specific deps (fastapi, uvicorn, pydantic)

Shared modules (`qa.py`, `clients_config.py`, `indexer.py`) live in the parent
folder and are imported directly. **This backend never duplicates them.**

## Local setup

From the project root (the folder that contains `demo_app.py`):

```
py -m pip install -r backend/requirements.txt
```

If this is your first time running the backend, also install the parent deps
if you haven't already:

```
py -m pip install -r requirements.txt
```

## Environment variables

The backend reads env vars from the PARENT `.env` file — same file
`demo_app.py` uses. No need for a separate one in `backend/`.

Required vars:
- `ANTHROPIC_API_KEY`
- `PINECONE_API_KEY`
- `YOUTUBE_API_KEY` (only needed if you plan to re-index — not required
  for streaming Q&A)

Optional:
- `CORS_ALLOW_ORIGINS` — comma-separated. Defaults to
  `http://localhost:3000,http://127.0.0.1:3000` so the local Next.js dev
  server can call it. Override in production to only allow your Railway
  frontend URL.

## Running locally

From the project root:

```
cd backend
py -m uvicorn main:app --reload --port 8000
```

You should see:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process ...
```

The `--reload` flag makes uvicorn restart when `main.py` changes. Great for
dev, don't use in prod.

## Test 1 — Health check

Open a second PowerShell window and run:

```
curl http://localhost:8000/health
```

Expected:

```
{"status":"ok","service":"channel-brain-api"}
```

## Test 2 — Streaming Q&A

This is the big one. Sends a real question, streams the answer.

Save this to `test_stream.ps1` in the `backend/` folder:

```powershell
$body = @{
    question = "What are Chris' favorite business ideas?"
    client_id = "koerner-office"
    mode = "audience"
    history = @()
} | ConvertTo-Json

curl.exe -N -X POST http://localhost:8000/api/query/stream `
    -H "Content-Type: application/json" `
    -d $body
```

Then run it:

```
.\test_stream.ps1
```

**What to look for:**

1. Almost immediately (within ~1s), you should see a `sources` event with
   the list of source episodes:
   ```
   data: {"type": "sources", "sources": [{"title": "...", "url": "..."}]}
   ```

2. Then a stream of `token` events — one per text chunk from Claude:
   ```
   data: {"type": "token", "text": "Chris"}
   data: {"type": "token", "text": "'"}
   data: {"type": "token", "text": " favorite"}
   ...
   ```

3. Finally a single `done` event:
   ```
   data: {"type": "done", "sources": [...]}
   ```

Concatenate all the `text` fields in order and you get the full answer.

**The important thing:** tokens should start arriving quickly (~1-2s from the
POST) and stream continuously until done. Total time should be ~15-25s for a
synthesis question, same as before, but the visitor sees output starting fast.

## What's NOT built yet (later sessions)

- `GET /api/client/{id}` — client config lookup
- `POST /api/preloaded` — preloaded cache lookup (returns cached answer instantly)
- `POST /api/lead` — email/lead capture
- Auth / rate limiting
- Cap enforcement (currently every request goes to Claude, no monthly limit
  check; we'll add this before deploying to production)
