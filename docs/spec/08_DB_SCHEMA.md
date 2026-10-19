# 08 · Database model and financial invariants

The accompanying `contracts/schema.sql` is a **migration sketch**, not a finished production migration. It covers the core model. Prefer Alembic migrations with tests; don't use schema auto-create on production.

## Entities

**User:** invite identity, roles (`PLAYER`, `ADMIN`), nickname, display preferences. **Season:** event date window, grant rules, initial state, rules version. **Season membership:** exactly three participants by default but no hard three-user schema limit. **Grant day:** eligible tournament-local play date plus grant status/audit.

**Fixture:** Worlds stage, team IDs, best-of, scheduled/actual start, data quality/status. **Game:** one child of fixture, indexed, immutable external IDs when available. **Team/player/champion:** canonical internal IDs and source aliases.

**Market:** published question attached to event scope, market type, rules JSON, closing instant, market state. **Outcome:** set of selectable answers. **Odds snapshot:** historical quote version, source/model/confidence/time; never mutate old snapshot. **Ticket:** one acceptance act; **selections** independent singles by default, each frozen price/stake/rules. **Result revision:** source evidence and authoritative graded outcomes. **Settlement:** per selection, unique version for replay safety, outcome win/loss/void/hold.

**Ledger:** transaction master + per-wallet positive/negative integer entries; cached wallet balance is maintained atomically and periodically reconciled. `available` is not open stakes. **Audit:** append-only admin actions, before/after, actor/time, justification. **Outbox:** post-commit delivery with retry.

## Critical invariants

1. `wallet.available_rc >= 0` **always**, including concurrent purchases and corrections.
2. Uniqueness of each user/day stipend; a scheduled job retry cannot create multiple grants.
3. Each ticket has a unique per-user idempotency key, and accepted selection references exactly one versioned quote.
4. Stake debit and ticket acceptance commit atomically; no 'successful placement' without a ledger debit.
5. Grade each selection once per confirmed result revision; correction ledger reverses previous return instead of deletion.
6. Only confirmed results can settle; source ingest alone is non-authoritative.
7. `market.close_at` and `quote.expiry` validated within placement DB transaction against server time.
8. Canonical order and lock ordering documented and tested under concurrency.
9. Personal wallet and history endpoints cannot read other users' private pre-lock picks.
10. No mutation to `accepted_odds`, `accepted_rules_snapshot`, `accepted_at`, or `stake_rc` after ticket acceptance.

## Double-entry design option

For a proof-grade future design, use the journal to record virtual RC issuance from a `SYSTEM_ISSUANCE` account to a user wallet, stakes from wallet to `OPEN_STAKES` escrow account, losses from escrow to `HOUSE_GAME_POOL`, winnings from escrow and pool to wallet. That ensures total virtual credits can be accounted for. `HOUSE_GAME_POOL` may go negative because there's no real solvency requirement; no money representation and no purchasable credit. A simpler signed-entry ledger works at first but should be reconciled and audited.

`contracts/schema.sql` demonstrates a **signed per-wallet ledger plus transaction idempotency** rather than full balanced journal; if switching to double entry, make that a deliberate schema migration and revise acceptance tests accordingly. Never claim a model is double entry unless entries balance.

## Migration requirements

Migrations are monotonic, independently reversible where safe, and run before web/worker deploy. No destructive changes without backup + rehearsal. Include DB constraints for stake positive, odds positive, unique grants, unique quote version per outcome, and valid state enum / check. Add appropriate `FOR UPDATE`/advisory locks for season days and settlement.

## Corrections and backfill

Data adapters can import an event result revision multiple times safely by external ID + content hash. If a new revision differs from settled facts, propose an admin correction rather than auto-changing wallet. Correction computes `(correct_return - prior_return)` and adds that delta to wallet with explicit journal reference. On a *negative correction* larger than current available wallet (because the user already spent their credits), decide the season's policy **before implementation**: recommended `balance_debt_rc` nonspendable offset, future grants/payouts first recover debt while `available_rc` remains nonnegative, and show transparent 'pending correction adjustment' info. Do not permit negative wallet balance. Simpler alternative: admin-reviewed debt hold with no automatic correction, but must not silently absorb inconsistency.

## Reporting views

For each player: available, open stake, total grants, staked amount, total returns, realized profit excluding grants, winning selections, graded selections, mean accepted odds, daily bankroll chart. For group: final leaderboard (all resolved) and provisional available-only ranking, biggest win and swing, markets by category, data-quality queue depth. Never describe sum of possible returns as present net worth.
