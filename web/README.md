# DealRadar web

Next.js (App Router) frontend: `/dashboard`, `/watchlist`, `/products/:id`, `/deals`, `/war-room`, `/settings`.

```bash
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev   # API origin; must be listed in DEALRADAR_CORS_ORIGINS
npm test            # vitest (formatting, realtime reconnect)
npm run typecheck
```

The API's `DEALRADAR_CORS_ORIGINS` (comma separated, default `http://localhost:3000`) must include the origin the
frontend is served from. Live updates use the API's `/ws` endpoint (token in the query string).

## Browser smoke test

Drives a real browser against a real API (fake JB Hi-Fi site, no Redis): register, track a product by URL, set a
target price, watch the War Room receive a live target hit, then check the dashboard and product chart.

```bash
npm run build && npx next start -p 3000 &
python e2e/server.py &                      # from the repo root venv; API on :8000
NODE_PATH=$(npm root -g) node e2e/smoke.js  # needs `playwright` + a Chromium install
```
