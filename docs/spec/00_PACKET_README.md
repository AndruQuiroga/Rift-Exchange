# Rift Exchange — Worlds 2026 private prediction league

> **UI/UX direction update (2026-10-18):** The first demo's glass-inspired styling is **not approved**. Research, alternate directions, and explicit agent guidance live in [`docs/17_VISUAL_DIRECTION_RESEARCH.md`](docs/17_VISUAL_DIRECTION_RESEARCH.md). Compare three non-glass styles in [`design-lab/index.html`](design-lab/index.html). The original [`prototype/index.html`](prototype/index.html) remains an **old behavior reference**, not the visual target.

**Build packet v0.2 · 18 October 2026 · Status: specification + clickable UX prototype + three-style design study**

> Working name only. This is an **invite-only, three-person, fictional-credit prediction game**. Credits have no monetary value, cannot be purchased, withdrawn, exchanged, gifted, or redeemed. No prizes with monetary value, advertising, affiliate links, or payment rails. It is designed *like* a sportsbook for playful competition; **that resemblance is a policy risk**, not a legal or platform-policy exemption. See [Policy & sources](docs/14_POLICY_AND_SOURCES.md) before integrating esports data or publishing.

## North star

The excitement of a real match-day sportsbook, **without real money**, built specifically for three friends who follow League of Legends Worlds. On match day, open the app, compare odds, choose independent predictions, size your stakes, watch the games, see results settle, and talk trash on a shared leaderboard. Build a bankroll over the tournament; do not use fantasy player drafts or normalize points between Bo1/Bo3/Bo5.

**Product principles**
1. **Mobile is the primary interface.** At 360–430px, the app should feel effortless; desktop expands the canvas rather than stretching mobile cards.
2. **Game day is a ritual.** A fresh **1,000 RC per configured match day** is granted once. Savings and previous winnings carry forward, with no arbitrary daily spending cap.
3. **Clarity beats spectacle.** Offered odds, stake, total potential return, *net* profit, lock time, and settlement rules are visible before commitment.
4. **Different match lengths need no score normalization.** Each prediction has an explicit unit: game, series, match day, stage, or tournament.
5. **An engine, not hardcoded screens.** Market definitions, statistics, probability models, outcome graders, and source adapters are versioned and pluggable.
6. **Trust is the real feature.** Immutable accepted odds; server-side clock; atomic wallet operations; corrections are auditable; no backdated predictions.
7. **Ambitious feature-complete destination, vertical-slice delivery.** Build the end-to-end interaction well before broadening the catalog.

## Explore the packet

| File | Purpose |
| --- | --- |
| [01 — Product vision](docs/01_PRODUCT_VISION.md) | Goals, audience, game feel, complete feature ambition |
| [02 — Rules & economy](docs/02_GAME_RULES.md) | Exact virtual-currency and settlement rules |
| [03 — Market catalog](docs/03_MARKET_CATALOG.md) | Winner, score, draft, player props, tournament, combos |
| [04 — UI/UX system](docs/04_UX_DESIGN_SYSTEM.md) | Information architecture, visual language, responsiveness, accessibility |
| [05 — Journeys](docs/05_USER_JOURNEYS.md) | End-to-end flows, empty/loading/error/correction states |
| [06 — Odds](docs/06_ODDS_ENGINE.md) | Probability modeling, repricing, confidence, market gating |
| [07 — Architecture](docs/07_ARCHITECTURE.md) | Modular backend, real-time updates, deployment |
| [08 — Data model](docs/08_DB_SCHEMA.md) | PostgreSQL design, ledger, consistency, migrations |
| [09 — API](docs/09_API_CONTRACTS.md) | REST/SSE contracts, authorization, examples |
| [10 — Data pipelines](docs/10_DATA_PIPELINES.md) | Scheduling, stats, evidence, reconciliation, imports |
| [11 — Admin & integrity](docs/11_ADMIN_AND_INTEGRITY.md) | Admin UX, locking, corrections, safeguards |
| [12 — QA & acceptance](docs/12_TESTS_AND_ACCEPTANCE.md) | Test matrix, mobile UX quality gates |
| [13 — Release plan](docs/13_RELEASE_PLAN.md) | Vertical slices, full vision, fallback paths |
| [14 — Policy & sources](docs/14_POLICY_AND_SOURCES.md) | Official event facts, source links, rights gates |
| [15 — Coding-agent handoff](docs/15_AGENT_HANDOFF.md) | Implementation instructions and acceptance contract |
| [16 — Decisions & backlog](docs/16_DECISIONS.md) | Defaults, tradeoffs, pending decisions |
| [17 — Visual direction research](docs/17_VISUAL_DIRECTION_RESEARCH.md) | 2026 design research, anti-glass rules, three palettes and implementation brief |
| [Visual style lab](design-lab/index.html) | Switch between Arena, Sportsdesk, and Terminal without glass; visual concept only |
| [Schema sketch](contracts/schema.sql) | Initial SQL migration draft (review before production) |
| [API draft](contracts/openapi.yaml) | Minimal typed contract illustrating the vertical slice |
| [Mock demo](prototype/index.html) | Responsive interactive **front-end-only** experience |

