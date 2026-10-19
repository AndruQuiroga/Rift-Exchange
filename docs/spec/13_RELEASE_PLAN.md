# 13 · Full ambition, realistic build order

**We are not cutting the end-state feature set.** Instead, we deliver **vertical slices** in an order that protects UX and correctness. The exact October 2026 window is short, so use manually seeded match results if data access is unresolved.

## Slice 0 — Design proof and policy review

Deliver: mobile 390px, desktop 1440px visual reference; component tokens; mock slate; interactive selections/Slip/Portfolio/League; 3-friend usability walk-through; policy/data license checklist. The included static `prototype/index.html` is the first proof, not production UI. Gate: all three friends can understand what they are picking, staking, and potentially returning.

## Slice A — Real wallets, users, and standings

Invite-only auth + three members; seasons, once-per-match-day 1,000 RC grants; opening grants; immutable ledger, server-verified balances; wallet, portfolio history, provisional leaderboard; atomic operations and idempotency tests. Gate: simulating network retries/concurrency never creates credits or debt accidentally.

## Slice B — Full pre-match selection experience

Fixture/event cards; winner & exact-score markets; price snapshots; market cutoff and state; server quote → confirm → atomic ticket purchase; mobile slip, receipt, error/conflict states; SSE updates. Gate: first complete prediction on mobile under 30 seconds, front and back both production-quality.

## Slice C — Admin and settlement

Fixture editor, manual odds editor with implied probability warnings, pending results inbox, score grading, void/hold, correction/reversal, grant calendar repair, audit and health. Gate: every ledger entry traceable to an event, no double payout, clear why any prediction has not resolved.

## Slice D — LoL-specific richness

Champion metadata/IDs (pending rights approval), draft markets, champion picked/banned by game and across series, 'most banned day' complete-data validation, Fearless Draft state, player kill props, conditional bands, first-blood and objective props **only with trusted data**. Gate: at least one full game can be ingested, verified, and automatically graded by each supported market family.

## Slice E — Odds intelligence

Manual priors with odds versioning; Elo baseline; scoreline distributions; model backtest; patch/team/champion smoothing; player prop simulations; confidence UI; manual override reason. Gate: backtested forecast quality better than naive base rate or model flagged experimental; prices are not artificially shown as certain.

## Slice F — Social and tournament depth

Futures, daily specials, after-lock activity feed, 3-user compare, weekly awards, profile history, bankroll timeline, standings day-by-day replay, season recap, notification opt-in, PWA install/offline read-only, desktop persistent slip, search/favorites, market history. Gate: fun and smooth enough to reuse for a new tournament with seed data only.

## Slice G — Advanced market construction

Same-event combination pricing from joint simulations, odds live movement under pre-match updates, editor-submitted market ideas, custom models, source adapters, automated results and source-quality monitoring. Gate: no correlated-price errors or impossible resolution contracts in simulation/regression.

## Risk-adjusted launch approach for Worlds 2026

Given the Oct 23 Swiss start: **target Slices 0–C first**, potentially pre-seeding a curated slate and hand-confirming results while data-provider rights remain unsettled. D–G proceed behind flags rather than blocking the game. Do not promise a date or ship less-safe wallet code to meet a match. If the policy review says even a private deployed LoL-linked betting-style game is not allowed, keep the engine and UI as a local mock-data prototype, seek permission, or change into a non-wagering prediction points format.

## Structured backlog scoring

Prioritize by `(player delight × usage frequency × trust) / complexity`, but do not let this push visual design or integrity late. Each slice has mobile UX tasks and tests, not a backend-only phase. Keep ambitious discovery issues in GitHub, with explicit source/licensing dependencies.
