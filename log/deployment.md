# Deployment Guide: Local Backend + Public Dashboard

**Date:** 2026-02-23
**Architecture:** Backend on local machine → Cloudflare Tunnel → Vercel (React frontend)

```
Internet User → Vercel (static React app)
                  ↓ API calls
                Cloudflare Tunnel (public URL)
                  ↓
Your Machine → FastAPI (:8000) → SQLite (data/pnl_weighted.db)
```

---

## Setup Summary

### What was changed

| File | Change |
|------|--------|
| `backend/config.py` | `FRONTEND_ORIGIN` now supports comma-separated origins → `ALLOWED_ORIGINS` list |
| `backend/main.py` | CORS middleware uses `ALLOWED_ORIGINS` instead of single origin |
| `.env` | Added `FRONTEND_ORIGIN=http://localhost:5173,https://hyper-strategies-pnl-vercel.vercel.app` |
| `scripts/start-public.sh` | New script — starts backend + Cloudflare Tunnel together |

### Vercel project settings

- **Repo:** `0xjayfi/hyper-strategies` (branch: `main`)
- **Root Directory:** `frontend`
- **Framework Preset:** Vite
- **Build Command:** `npm run build`
- **Output Directory:** `dist`
- **Environment Variable:** `VITE_API_URL` = `https://<tunnel-url>.trycloudflare.com`

---

## Day-to-Day Operations

### Start the backend + tunnel

```bash
# Use tmux so it survives SSH disconnects
tmux new -s hyper
cd ~/hyper-strategies-pnl-weighted && ./scripts/start-public.sh
# Ctrl+B then D to detach
# Reconnect later: tmux attach -t hyper
```

### When tunnel URL changes (every restart)

1. Copy the new `https://....trycloudflare.com` URL from terminal output
2. Vercel → Settings → Environment Variables → update `VITE_API_URL`
3. Vercel → Deployments → three dots → Redeploy

### Push code changes to Vercel

Vercel auto-deploys on every push to `main`:

```bash
# Option A: Push feature branch directly to main
git push origin feat/pnl-weighted:main

# Option B: Merge then push
git checkout main
git merge feat/pnl-weighted
git push origin main
```

---

## Key Details

### What stays on your local machine
- SQLite database (`data/pnl_weighted.db`)
- Nansen API key (`.env`)
- Backend process (FastAPI + Uvicorn)

### What's hosted on Vercel
- Static React/TypeScript frontend (no secrets, no server-side code)
- `VITE_API_URL` env var pointing to tunnel

### SSH disconnect behavior
- **Without tmux/screen:** backend + tunnel die, dashboard goes offline
- **With tmux/screen:** processes survive, dashboard stays up
- Vercel frontend stays deployed regardless (just can't reach backend if tunnel is down)

### Tunnel URL stability
- **Free quick tunnels** (`trycloudflare.com`): URL changes every restart
- **Named tunnels** (free Cloudflare account): permanent URL, run `cloudflared tunnel login` once to set up

### CORS config
- `.env` → `FRONTEND_ORIGIN=http://localhost:5173,https://hyper-strategies-pnl-vercel.vercel.app`
- Comma-separated, parsed in `backend/config.py` into `ALLOWED_ORIGINS` list
- Must restart backend after changing `.env` for CORS to take effect

---

## Troubleshooting

### CORS errors in browser console
- Backend needs restart to pick up `.env` changes
- Check: `curl -s -H "Origin: https://hyper-strategies-pnl-vercel.vercel.app" http://localhost:8000/` should return `access-control-allow-origin` header

### "Address already in use" on port 8000
```bash
# Find and kill the old process
lsof -i :8000 | grep LISTEN
kill <PID>
# Then restart
./scripts/start-public.sh
```

### Vercel builds as Python/FastAPI instead of Vite
- Vercel project settings → Root Directory must be `frontend`
- Framework Preset must be `Vite`

### Dashboard loads but shows no data
- Check if backend + tunnel are running on your machine
- Check if `VITE_API_URL` in Vercel matches the current tunnel URL
- Check backend logs in terminal for errors
