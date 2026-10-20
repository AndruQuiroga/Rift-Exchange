# Leaguepedia live activation — 2026-10-20

Leaguepedia is enabled in production through the authenticated Cargo adapter.
Both API and worker service specifications set `RIFT_LEAGUEPEDIA_MODE=live` and
mount the bot login pair as external Docker secrets. No credential values are
stored in this repository. Core worker health remains separate from coverage.

## Release identity

- Application and deployment source: `a17cdbdc10a29fc65e0067fb9cb66e653689a32c`.
- Release ID: `a17cdbd-20261020T194347Z` (12:43:47 America/Phoenix).
- API: `ghcr.io/andruquiroga/rift-api@sha256:5941f781e7b20260a66fa9bed298d6fa9ce215e47a6b57ce3825fe7a913b2b2b`.
- Web: `ghcr.io/andruquiroga/rift-web@sha256:c0e0798adfed5c0d9357f4601cf450790bd627328a865fca67982c1f17344baa`.
- [CI validation and publication](https://github.com/AndruQuiroga/Rift-Exchange/actions/runs/39485433357)
  passed before deployment: 35 backend tests, lint, fresh migration/schema checks,
  frontend checks, both manifest configurations, and both image builds.
- [Implementation PR](https://github.com/AndruQuiroga/Rift-Exchange/pull/2).

## Verification

The local authenticated probe passed before provisioning the secrets over the
existing private SSH connection. The release's dedicated Leaguepedia job passed
on the production node before the application resumed. A second probe from the
running production worker verified authentication and Cargo access independently
of its container health check.

Before activation, the adapter was compared against the official feed's final
series scores. The same read-only comparison was repeated from the deployed
worker: all six series and 22 games agreed.

| UTC date | Series | Official feed | Leaguepedia |
| --- | --- | --- | --- |
| October 15 | Karmine Corp — Cloud9 Kia | 3–2 | 3–2 |
| October 15 | MVK Esports — FURIA | 3–0 | 3–0 |
| October 16 | Karmine Corp — MVK Esports | 3–0 | 3–0 |
| October 16 | FURIA — Cloud9 Kia | 3–1 | 3–1 |
| October 17 | MVK Esports — FURIA | 3–1 | 3–1 |
| October 18 | Karmine Corp — MVK Esports | 3–0 | 3–0 |

This exposed and fixed the old query's incorrect ban-table fields, midnight UTC
truncation, early-start exclusion, and the Cloud9 sponsor-name difference. The
adapter resolves team redirects, uses an explicitly verified alias where needed,
and rejects duplicate game numbers rather than choosing an ambiguous series.

After deployment, API, worker, web and database containers were healthy, public
readiness and the join page returned HTTP 200, and provider bookkeeping had no
unresolved errors. The separate backup node reported healthy and contained a new
post-release dump. The active release metadata records live mode for subsequent
deployments.

## Coverage at verification

Production contained 30 game records, including 22 with complete final-frame
stats. There were 56 champion-pick markets and eight total-kill markets, sourced
from LoL Esports, alongside the existing winner and futures markets.

Leaguepedia currently supplies game-winner cross-checks. Ban rows can be queried
and parsed, but no game records yet had persisted bans; ban ingestion and market
generation remain deferred. Pre-series player props still need a roster source
and their market implementation. Live credentials alone do not enable those
market families or guarantee future fixture coverage.

Use [the release guide](../../infra/stache/README.md) for the provider probe,
secret provisioning and explicit provider-mode changes.
