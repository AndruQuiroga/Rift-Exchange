# Rift Exchange

Private, invite-only prediction league for three friends following LoL Worlds 2026. Play credits only: no purchase, cash-out, transfer or prizes.

Everything runs without manual input (D-008): the worker pulls fixtures and results from the lolesports feed, prices markets from a team-strength model, locks them at the scheduled start, settles them from verified game data, and pays the daily grants.

## Layout

| Path | What |
| --- | --- |
| `services/api` | FastAPI API, worker, odds engine, Alembic migrations (Python 3.13, uv) |
| `apps/web` | Next.js mobile-first client; `/api/*` is proxied to the API |
| `infra/compose.yaml` | Postgres + migrate + api + worker + web |
| `docs/spec` | Product/engineering spec (build packet v0.2) and the decisions log |
| `docs/screens` | Reference screenshots from the end-to-end walkthrough (390px and 1440px) |
| `design` | Earlier prototype and design-lab studies (reference only) |

## Run locally

```bash
createdb rift            # or point RIFT_DATABASE_URL at any Postgres 16
make setup migrate
make cycle               # first sync: history, Worlds schedule, ratings, markets
make invite ADMIN=1      # prints an invite code; share http://localhost:3000/join?code=<code>
make invite              # one per friend
make api                 # :8000
make worker              # keeps everything moving (60s loop)
make web                 # :3000
```

Or with Docker: `docker compose -f infra/compose.yaml up --build`, then `docker compose -f infra/compose.yaml exec api rift invite --admin`.

## Configuration

For Stache hosting options, verified infrastructure observations, launch requirements,
and the recommended agent deployment interface, see [the deployment assessment](docs/deployment/stache.md).
Run `./infra/stache/preflight.ps1` from PowerShell for read-only SSH/Swarm checks.

Environment variables (prefix `RIFT_`, see `services/api/src/rift/config.py`): `DATABASE_URL`, `COOKIE_SECURE` (set `true` behind HTTPS), `LEAGUEPEDIA_MODE` (`mock` until the bot account exists, then `live` with `LEAGUEPEDIA_BOT_USER`/`LEAGUEPEDIA_BOT_PASSWORD`), `SETTLE_DELAY_SECONDS`, `HOLD_VOID_AFTER_HOURS`.

## Tests

- `make test`: money invariants against Postgres (concurrent all-in, idempotent retries, odds-change rejection, corrections with debt recovery), a scripted full series lifecycle through the worker, the API, and web typecheck/lint.
- `make e2e CODES="…"`: drives the real stack in Chromium at 320/390/768/1440px and refreshes `docs/screens`.
