# 10 · Fixture, roster, draft, stat, and evidence pipelines

## Principle

**Provider adapters must be optional.** The app runs end-to-end with mock fixtures and manually confirmed results. Automation improves timeliness but cannot be required for wallet accuracy, grading, or fun.

## Data-source feasibility snapshot (18 Oct 2026)

| Source | What it's plausibly good for | Restriction / verification required |
| --- | --- | --- |
| Official LoL Esports Worlds primer & schedule | Dates, stages, tournament structure, event status reference | Great as human cross-check; do not assume a public supported schedule API |
| GRID Official Esports Data | Game telemetry, live scores, event files, official event records | **Rights-based license**. Current commercial plans are use-case specific; GRID says sportsbook-like uses must contact sales. No implied free full live access |
| Oracle's Elixir CSV downloads | Historical pro-match player/team stats for offline modeling | Published downloadable match data; confirm 2026 coverage, update frequency, reuse restrictions, required attribution; **not a guaranteed live feed** |
| Riot Data Dragon | Champion metadata, spell/item data, static images | Rights/policy review; it does **not** supply pro-game results |
| Manual admin data | Precisely chosen pre-match markets and confirmed outcomes | Lower automation, but auditable, verifiable, and robust for three users |
| Esports community wikis | Secondary cross-check for aliases and schedule | Respect site terms/API quotas, provenance, not definitive for settlement |

Do not depend on unofficial undocumented endpoints, aggressive scraping, or a fabricated source. Official Riot registration/use requirements and prohibition of betting/gambling functionality are a blocking review item.

## Canonical pipeline

`discover fixtures → normalize IDs → import candidate stats/drafts → validate completeness → propose result revision → verify → grade → ledger payout → social notification`.

Each row carries `source_provider`, `source_record_id`, `fetched_at`, `effective_at`, `source_url_or_evidence`, `raw_hash`, `quality`, `ingestion_version`. Store raw provider payload in immutable archival storage within permitted retention rules if licensed; canonical mapping is versioned. A new observation does not automatically overwrite a confirmed fact.

## Data object needs by market

| Market type | Fields needed | Minimum confidence |
| --- | --- | --- |
| Winner / exact score | series game wins, completion/forfeit flags | Score confirmed |
| Game N winner | game start/finished, winner | Game confirmed |
| Champion pick/ban | ten pick IDs, ban IDs by game, game complete | Draft verified |
| Most banned in day | complete bans for **all included games** | Full-day confirmed |
| Player most kills | full participating roster and all player kills for scoped games | Full-player-stat confirmed |
| First blood | official first blood event/player/team | Event-level verified |
| Penta | authoritative multi-kill event | Event-level verified |
| Objectives | tower/dragon/baron event | Event-level verified |

For a daily 'most banned' market, if one relevant game lacks ban data, hold the entire market. No partial leader settlement.

## Mock/demo mode

Use a deterministic `mock-season-2026` generator with **fictional** teams (Atlas, Nova, Ember, Tide, etc.), fixtures, best-of formats, odds, game stats and source states. Feature flags:

- `USE_MOCK_FIXTURES=true`: never present simulation as real Worlds data.
- `DATA_PROVIDER=manual`: human manages fixtures and confirms scores.
- `ENABLE_PLAYER_PROPS=false` until reliable stat field coverage proven.
- `ENABLE_DRAFT_PROPS=false` until reliable draft data proven.
- `ENABLE_FUTURES=true` if manual grading policy is clear.

Fixtures and markets may be created manually; once real event data source is approved, introduce adapter behind a contract and replay stored fixtures in staging.

## Matching / normalization

Avoid string joins like 'GENG' == 'GEN'. Make internal stable IDs for teams, player aliases, champions, fixtures. Store source-specific aliases, validity interval, and identity confidence. Correct roster changes within fixture snapshots, not today's roster retroactively applied to old matches. Retain patch version for champion catalog and game data.

## Scheduling and timing

UTC instants in DB. Tournament's eligible days determined by authoritative fixture location/calendar (not user's device locale). Lock: before series/game **or draft**, whichever earlier. Never 'infer the draft hasn't started' from broadcast delay when start time is missing. Admin can pre-lock a market; if source delays, default suspension and manual reopen **only if event has definitely not started**; audited.

Job cadence: fixture refresh 10–30 minutes when licensed provider supports; market lock checker every 15–30 seconds (DB enforces cutoff even between polls); scoring refresh post-event 1–5 minutes; historical imports daily. Since there are only three users, low infrastructure load. Verify the provider's rate limits before implementing any cadence.

## Historical analytics roadmap

1. Import licensed historical data to offline dataset.
2. Track tournament, patch, team/player/opponent IDs.
3. Fit win/draft/player models with strict time splits.
4. Backtest only on held-out matches.
5. Plot reliability diagrams, log loss/Brier score, market coverage and ungraded fraction.
6. Deploy a model only when clearly better than baseline; otherwise retain manual odds.

**Source-specific issues to investigate:** timestamp accuracy, BO/game IDs, unique player alias disambiguation, game remakes, Fearless Draft legality, and availability of ban sequence.
