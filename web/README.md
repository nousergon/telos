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

### The tax projection is validated and freshness-graded

The artifact at `TAX_PROJECTION_PATH` (default `../cache/tax_projection.json`) is checked
at read time against the shared contract, `contracts/tax_projection.schema.json`
(override with `TAX_PROJECTION_SCHEMA_PATH`), never trusted on its `schema_version` alone.
Any `1.x` minor is read; decimal strings and ISO dates must be real. An artifact that fails
shows its contract error instead of the panel; an unreadable contract fails closed.

Payment guidance ("pay / don't pay") is shown only for a **current** projection: `as_of` at
most 45 days old (`MAX_GUIDANCE_AGE_DAYS`), not in the future, and before the tax year's last
installment date (Jan 15 of the following year). Otherwise the dated figures stay and the
guidance is withheld with the reason. `npm test` runs these cases on synthetic data.

## Deploy

See `telos-ops/DEPLOY.md` — merges to `telos`/`telos-ops` main auto-deploy to the shared
dashboard EC2 via GHA → SSM.
