# 01 · Product vision and feature boundary

## What we are building

A premium, mobile-first, invite-only prediction league for **three friends watching LoL Worlds 2026**. The interaction metaphor is a sportsbook: event pages, pre-event odds, a slip, stakes, settled predictions, an accumulating account, and a leaderboard. **No real money and no prizes of value.** Never integrate a payment provider.

A player can place 100 RC at 2.2× on a series winner, 400 RC at 4.5× on an exact series score, 250 RC on whether a champion is picked in Game 1, and 2,000 RC on a long-range tournament outcome. Uncommitted credits remain available. New grants accumulate. An all-in wager is allowed **up to the available balance**; no lending, negative balance, daily spend ceiling, or forced allocations.

## Not this

- Not fantasy drafting: with three people, no complicated shared/exclusive roster pool.
- Not PvP liquidity: friends need not select opposite sides for a pick to be accepted.
- Not a simulated stock exchange: no buying/selling positions or cashing out before resolution.
- Not real-money wagering, financial products, or external payments.
- Not dependent on real-time official data access or a machine-learning model to be enjoyable.
- Not a Riot-endorsed or officially affiliated app.

## Product pillars

**Anticipation:** A match day appears as a browsable slate with visible lock countdown and featured markets. **Agency:** The stake can be any positive amount within available credits. **Compounding:** Prior returns become stakeable; grants prevent irreversible bankruptcy. **Rivalry:** Rank changes, notable wins/losses, and friend activity after lock. **Trust:** Odds and selection rules freeze at acceptance; evidence and adjustments are visible. **Delight:** Beautiful on a phone, fast to place three picks, respectful animations, well-designed stats.

## Complete feature vision

**Market interaction:** featured slate, event detail, popular/trending picks, filter/search by team/champion/player, decimal-odds toggle display only, odds movement indicators, price history graph, configurable market windows, selection controls, edit/remove slip, balance-preserving stake input, presets (10/25/50/ALL as percentage of *available*), quote expiry, multi-single checkout, receipt, shareable win cards.

**Competition:** wallet, day grants, locked vs available capital, ROI, win rate, average odds, streaks, biggest upset, head-to-head friend comparison, group activity feed, hidden-until-lock selections, group awards, final Worlds recap with final leaderboard.

**Market catalog:** series winner, exact score, series length, Game 1 winner, champion drafted by side, champion picked/banned anywhere in series, champion most picked/banned *per day* with tie policy, highest kills in game/series, first blood, penta, objective props, stage-qualified teams, tournament winner, daily specials, milestones, same-game combos when models support correlations.

**Admin and backend:** fixtures + roster imports, native odds modeling and manual override, odds snapshots, risk exposure dashboard, open/close/suspend controls, lock-before-draft enforcement, linked outcome sets, results entry & verification, partial-data hold, idempotent settlement, dispute/correction workflow, grant calendar, historical audit, provider health view, metadata/patch management, feature flags, dev seed/reset controls.

**Experience expansion:** push notification opt-in (not necessary for v1), PWA install, desktop split pane, spoiler mode, time-zone aware notifications, archived past seasons, dark/light theme, responsible-style display of fictional values with no monetization, Discord share links (no public Discord bot initially).

## Essential UI screens

Home/Today, Events, Event Detail, Market Explore, Bottom Slip/Checkout, Portfolio (Open/Settled), Wallet/Ledger, League/Leaderboard, Friend Profile/Compare, Notifications, History/Stats, Account/Preferences, Admin Dashboard, Fixtures, Market Builder, Odds Inspector, Results Inbox, Settlement Preview, Corrections, Audit Log, Import Monitor.

## Useful metrics (three users, qualitative first)

1. From opening Today's slate to accepted single selection: **< 30 seconds** on a mobile device with prefilled preferences.
2. Correctly explain **stake vs total return vs net gain** in a five-minute user test.
3. All three friends can participate across different time zones without missed grants or late bets.
4. Zero silent mis-settlements, double credits, or wallet balance inconsistencies.
5. Every selectable market has a visible resolution rule and cutoff time.
6. Every mobile surface works at 320, 360, 390, 430, 768, and 1440 px, portrait and landscape where relevant.
7. App remains usable with keyboard, screen reader, reduced motion, and slow or intermittent connection.

## Differentiator: tournament structure is explicit

Fixtures have `best_of` and stage metadata; markets attach to a **specific event scope** (game/series/day/stage/tournament). We never sum fantasy points across variable game counts to determine winner. A Bo1 may offer `winner` and `first blood`, a Bo3 can additionally offer `exact 2-0/2-1`, and a Bo5 can offer `3-0/3-1/3-2`. Any “most kills” market declares whether it is Game 1, an individual player's aggregate over the series, or normalized per-game rate; ambiguity is a market error.

## Constraints/risks

Source rights and Riot third-party prohibitions are a **critical external dependency**. Design the full feature set as a mock-data-first fan prototype; do not equate 'fictional credits' with Riot policy approval. We do not depend on scrape-only, undocumented APIs. See `14_POLICY_AND_SOURCES.md`.
