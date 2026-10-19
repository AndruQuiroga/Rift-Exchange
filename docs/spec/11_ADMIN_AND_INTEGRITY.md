# 11 · Admin experience, audit, and game integrity

## Role model

Three users start as friends; one may administer but admin power must not alter prior accepted odds or stealth-settle disputed markets. Roles: `PLAYER` and `ADMIN` with granular `manage_schedule`, `manage_markets`, `confirm_results`, `correct_results`, `manage_members`. The admin's own predictions should not be shown to the admin from other players before market lock. All admin edits are logged and later visible at minimum in season audit summary.

## Admin information architecture

`Overview | Fixtures | Markets | Odds Lab | Results | Grants | People | Audit | Sources`

### Overview

Status cards: markets open/closing/held, next event clocks, source freshness, unsettled selections, latest failed job, grants due, biggest pending correction. A simple inbox prioritizes items requiring action.

### Fixture editor

Select stage, format (Bo1/Bo3/Bo5), team IDs, scheduled start, local event date, source aliases. Confirm possible game indices. Validate logically inconsistent combinations. Preview how fixtures appear at 390px and desktop before publish.

### Market builder

Wizard: `Template → Scope → Text/Options → Rule/Tie/Void → Odds → Lock → Evidence → Preview → Publish`. Show odds implied probabilities and warnings, not just a freeform multiplier. Highlight statistical data fields needed to settle. Produce a human-readable market rules snippet automatically. Do not let admin quietly change a rules version if tickets exist.

### Odds Lab

Author estimate vs model estimate, implied probability, consensus overround, source freshness, previous quote snapshots, manual override reason. Preview both outcomes. Bulk price updates require explicit confirmation; payout exposure is fictional but useful for economy diagnostics.

### Results inbox

Evidence panel; completion status per relevant field; `Preview grading` simulation; exact number of winner/loser/void/hold selections and per-user balance effects; then `Confirm & settle`. Disputed data should block settlement. Recovery action creates new revision, reversal entries, reason, and user notices.

### Grant calendar

Show eligible official match days, scheduled/per-user issuance, skipped days, idempotency status. Repair missing grants with audited dry-run preview. New member catch-up policy visible.

## Integrity controls

- Server checks fixture locks inside same DB transaction as placement.
- Odds snapshots immutable, published before accepted ticket; no stale-price auto-accept.
- Player cannot amend/remove accepted predictions.
- Admin cannot create a prediction for a user without impersonation-level audited action (default disabled).
- Data revisions are explicit; corrections do not delete evidence or ledger.
- Role separation where feasible: admin who placed a prediction on that event requires either co-approval from a second friend for contested correction or public peer-visible correction log.
- No public users or API credentials; authenticated sessions, anti-CSRF, rate limiting, secrets only in vault/env, backups encrypted.
- Avoid storing legal names, Riot IDs, location, email when unnecessary. Pseudonymous display names are enough.
- Policy review on external artwork/data before publication.

## Notifications and social fairness

Default: accepted tickets private until outcome lock, then reveal stakes/odds and friend activity. Players can optionally keep **stake amounts** hidden until settlement if group agrees before season start (default all revealed at lock). Do not send alerts pressuring players to risk larger stakes. No real-money-like deposit/add-funds screen.

## Operations runbooks

**Data outage:** suspend unsupported markets, announce cause, continue scores from verified manual data. **Incorrect settlement:** hold new settlement for affected market, propose correction with evidence, preview reversible ledger deltas, execute one revision, notify all users. **Missing stipend:** dry-run grant repair and unique-key-safe backfill. **Site outage near lock:** server UTC cutoff still rules; no backdating; admin may void affected selection only according to published fairness policy, never cherry pick.
