# 09 · API contracts & client guarantees

API base `/api/v1`. JSON encoded as UTF-8. OAuth/OIDC or session-cookie login; cookies secure/HttpOnly/SameSite; CSRF protection for cookie-auth writes. `X-Request-ID` returned for troubleshooting. Error responses are stable enough for accessible UI copy.

## Browse endpoints

- `GET /season/current` → current tournament, user match-day grant calendar, UI flags, season-local timezone.
- `GET /events?date=2026-10-23&stage=SWISS` → fixture cards with `format`, `scheduled_start_at`, `state`, summary markets, lock time, pagination.
- `GET /events/{fixture_id}` → detailed stage/series, game indices, upcoming markets, source status. `games[]` lists every game slot (1..best_of) with `state`, `started_at`, `ended_at`, `winner` (A/B), betting `window` (`OPEN`/`UPCOMING`/`LOCKED`/`DONE`/`NOT_NEEDED`), `opens_when`, `closes_at` and `burned_champions` (Fearless: champions played in earlier games). Game N ≥ 2 markets open when Game N−1 ends and close 7 minutes later or when Game N loads; their `params.game_index` names the game.
- `GET /events/{fixture_id}/live` → stored live scoreboard for the current game (`game_index`, `game_clock_s`, `[A, B]` gold/kills/towers/dragons, objective `events`) plus the caller's picks on the series with a `live` progress object. Served from what the worker stored; never calls the provider. Game clock is wall time since the first livestats frame, so pauses inflate it.
- `GET /markets?fixture_id=...&category=DRAFT&state=OPEN` → typed markets, outcome quote snapshots, readable settlement policy, availability reason.
- `GET /markets/{id}/history` → pre-lock quote updates for transparent movement charts.
- `GET /league/standings` → season member summary (`available_rc`, `open_stake_rc`, realized profit, provisional flag), spoiler control.
- `GET /league/activity` → only after-lock friend picks & settled actions; no leaks of pending private tickets.
- `GET /me/wallet` → server-authoritative available, open stake, total grants, ledger cursor.
- `GET /me/tickets?state=OPEN|SETTLED` → user's accepted tickets, frozen odds, returns & evidence.

## Quotes and purchase

```http
POST /api/v1/quotes
Content-Type: application/json

{
  "items": [
    { "outcome_id": "outcome_a", "stake_rc": 400 },
    { "outcome_id": "outcome_b", "stake_rc": 250 }
  ]
}
```

Response:

```json
{
  "quote_id": "qt_01",
  "expires_at": "2026-10-23T16:59:45Z",
  "total_stake_rc": 650,
  "available_after_rc": 600,
  "conditional_return_if_all_win_rc": 1498,
  "items": [
    {"outcome_id":"outcome_a","stake_rc":400,"odds":"1.62","odds_version":7,"potential_return_rc":648},
    {"outcome_id":"outcome_b","stake_rc":250,"odds":"3.40","odds_version":3,"potential_return_rc":850}
  ]
}
```

The sample assumes an available balance of 1,250 RC (not inferred from any actual account).

```http
POST /api/v1/tickets
Idempotency-Key: a-v4-client-generated-uuid
Content-Type: application/json

{ "quote_id": "qt_01", "confirm_odds_versions": {"outcome_a":7,"outcome_b":3} }
```

Response: `201 Created` or `200 OK` on same idempotent retry, with immutable ticket details. Any changed quote version → `409 ODDS_CHANGED`, reason and new quote; lock → `409 MARKET_CLOSED`; insufficient wallet → `409 INSUFFICIENT_CREDITS`; expired quote → `409 QUOTE_EXPIRED`.

**Critical API requirement:** `quote` is informational until ticket acceptance; `tickets` does not trust client-provided odds, stake, market status, or wallet amount. Store the quote payload server-side or signed and verify against DB current version inside a transaction. Enforce ticket total and all market validations again. A quote should expire in 15–30 seconds or immediately when its outcomes change/close.

## Results and admin API

- `GET /admin/results/inbox` shows pending fixtures & source evidence.
- `POST /admin/events/{id}/results/propose` records result observation, not settlement.
- `POST /admin/results/{id}/confirm` confirms verified result revision and queues grading.
- `POST /admin/settlements/{id}/preview` shows selection status and per-user return effects.
- `POST /admin/settlements/{id}/execute` grade atomically and audit actor.
- `POST /admin/results/{id}/correct` appends correction proposal (not a destructive update).
- `POST /admin/markets` / `PATCH ...` require role, validation, and audit; forbid editing rules for accepted selections.
- `POST /admin/grants/reconcile` idempotently fills missing grant days.
- `GET /admin/audit` shows timestamped actions; no deletion API.

## SSE streaming

`GET /api/v1/stream` authenticated; events `{id, type, occurred_at, entity_id, revision}`. Client treats stream as **invalidation hints**, fetches canonical data by REST; handles reconnect and stale last-event ID. Private events (wallet, unclosed tickets) scoped to user; shared group event types disclose only after lock.

## Example error envelope

```json
{
  "error": {
    "code": "MARKET_CLOSED",
    "message": "This prediction locked when the draft began.",
    "details": {"market_id":"m_123", "closed_at":"2026-10-23T16:58:00Z"},
    "request_id": "req_abc"
  }
}
```

No raw database exceptions or internal model confidence inputs in user-facing errors. Use structured `code` to drive translations and assistive announcements. All writes require secure origin + CSRF/anti-replay strategy, rate limits appropriate for three users, and admin audit entries.

## Nonfunctional/compatibility

OpenAPI generated from code and reviewed in CI, typed TS client from OpenAPI, additive versioned responses. Test empty fields, missing data, duplicate idempotency keys, long market names, emoji nicknames, and network retries. Keep `contracts/openapi.yaml` as an **illustrative starting contract**, then replace with runtime-generated authoritative spec.
