# Phase 4 reference priors

Reference games live in `reference_games`, registered on `rift.models.Base` at import time. They never create fixtures, markets, historical ratings, grants, settlement inputs, or wallet entries. Apply Alembic revision `e6f7a8b9c0d1` before pricing with this code.

## Discover and ingest

From `services/api` using the configured API runtime:

```powershell
python -m rift.reference --discover ../../contracts/reference-events-2026.json --cutoff 2026-10-20T00:00:00+00:00
python -m rift.reference ../../contracts/reference-events-2026.json --cutoff 2026-10-20T00:00:00+00:00
# Continue using the returned next_cursor until it is null:
python -m rift.reference ../../contracts/reference-events-2026.json --cutoff 2026-10-20T00:00:00+00:00 --cursor '[0,20,0]'
```

Use the actual returned cursor, not the example value. Keep the manifest and cutoff fixed during a run. Cursor positions refer to event/match/game indexes; upstream schedule changes can shift positions. Restart from zero after a schedule change or to retry missing stats/drafts; primary-key dedup makes this safe. Repeat full passes to enrich drafts when Leaguepedia becomes available. Provider failures on the primary feed abort the transaction and can be retried; optional draft lookup failures retain the usable final stats.

Discovery calls the existing feed's league catalog and tournament endpoint, accepts a single anonymous league wrapper, rejects explicit identity mismatches and ambiguous anonymous wrappers, and selects this year's completed international tournaments plus the most recently started completed regional tournament per league. Tournament end dates are inclusive; manifest end timestamps are exclusive UTC midnight on the following day. It excludes Worlds, whose games belong to wager fixtures. Latest tournament can be a separately published regional qualifier; inspect the named manifest if the provider splits a season across several tournaments. Discovery does not prove match/stat/ban coverage.

The saved `contracts/reference-events-2026.json` was obtained from the live feed on 2026-10-20: four international tournaments (MSI, First Stand, EWC, Americas Cup), plus latest LCK/LPL/LEC/LCS/CBLOL/LCP splits. The live LCK record is `lck_split_3_2026`, tournament `115548147890329817`, July 28 through September 13 inclusive. No placeholder IDs are used. The coordinating agent also ran a bounded live probe into `rift_dev`: four MSI games and four latest LCK split games, all eight with complete final stats and none missing. Bans: zero; the probe used MockLeaguepedia, so authenticated ban coverage remains unverified. This is eight-game measured coverage, not full-event coverage.

Bounds per batch: at most 16 event windows, four schedule pages per event, 20 match detail reads, 60 final-stat attempts (the adapter may make two window reads per attempt), and one optional draft lookup per match. Function parameters permit bounded increases (12 pages, 100 matches, 300 attempts). Split windows cannot exceed 150 days; international windows cannot exceed 60 days. Only finished ten-player games with matching provider game/team identities and timestamps inside the event and cutoff are stored. Bans require an unambiguous same-series game within one hour, matching blue side and ten canonical picks, and ten distinct bans disjoint from picks. Existing finals remain unchanged when a missing draft is enriched. First-pick pricing stays disabled.

## Weighting and leakage controls

Current completed wager games carry weight 1; international references .5; regional references .25. References must finish before the first scheduled wager-season fixture and the optional historical cutoff; other years and all provider IDs already in canonical games are excluded. Stored regional games from older splits are excluded per league even if retained from an earlier import.

Selection is bounded to the newest 300 eligible stored rows **per category**. Within that candidate set, historical influence is capped at 40 equivalent games, 20 per category and 10 per event, so newest regional games cannot consume the international budget. The two category queries prevent a large regional history from crowding international rows out before weighting. Within each category the scan bound can still omit older events; this is not a full-year coverage guarantee. Minimum draft/kill gates use effective weighted game mass, not physical row count: 30 international games or 60 regional games provide 15 effective games and can unlock kill lines before Worlds. Ban gates use only effective games with validated bans. Current Worlds results retain full weight as they arrive.

Draft pick/ban and team/role champion rates use weighted counts. Kill distributions represent exact quarter-game weights using repeated observations; their existing sample-variance calculation remains an experimental approximation. Player estimates use weighted means and variance, shrink toward role priors, and use champion-conditioned kill priors from current and historical samples only with at least three effective games, shrunk toward six games of role evidence. Duel calls pass champion context. Player identity uses stable feed player IDs; missing IDs contribute only to role/champion evidence. Unknown team mappings never become guessed team identities.

Historical final stats support kills, picks and validated bans. They do not establish CS15, damage share, objective timing, dragon type or soul. Historical references therefore never create fabricated objective observations or zeros for missing fields. Objective priors retain their current timeline evidence requirement.

## Coverage and validation

Batch JSON keeps `coverage: unverified` and reports measured `observed_games`, `with_stats`, `with_bans`, `missing`, `draft_errors`, `stored`, and `enriched`. These denominators describe the inspected batch, not all games in an event. Discovery only verifies catalog identities/date bounds; page caps, feed retention, missing finals, alias differences and Leaguepedia coverage remain independent limitations. Inspect batch reports and stored per-event rows before claiming coverage. Weights are explicit experimental defaults, not calibrated predictive improvements.

Run `python -m pytest tests/test_reference.py -q` for isolated SQLite/provider-fixture tests. Migration parity is checked against model metadata; PostgreSQL `alembic upgrade head` and `alembic check` passed on the local migration database. Full backend, frontend and browser checks are recorded in the phase 4 PR. Use a dedicated test database when running the full suite: its fixtures truncate tables.