## Compare the three non-glass designs

Open [`design-lab/index.html`](design-lab/index.html) in a browser and switch between **A · Arena Editorial (recommended)**, **B · Clean Sportsdesk**, and **C · Match Terminal**. View at mobile and desktop sizes. It is a purely illustrative look-and-feel study, not the existing interactive product demo. Static design screenshot captures are in `design-lab/`. Run `python design-lab/smoke_test.py` for responsive checks.

## Try the mobile-first demo

Open `prototype/index.html` in a modern browser, or serve this folder with `make serve-demo` and visit `http://localhost:8977/prototype/`. It requires **no backend**. It includes market browsing, selection, a bottom bet slip, virtual-credit staking, portfolio history, a three-friend leaderboard, and navigation. It uses **fictional fixtures, sample odds, and local browser state**—not live results, real odds, or server-enforced controls. Reset using **Profile → Reset demo** (or by clearing browser storage).

## Recommended technology

- **Next.js + TypeScript + Tailwind (or CSS variables) + shadcn/ui primitives** for accessible mobile/desktop UI; bespoke components for cards/odds/slip.
- **FastAPI + Pydantic + SQLAlchemy + PostgreSQL** for wallet/markets/quote/settlement and an admin surface.
- **Worker + cron scheduler**, Redis *optional* for distributed notifications/queue; PostgreSQL remains the financial source of truth.
- **SSE first**, polling fallback; no need to invest in an expensive live sportsbook engine for three users.
- **Docker Compose for development**; deploy behind existing reverse proxy and authenticated tunnel or invite-only ingress. Existing Docker Swarm/Portainer environment is a possible target, subject to a fresh infrastructure check.

## First implementation command to your coding agent

Give the agent [15 — Coding-agent handoff](docs/15_AGENT_HANDOFF.md) and this README. Ask it to implement **Slice A through D end-to-end**, using the **new anti-glass guidance** (not the old demo skin), validating 390px and 1440px. Do not accept a plain CRUD dashboard as the final UI.

## Current assumptions (can be configured)

- Three invite-only users; one admin who can participate (with audit controls).
- Start season at Swiss. Opening 1,000 RC once per player, **plus 1,000 RC per day that has at least one actual Worlds match**, including Play-Ins only if we explicitly include them; make grants configurable per season.
- Everything settles after authoritative results are available; **no live/in-play placement** in v1.
- Odds displayed in decimal notation, e.g., `2.40×` **including returned stake**.
- One market outcome per mutually exclusive market on a single ticket. Independent single selections supported; parlays deferred until correlated pricing and cancellation semantics exist.
- Automatic settlement only when the required data fields exist; otherwise queue human review.

## Delivery statement

The packet is a design and engineering specification, not a functioning deployed application. The prototype is intentionally mocked; no external APIs, user accounts, or real data are connected yet.

## Visual previews and runnable smoke check

| Preview | File |
| --- | --- |
| Phone, 390px | [`assets/mobile-preview.png`](assets/mobile-preview.png) |
| Narrow phone, 320px | [`assets/mobile-small-preview.png`](assets/mobile-small-preview.png) |
| Mobile prediction slip | [`assets/mobile-slip-preview.png`](assets/mobile-slip-preview.png) |
| Three-friend leaderboard | [`assets/mobile-league-preview.png`](assets/mobile-league-preview.png) |
| Desktop, 1440px | [`assets/desktop-preview.png`](assets/desktop-preview.png) |

```bash
make verify-contracts  # check the sample OpenAPI YAML + synthetic seed JSON
make smoke-test       # browser-state demo tests at 320, 390, 768, 1440 px
make serve-demo       # optional HTTP server to open the static frontend
```

For `smoke-test`, install Python Playwright and Chromium if not present on your machine; the script currently expects Chromium at `/usr/bin/chromium`. The test is **only a UX-demo smoke test**, not a backend correctness or source-licensing approval. See [16 — Decisions](docs/16_DECISIONS.md) for unconfirmed defaults.
