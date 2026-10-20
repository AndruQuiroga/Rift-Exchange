# 16 · Decisions, assumptions, and open issues

## Accepted product direction

| ID | Decision | Status | Rationale |
| --- | --- | --- | --- |
| D-001 | Sportsbook-style **fictional credits**, no stock trading/cashout | User-confirmed | Straightforward outcome and payout interaction. |
| D-002 | **Three players** initially, scalable membership | User-confirmed | Social dynamic should work with a tiny group. |
| D-003 | Skip traditional fantasy roster drafts and cross-BoX points normalization | User-confirmed | Market scopes address different match lengths naturally. |
| D-004 | Accumulating daily match-day grant; can stake savings/winnings | User-confirmed | Compounding bankroll game loop. |
| D-005 | Ambitious end state and premium **mobile-first UX** | User-confirmed | UI/UX is a first-class deliverable. |
| D-006 | No real-money exchange, purchase, transfer or prizes | Hard constraint | Fictional-only league; policy caution remains. |
| D-007 | Reject prior glass/gradient-heavy look and pursue modern solid-surface visual direction | User-confirmed | UI/UX is central; visual refresh should preserve all game logic. |
| D-008 | **Fully automated data, no routine manual inputs.** Fixtures, odds, locks and settlement are produced by the worker; admin keeps only emergency controls (suspend, kill switch, audit) | User-confirmed 2026-10-19 | Owner wants zero manual operation. |
| D-009 | **Primary source: lolesports public feed** (`esports-api.lolesports.com` schedule/event details + `feed.lolesports.com/livestats` windows). **Secondary: Leaguepedia Cargo API** for bans and cross-checks, via a bot account (mocked until credentials exist). Data Dragon for champion metadata. No Riot developer API key is required (it does not serve pro data) | User-confirmed 2026-10-19 | Verified 2026-10-19: schedule through Nov 14, Play-In game metadata, per-player kills/objectives in final frames. Leaguepedia rate-limits anonymous queries. Feed is undocumented and may change; adapters are isolated and degrade to HOLD. |
| D-010 | **Opening grant on account creation** plus an **opening futures window** (Worlds winner, Swiss advancement) before the first Swiss match; then 1,000 RC per official match day (venue-local date, America/Chicago) | User-confirmed 2026-10-19 | Supersedes A-001/A-002 ambiguity. |
| D-011 | Full stack kept: Next.js web + FastAPI API + Python worker sharing one codebase + PostgreSQL; Redis omitted initially | User-confirmed 2026-10-19 | Model-driven odds favour Python. |
| D-012 | Visual direction delegated to the build: solid-surface "Arena" broadcast style (charcoal, hairlines, one lime accent, big tabular odds); tweak later | User-delegated 2026-10-19 | Packet recommendation; no glass. |
| D-013 | Odds are model-generated (Elo from 2026 league results → per-game q → Bo1/3/5 distributions); markets only open when their model has data. Series markets lock at scheduled series start; between-game locks deferred | Build decision 2026-10-19 | No admin pricing available under D-008. |
| D-014 | Auto-settlement once a game/series is `completed` and the data has been stable for a settle delay; incomplete data → HOLD → auto-VOID at deadline; later source changes produce automatic reversal + regrade | Build decision 2026-10-19 | Follows D-008 and settlement invariants. |
| D-015 | Real team names are used (no ATLAS/NOVA in production); app stays private and invite-only, and is not published | User-confirmed 2026-10-19 | Owner accepts Riot-policy risk; supersedes A-015 for live data. |
| D-016 | Team model: game-level Elo with regional priors, K=12, shrink 0.85, tuned on a walk-forward backtest of 67 international 2026 series (log loss 0.590 vs 0.693 coin-flip, 69% accuracy). Re-run with `make backtest` | Build decision 2026-10-20 | Lower K scored marginally better but leans on editorial regional priors; kept the middle ground. |
| D-017 | Game winners come only from forced evidence: a series sweep, or the series-score change between two polls (the worker polls every minute during live series); otherwise Leaguepedia, otherwise HOLD | Build decision 2026-10-20 | The live-stats feed has no explicit per-game winner. |
| D-018 | Futures: "advance from Swiss" closes at the first Swiss match (the opening betting phase); "Worlds champion" stays open, re-priced after every result, until quarterfinals start | Build decision 2026-10-20 | Matches D-010; accepted odds stay frozen. |
| D-019 | Draft (champion picked) and game-1 total-kills markets open once ≥15 Worlds games have verified stats; priced from this tournament's pick rates / kill totals and labelled experimental | Build decision 2026-10-20 | Play-Ins supply the first 22 games. |

## Chosen defaults, configurable (not yet separately confirmed)

