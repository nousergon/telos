# Telos web dashboard

Next.js (App Router) UI at **`/dash`** — year-round federal tax projection from the telos
engine, plus taxable investment gains read from Metron (downstream M0 consumer).

Public URL (when deployed): **https://telos.nousergon.ai/dash**

## Run locally

```sh
cp .env.example .env.local
npm install
npm run dev    # http://localhost:3001/dash
```

Set `METRON_TENANT_ID` + `METRON_PORTFOLIO_ID` to pull investment gains from a running
Metron API. Place a `tax_projection.json` artifact at `TAX_PROJECTION_PATH`.

## Deploy

See `telos-ops/DEPLOY.md` — merges to `telos`/`telos-ops` main auto-deploy to the shared
dashboard EC2 via GHA → SSM.
