# Exchange builders — phase 4

Status: implemented on `feat/exchange-builders-p4`, stacked on phase 3 (#5).

## Two timing windows

The exchange remains the only money path. All selections are independent singles.

- Winner, objectives and draft predictions retain their pre-draft cutoff.
- Lane duels and kill lines open when the game feed provides its starting lineup and champions. They close three minutes after the first game frame, or on first blood if earlier. A missing lineup never opens a window.
- The feed exposes champions after draft, not during champion select. There is no claim of a live-draft integration.
- The server checks the recorded window both when creating a market and when quoting/accepting a ticket. The worker polls every five seconds during an eligible window. A later-discovered cutoff refunds late selections.
- Times currently use elapsed feed-frame time from the first frame. Pauses are not subtracted; broadcast lag and the live polling cadence need measurement during an actual game.

## UI

Players previews expected lane opponents before load, without prices. Once confirmed it shows each player's champion and a ticking countdown. Kill lines show both compositions and the same countdown. Both builders disable locally at cutoff and refresh their server state every two seconds. Draft and objective controls retain their existing timing.

## Reference data

Historical priors belong in a separate reference table, never in wager fixtures. Explicit event windows select this year's international events and the latest regional split. Imports must be bounded, resumable and deduplicated by official game ID. Re-running a batch may enrich a missing draft, without changing existing final statistics.

Current Worlds observations carry full weight. Historical samples carry lower weights with a capped contribution so a large regional history does not drown out the current event. Only fields actually provided count: missing historical CS at 15, damage share or objective timelines do not become zeros.

The feed-derived event manifest and import commands are in [the reference-data runbook](../reference-data.md). A live probe discovered 10 eligible event windows and imported eight final-stat records (four MSI, four LCK); it did not verify bans.

Reference coverage and a live early-game window must be reported separately from deterministic test results. Deployment and an authenticated Leaguepedia backfill are separate operational actions.