| ID | Default | Reason / potential alternative |
| --- | --- | --- |
| A-001 | 1,000 RC opening **plus** 1,000 RC on every eligible official match day (including first) | Two explicit ledger rows; alternatively suppress first-day match grant. |
| A-002 | First eligible match day **October 23**; exclude completed Play-Ins | Starting now makes the Swiss slate an equal starting point. |
| A-003 | Tournament-local calendar day drives stipend; server stores UTC cutoff | Avoid day-shift and browser-time exploits. |
| A-004 | Quotes expire after 20 seconds; prices fixed upon acceptance | Avoid stale selections while retaining explainability. |
| A-005 | All stake integers; decimal multiplier display; half-up integer return | Reproducible across languages and DB. |
| A-006 | Market lock by earlier of published cutoff, draft start (if relevant), or fixture start | Never accept after information is revealed. |
| A-007 | Market examples: winner, exact score, game winner, draft, champion most banned on match day, highest kills, futures | Diverse prediction types without fantasy rosters. |
| A-008 | Individual single selections placed in one checkout, not correlated accumulator | Safer grading and clearer odds. |
| A-009 | Unsettled active predictions shown in Portfolio, **not valued as current credits** | No cash-out or trading. |
| A-010 | Selections private to owner until lock; then visible to friends | Prevent copying, increase playful rivalry. |
| A-011 | Most-kills/most-banned ties **void** unless odds explicitly include tie outcome | Avoid ambiguous partial payouts. |
| A-012 | Data completeness gating + human review before settlement | Correctness more important than instant payout. |
| A-013 | Administrator has transparent peer-visible result/correction audit | Small-group social fairness. |
| A-014 | **Proposed** Arena Editorial: flat graphite surfaces, subtle separators, electric lime on key actions only | Prior glass style rejected; compare three alternatives in `design-lab/index.html` and `17_VISUAL_DIRECTION_RESEARCH.md`. Palette unconfirmed. |
| A-015 | Use synthetic Atlas/Nova fixtures and no protected Riot artwork in public mock | Avoid confusing examples with actual Worlds matches. |

## Blocking release decisions

1. **Riot policy:** Product policies prohibit betting/gambling functionality; does the intended fictional-credit staking app qualify and receive permission? Do not deploy a Riot-linked version without resolving this. See `14_POLICY_AND_SOURCES.md`.
2. **Data rights:** Is there a legitimate source we may use for live fixtures, drafts, player statistics, and redisplay? For now use synthetic or permissioned manual data.
3. **Admin fairness:** Should corrections require one other friend's approval when administrator has open positions? Default strongly recommends yes.

## Non-blocking nice-to-choose items

- Team/name/brand (working name Rift Exchange, could be generic original IP).
- Whether first Swiss day gets 2,000 total RC (opening + daily) or opening amount replaces first daily grant.
- Whether friends reveal stakes at market lock or settlement.
- Whether friends prefer a display of projected win probability alongside odds.
- Whether a daily bonus should be 1,000 on each **match day**, each **calendar day**, or each **individual series**; user originally said every day or game day. Default match day.
- Whether to include Play-In historic results in stats even though the game starts Swiss.

## Backlog seeds (no feature forgotten)

| Theme | Candidate |
| --- | --- |
| Watch-party UX | Copy clean group activity links; spoiler blur; offline read-only; notifications by match; themed celebration screens |
| Markets | Ban/pick leader, unusual champion, first objective, series MVP, inverse/upset specials, knockout qualification, total unique picks |
| Portfolio | Cumulative RC chart annotated with grant events, exposure by team/market, risk heat map, ROI by category, accepted-odds timeline |
| Models | Bayesian Elo, patch-sensitive draft priors, champion-player tendency smoothing, kill count negative binomial, correlated BoX simulator |
| League | Mock trophies, season history, badge cabinet, rivalry timeline, pinned picks post-lock, awards recap |
| Admin | Odds diagnostics, suspended-market queue, provider health, settlement rehearsal, model A/B, two-person correction approvals |
| Platform | API client codegen, fixture import CLI, Sentry-compatible diagnostics, GitHub Actions, Swarm/Portainer deploy recipes |
| Access | Colorblind modes, font scaling, translations, keyboard and screen reader, haptics toggle, motion reduction |

## Change-control instructions

Before editing a rule with any accepted ticket: publish a new rule version and only apply it to *new* tickets; never rewrite accepted terms. For economy rule changes, freeze before the affected match day and record an audit event visible to all members. For source changes, stage adapter in shadow mode and compare at least five graded fixtures before enabling automatic confirmation.

## Deferred after the first build (2026-10-20)

- ~~Ban markets~~ — built in the exchange builders work (2026-10-21): bans and pick order are stored from Leaguepedia and champion-banned markets open once 10 games have bans. **First-pick markets stay off** (`draft.FIRST_PICK_VERIFIED`) until blue-side-first is confirmed against real 2026 drafts.
- ~~Player props~~ — built: lane duels (lineups from each team's last Worlds game, else its latest regional match), any-line kill totals and objective markets, all graded from the per-game livestats timeline.
- ~~Between-game locks~~ — built: the worker polls every 15 s around live series and Game N markets close 7 minutes after Game N−1 ends (measured gap to the next game's first frame: 19–21 minutes).
- Second-friend approval for corrections — corrections are automatic (D-014) and fully visible in each ledger.
- Docker images are written but were not built in the development container (no Docker daemon there).
