# 05 · Key interaction flows & state inventory

## Flow A — first visit (new friend)

Invite link → passwordless login or admin-provisioned credentials → display username/avatar choice → season rules in three sentences → wallet grant explained → optional 'show spoilers' and timezone setting → Today. Do not require Riot sign-in. Onboarding checklist is optional; skip immediately to games if invited user understands them. The first session should explain '2.30× is total return, not profit' via inline helper.

Acceptance: all 3 users have isolated accounts and same historical grants, invites cannot be replayed, post-join grants backfill deterministically, nothing calls a Riot API.

## Flow B — placing two singles

1. Home lists upcoming match day and odds. User taps `Atlas 1.62×` → tile selected (accessible toggle), floating slip appears (`1 pick`).
2. User taps `Game 1 Orianna picked 2.75×` → slip shows `2 picks`.
3. Tap slip → bottom sheet opens with market labels, two editable integer RC stake fields, outcome prices, and conditional total return, net, and remaining available.
4. Enter stakes 400 + 250; frontend highlights if >available but doesn't pretend wallet is authoritative.
5. Review → server requests `POST /quotes`, returns price versions and expiry; if any changed, render side-by-side **was** and **now** and require confirmation.
6. Tap `Place picks`; server atomically debits 650 and inserts two single selections; confirmation shows accepted odds and ID. Persist receipt.
7. If network fails, client queries by idempotency key before retrying; no duplicate funds spent.

Each selection may be resolved independently. When one wins and one loses, return only winner. Portfolio displays detailed realized profit per selection.

## Flow C — pre-event odds change

Update arrives while user is browsing: tile flashes quietly, then settles. If tile is selected but user hasn't submitted, slip shows 'Price updated'. User opens slip: old price strike-through, new price beside it. `Confirm new odds` explicitly required; if event has locked, user can remove or save the pick as a failed attempt (not financial transaction). Never take altered odds without consent.

## Flow D — live match day

At configured grant moment scheduler creates a ledger grant for every player; Today hero shows it once via nonblocking toast. Each series transitions Scheduled → Locked → Live → Complete. UI is view-only after lock; optional picks revealed to friends at lock, not before. If result arrives: awaiting data → grading → win/loss/void, with a brief update; if only game scores available, score-based markets settle and player props wait.

## Flow E — settled portfolio and rivalry

My Picks tabs: `Open`, `Settled`, `All`. Cards include snapshot label, odds, stake, return, outcome, lock/settled time, proof/correction history. League ranks 3 players, shows today's swings, biggest hit, and a 'compare our reads' view after market lock. A friend can view other users' settled picks but not their unclosed confidential picks by default.

## Flow F — admin result pipeline

Admin Results Inbox receives game-series candidate with source, ID match, timestamps, and confidence. Score can be confirmed; all score markets preview grading before execution. For Champion Most Banned market, if draft data is missing for one game, show `HOLD`, not guessed result. Admin confirms, worker commits payouts idempotently, and sends SSE events. Correction shows original vs changed result, user wallet deltas, and requires reason + second confirmation for high-impact adjustments.

## Flow G — no connection, small screen, failure

- **Offline at browse:** cached slate can be browsed read-only with stale banner; `Place` disabled unless server reachable.
- **Checkout timeout:** show 'Checking whether your picks were received'; GET ticket by idempotency key; never confidently declare failure if status unknown.
- **Insufficient funds:** show `Available 240 RC; your slip needs 300 RC` with clear editable fields and a one-tap 'reduce total proportionally' optional action.
- **Locked market:** show locked, why, and next available event; preserve other slip lines.
- **Delayed data:** settle what can be proven; precise 'Awaiting verified Game 2 draft data' banner.
- **Admin correction:** show correction notice, original return, reversal, corrected return, reason.
- **No matches:** beautifully designed upcoming date view, favorites, season leaderboard, and open long-term predictions.
- **No picks:** show attractive empty state with 'Explore markets', not placeholder charts.

## State names for component/storybook coverage

`idle, hover, focus, selected, price_change, pending, quote_expired, suspended, locked, accepted, rejected, awaiting_data, settle_queued, won, lost, void, corrected, offline, empty, loading, partial_failure`.

Make every state renderable in storybook/design playground and covered by deterministic fixtures. No blank terminal-looking errors in the public UI.
