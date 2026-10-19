# 15 · Implementation handoff for coding agents

**Goal:** Convert this packet into a production-quality **mobile-first private prediction league** *only after the release policy gate is satisfied*. In the meantime build against fictional fixtures/original-IP assets and keep a self-contained frontend demo. The packet is the source of product decisions; code, tests, and schema must make those decisions executable.

## Order of reading

1. `README.md` and `01_PRODUCT_VISION.md` for north star and experience.
2. `17_VISUAL_DIRECTION_RESEARCH.md`, `04_UX_DESIGN_SYSTEM.md`, and `05_USER_JOURNEYS.md` — **updated anti-glass visual requirements** and nonnegotiable behavior contracts.
3. `02_GAME_RULES.md` and `08_DB_SCHEMA.md` — money/game invariants.
4. `03_MARKET_CATALOG.md`, `06_ODDS_ENGINE.md`, `10_DATA_PIPELINES.md` — scope and data dependencies.
5. `09_API_CONTRACTS.md` + `contracts/openapi.yaml` — typed API, quote, and placement flow.
6. `11_ADMIN_AND_INTEGRITY.md`, `12_TESTS_AND_ACCEPTANCE.md` — audit and QA.
7. `13_RELEASE_PLAN.md`, `14_POLICY_AND_SOURCES.md`, and `16_DECISIONS.md` — rollout and blockers.
8. `prototype/index.html` — **design interaction reference**, not trusted code.

## Boundaries

- Do **not** connect payments, crypto, withdrawal, transferable credits, or valuable prizes.
- Do **not** call undocumented LoL esports endpoints or scrape without license.
- Do **not** ship a League-branded sportsbook clone absent Riot approval; demo is generic/original-IP by default.
- Do **not** fake actual fixtures/odds as if verified. Use clearly marked demo data.
- Do **not** use browser localStorage as authoritative financial state in production.
- Do **not** normalize Bo1/Bo3/Bo5 fantasy scoring. We model independent *specific outcomes*.
- Do **not** mark desktop CRUD tables as an adequate mobile product.
- Do not hide exceptions or silently ignore missing match data; result status must show why it is pending.

## Repository architecture to implement

```text
apps/
  web/                        # Next.js app router, TypeScript, responsive screens
    app/(public)/             # signed-out invite, minimal marketing
    app/(app)/today/          # slate, hero wallet, event feed
    app/(app)/events/[id]/    # complete market groups
    app/(app)/explore/        # search/filter
    app/(app)/picks/          # open/settled, detail, receipt
    app/(app)/league/         # 3-friend standings and social
    app/(app)/profile/        # wallet, activity, preferences
    app/(app)/admin/          # privileged tools
    components/              # odds tile, event card, slip, wallet chip, charts
    styles/                  # design tokens, dark theme, motion preferences
  api/                        # FastAPI, SQLAlchemy, alembic
    domain/                   # exact RC math, settlement, quotes, rules
    markets/                  # market templates and validators
    adapters/                 # synthetic, manual, approved-provider later
    routes/                   # endpoints and permission checks
    workers/                  # grant, settlement, outbox
packages/
  contracts/                  # generated API clients or OpenAPI artifacts
  data-fixtures/              # clearly fictional match samples
infra/
  compose.dev.yaml
  swarm/                      # optional swarm and secrets templates
  scripts/                    # provision, migrate, backup, smoke test
```

Keep business logic independent of transport; unit-test with deterministic clocks. Source adapters are replaceable, never directly imported by frontend.

## First tasks — implement in this exact sequence

### Task 0: proof screens and UX states

- Redesign the demo visual language per `17_VISUAL_DIRECTION_RESEARCH.md` (no glass, blur, decorative gradients); implement solid-surface responsive design tokens and reusable accessible components.
- Build 390px and 1440px reference images. Phone first. Test 320px and 200% zoom.
- Page states: loading, empty, scheduled, open, locked, suspended, API unavailable, quote changed, insufficient funds, settled, void/corrected.
- Build UI at original-IP mock data until policy/data gate cleared.

**Accept when:** no horizontal scrolling; odds selectable by touch and keyboard; complete fake flow takes <30 seconds without confusing return with profit.

### Task 1: core database + rules engine

- Create Alembic migration: seasons/users/memberships, official match days, fixtures, markets/outcomes, odds snapshots, tickets/selections, wallets/ledger, result revisions/settlements, audit/outbox.
- Implement opening grant, day grant, late join backfill, negative correction carry-forward (`recovery_due_rc`).
- Implement transactional stake placement under `SELECT FOR UPDATE` wallet lock + server cutoffs + odds snapshot version.
- Implement replay-safe settlement and full reconstruction of balance from journal.

**Accept when:** exhaustive concurrent all-in, quote expiration, idempotency, double grant, replay settlement, correction tests pass.

### Task 2: real end-to-end ticket flow

- Invite-only session auth, CSRF, private/user roles.
- Events → markets → quote → confirm → ticket receipt → portfolio → league leaderboard.
- Make wallet summary appear in nav and in Today hero; no fake optimistic accepted bets.
- Show explicit odds changed and retry to requote, never silently agree.

**Accept when:** mobile placement, logged-out errors, retries and slow network handled gracefully, admin sees audit trail.

### Task 3: admin and result lifecycle

- Fixture editor, template-based market creation, odds inspector, draft cutoffs, suspend/close, grant calendar, result evidence inbox, grading preview, correction proposals and peer-visible audit.
- Human-confirmed adapter first; automated only when approved data exists.

**Accept when:** manually enter fixture outcome, preview all three users' payout impact, confirm once, see reconciled wallet and history.

### Task 4: richer markets and models

- Champion metadata/drafts and player props behind `data_completeness` gates.
- Prediction math library with strict mutually-exclusive outcomes, fair implied probabilities, backtest report, explainable odds source.
- Tournament futures, match-day specials, group activity and awards.
- Same-game multipick parlays only after correlation-aware simulator is tested.

**Accept when:** every shipped template has independently tested grading fixtures for win/lose/void/hold and model calibration checks.

### Task 5: production-quality finish

- PWA, push preferences, spoiler mode, tablet two-column, desktop slip rail, odds movement chart, polished share cards, account statistics, recurrence for future tournaments.
- Dockerized deployment, backup/restore drill, migrator job, secret rotation, smoke test, monitoring and read-only degraded mode.

## Invariants to pin above any PR

`available_rc >= 0` · `stake_rc > 0` · `locked_odds immutable` · `quote_current_at_acceptance` · `grant unique per day/user/season` · `one settlement effect per selection+revision` · `corrections append only` · `no secret/public bet leaks before lock` · `no player-stat market without complete authoritative evidence`.

## PR / work item format

```markdown
# Title
**Slice:** 0/A/B/C/D/E/F/G
**Player outcome:** ...
**Mobile screenshot:** 390px; **desktop screenshot:** 1440px
**States:** loading / empty / happy / expired / error / corrected
**Endpoints/tables impacted:** ...
**Risk:** policy / data / race / UX / performance
**Tests:** unit, integration, Playwright, axe
**Proof:** commands + screenshots + migration plan
**Definition of done:** product, tests, docs, audit, visual reference
```

## Build commands anticipated once scaffolded

```bash
# Commands are *targets* for the future repo; not available in this packet alone.
make dev
make test
make test-e2e
make seed-demo
make migrate
make check-a11y
make screenshots
```

Don't substitute a nonfunctional code stub for requested functioning behavior. After each slice, deliver exact run commands, screenshots, tests, and a demo path; log intentional deferrals in `16_DECISIONS.md`.
