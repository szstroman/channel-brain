# Backend deployment to Railway

## What Railway needs

1. **A separate service** in your existing Railway project (or a new one)
2. **Root directory:** `backend` (set in Railway service settings)
3. **Environment variables** (set in Railway dashboard):
   - `ANTHROPIC_API_KEY` — same key as your Streamlit deploy
   - `PINECONE_API_KEY` — same key
   - `CORS_ALLOW_ORIGINS` — comma-separated list of frontend URLs. After Session 9 deploys the frontend, set this to the frontend Railway URL.
   - `ZAPIER_WEBHOOK_URL` (optional) — for lead forwarding
   - `PORT` — Railway sets this automatically, no action needed

## Files that make this work

- `backend/railway.toml` — tells Railway how to build + start the service
- `backend/nixpacks.toml` — installs BOTH parent-directory Python deps AND backend deps
- `backend/main.py` — the FastAPI app itself

## Deploy steps (after Session 8 code is committed)

1. Push everything to your GitHub main branch
2. In Railway: create a new service in your project
3. Connect it to the same GitHub repo
4. In service Settings → set "Root directory" to `backend`
5. In service Variables → set the env vars above
6. Deploy. First build takes 5-10 minutes (installs Python + all deps).
7. Once deployed, hit `https://<service-url>/health` — should return `{"status":"ok"}`

## Verify streaming works in production

Same as local. Use the same `test_stream.ps1` but change the URL to the Railway
service URL. Tokens should stream via SSE just like locally.
