# 02 · Rules, virtual economy, and settlement

## Canonical terms

- **RC:** Rift Credits, a fictional integer balance; non-transferable, not purchasable, no real-world value.
- **Season:** Worlds 2026 (one competition); creates all user wallets, grant calendar, and results.
- **Event:** a fixture / game / day / stage / championship result with start and status.
- **Market:** a mutually exclusive or yes/no question with documented scope and settlement policy.
- **Outcome:** a selectable answer with a quoted decimal multiplier.
- **Selection:** outcome on a user's ticket, with immutable accepted multiplier and rules version.
- **Ticket:** one atomic purchase; default contains 1–N **independent singles** (not a multiplied parlay).
- **Stake:** debited once at placement. **Return:** total credited on winning selection = stake × odds. **Profit:** return − stake.
- **Void:** if event invalid, unresolved by cutoff, or rules demand cancel, stake is returned exactly once.
- **Correction:** a compensating ledger entry referencing prior settlement, never erase history.

## Opening grant and match-day stipend

Default season config: `opening_grant=1000`, `match_day_grant=1000`, `season_timezone=America/Los_Angeles` for admin display only; **official match day IDs use tournament-local calendar date**, not browser date. Explicitly seed the schedule of eligible play days from official calendar. Stipend is granted **once per user per eligible play day**, using a unique `(season_id, user_id, grant_day_id)` key. All users get the same stipend even if they don't log in. Grant execution is idempotent and backfill-safe. Retroactive schedule changes require admin confirmation and visible audit records.

**Recommended policy:** first Swiss day onward, initial 1,000 RC on joining and additional 1,000 RC per official scheduled Worlds match day. If a newcomer joins after start, decide season-wide catch-up grants in advance; default: backfill all prior eligible grants equally to prevent join timing advantaging users. No grant on rest days. During an event with no bets available, money is still spendable later.

**Open question:** Could make the start 1,000 RC without a separate match-day stipend on Day 1. Default spec intentionally grants *both* to avoid ambiguity; expose season config in admin and show ledger entries separately.

## Placement rules

1. Server clock is authoritative; browser countdown is an aid only.
2. Market carries immutable rules and cutoff. Pre-match markets close **before event start**, and draft-dependent Game 1 picks close **before draft begins**, whichever is earlier. For pre-series ‘any game draft’ predictions, lock before the series draft begins. Never accept in-progress bets in v1.
3. Stake is positive whole RC (config can later support cents but don't use floating point for money).
4. Total of all selections on ticket ≤ available RC. **No arbitrary max stake**; an ALL shortcut fills the available amount. Currency/payout integer safety still applies.
5. Odds quote has version/expiry. At acceptance, each selection records `odds_decimal`, `market_version`, `rule_version`, `quote_id`, and `accepted_at`. If price changes or lock occurs, return conflict and display the new quote; **never silently reprice**.
6. Allow multiple separate tickets on the same outcome if user chooses; no special compounding across tickets. Limit one choice within a mutually exclusive group **on the same ticket** to avoid contradictory UX; separate hedge tickets permitted with explanation.
7. A ticket purchase transaction locks wallet, checks balance & cutoff, inserts selections, debits stake(s), inserts corresponding ledger entries, commits together, and broadcasts an accepted receipt.
8. Users cannot cancel settled or accepted predictions. Admin may void on a documented integrity issue.

## Settlement rules

A result is **proposed**, validated with source evidence, then **confirmed** by authorized admin or trusted provider. Only eligible confirmed results grade markets. Winner: `round_half_up(stake * accepted_decimal_odds)` for *total return*, integers; loser: 0; void: original stake. Configurable rounding semantics **must be deterministic and locked at season creation**; spec uses decimal arithmetic and ROUND_HALF_UP at final return. Use a unique settlement event ID for replay safety.

Manual corrections don't mutate historical transactions: append reversals and the corrected payout; both are surfaced in the user's ledger with an explanation. Settlement unit is per selection; an event may settle one market while holding others missing data. If sources disagree, mark `DISPUTED` and pause. Never guess a kill leader from partial stats.

## Leaderboard formula and visibility

**Default:** rank by `available_balance + reserved_for_unsettled_stakes` *as informational deployed capital*? **No**—a committed stake is at risk and has no guaranteed redemption value. Define leaderboard's primary rank as **available balance only** (open stakes are treated as spent until settlement). This invites an artificial incentive to defer bets on the final day. For the final ranking, require all markets settled/voided, then compare actual final balance. For mid-event context, display 3 separate numbers: **available**, **open stake**, **realized net earnings**; standings clearly marked provisional. A second 'contributed capital' view may add open stakes at cost as a **notional**, not guaranteed value, clearly labeled. Never call potential payout current assets.

Ties: rank equal balance jointly unless a fun tiebreaker is announced *before* the season begins (default: no tiebreaker; show tied place). Final results freeze after all corrections and before publishing trophy.

## Example ledger arithmetic

Starting available: 1,000 RC; stake 400 @1.45× and 250 @3.40×; available immediately after placement 350. If both win: returns 580 + 850 = 1,430; available = 1,780; **net profit on those stakes = 780**, not 1,430. Next match-day grant: +1,000 → 2,780.

## Event disruptions & edge cases

- **No contest / postponed before start:** suspend; if rescheduled to a materially different event window/opponent, void and repost. Do not quietly transfer old tickets.
- **Forfeit:** settle only markets whose rules explicitly cover forfeits and whose outcomes are authoritative; void player/draft performance by default.
- **Champion name changes/patched assets:** settle by canonical ID and match patch.
- **Ties in ‘most’ markets:** default `VOID_ALL_TIED_FOR_FIRST` for an outright leader market; an alternative 'dead heat' policy requires separate market definition and price model.
- **Team substitution/player role swaps:** settle by immutable participant IDs; player-specific markets void if player does not participate, except explicit `will_play` types.
- **Suspended/missing data:** mark market `HOLD` with status explanation; no artificial result.
- **Stale odds in two open tabs:** quote version conflict → repricing confirmation; wallet locked transaction prevents double spending.
- **Admin plays too:** odds changes must have an audit reason and market suspends when admin posts stats; all players see adjustments after lock.

## Non-monetization and access boundary

No fiat, crypto, cards, payments, purchasable credits, tips, staking real assets, referrals with monetary value, cash prizes, redemption, cash out, or transfer between users. Require one season disclaimer in UI and a small persistent 'Play credits only' label near wallet. The sportsbook metaphor is nonetheless **not assured to comply** with Riot rules; policy gate applies before external integration or deployment.
