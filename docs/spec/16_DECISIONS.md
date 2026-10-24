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
| D-020 | Swiss record calls are a free card, not stakes: one call per team, rows capped 2/3/3/3/3/2, price locked when called; exact pays 100 RC x price (cap 1,000), right side a quarter, paid as REWARD ledger entries. Open staked record picks were refunded and carried onto the card | Owner decision 2026-10-21 | No stake decision; underdog calls still pay more. |
| D-021 | Draft calls are only "picked by either team"; by-team, ban, first-pick and role markets are no longer created (earlier ones still settle) | Owner decision 2026-10-21 | One question per champion. |
| D-022 | Opening grant 5,000 RC (was 1,000); match-day grant stays 1,000. Members who joined earlier get the difference once, as an opening-grant top-up | Owner decision 2026-10-21 | Round 1 has many matches to play. |
| D-023 | Objectives offered: first blood, first tower, Baron before 25:00. First dragon element and dragon soul are no longer offered (earlier ones still settle) | Owner decision 2026-10-21 | Too many near-random options per game. |
| D-024 | Lane duels and kill lines stay open from game load to 3:00 of game time; an early kill no longer closes them. Kill lines are offered from 5 above the kills scored so far. "Games played" is no longer offered (the exact score covers it); earlier ones still settle | Owner decision 2026-10-21 | First blood should not end the early window. |
| D-025 | Early-window markets (game load to 3:00): team races first to 5 kills, gold lead at 15:00 (a gap under 700 gold is a tie and void) and first dragon (any element), plus lane duels on player gold at 15:00, where a gap under 700 gold is a tie and void. Kills, CS and damage duels are no longer offered (earlier ones still settle) | Owner decision 2026-10-21 | Per-role kill and damage duels were too predictable. |
| D-026 | Game winners (and a Bo1 match winner), first tower and Baron before 25:00 stay open through the draft until 3:00 of game time; first blood likewise but closes at the first kill if sooner. Series winner and exact score (Bo3+) still close at the series start. Draft picks close before the draft | Owner decision 2026-10-21 | Bet after seeing the draft. |
| D-027 | Stakes are capped at 1,000 RC per player per prediction (all their picks on it together). Everything is capped in the Swiss stage; from the quarterfinals, predictions that close before the draft (series winner, exact score, champion calls) are uncapped, and anything still open after the draft is seen (game winners, objectives, early-window markets) stays capped. Champion calls close before the draft, as D-026 says: series start for Game 1, 7 minutes after the previous game ends for Game N | Owner decision 2026-10-21 | Fair odds and no counterparty let any edge compound; trailing players get bigger swings in the knockouts. |
| D-028 | Early-window markets keep closing at 3:00 but follow the game: first to 5 kills, kill lines, gold lead at 15:00 and gold duels are re-priced from each livestats frame, and a pick accepted after a kill the price had not seen yet is void | Owner decision 2026-10-21 | No edge from watching ahead of the price. |
| D-029 | The Worlds champion future is not offered during the Swiss stage (`RIFT_OFFER_TOURNAMENT_WINNER`); re-evaluate after Swiss. Picks placed earlier still settle | Owner decision 2026-10-21 | Too far out, and the model prices it worst. |
| D-030 | A series counts as completed once a team reaches the wins needed (Bo1 1, Bo3 2, Bo5 3), even while the feed still lists it in progress: the page shows the result at once and settlement pays after the data holds for the settle delay, now 5 minutes for every market (was 10). Each fixture keeps the team order it was created with. A corrected score reopens the series; anything already paid regrades through D-014. | Owner, 2026-10-23 | Amends D-014. IG–GEN stayed "inProgress" well after its only game, and the feed flipped its team order at game start. |
| D-031 | Lane duels and kill lines are offered twice per game: **blind** before the draft (expected players and team history, closing with the champion calls — Game 1 at its scheduled start, later games 7 minutes after the previous one ends) and **after the draft** from the game's first frame until 3:00. Separate markets: a blind pick stands whatever champions are picked; a blind duel voids if either named player does not play. No betting during the draft itself. | Owner, 2026-10-23 | The feed shows no champion select and the broadcast does. Team races stay after-draft only. |
| D-032 | Results show before they pay: once a locked market is decided by the data — graded, or called live from the game timeline (the draft at load, firsts, baron, gold at 15:00, kills past a line) — the page shows it with the time it pays (data steady for the settle delay). Live calls confirm from verified data after the game. Nothing moves credits until settlement. Friends see each other's pick counts before lock and the picks themselves after (A-010 unchanged). | Owner, 2026-10-23 | Responsive match pages without paying on unconfirmed data. |
| D-033 | Champion calls (picked, by a team, in a role) pay a toned-down price: fair odds with the ban refund priced in, then 75% of the profit, on top of the usual margin. If the champion is banned instead, half the stake comes back; neither picked nor banned loses the stake. Bans come from Leaguepedia after the game, so a not-picked call holds until they arrive (void at the HOLD deadline). Picks accepted before this keep their own terms. | Owner, 2026-10-23 | Less variance on draft calls; a ban is a near miss, not a full loss. |
| D-034 | After lock, friends are rivals on the match: who backs which side, a live match table (settled plus already-decided picks), head-to-heads with both outcomes spelled out, squad picks, and fixed-phrase reactions (Called it, You're sweating, Bold call, GG) on a friend's locked pick, once per phrase. Reactions reach the friend as a toast. No free text. Before lock nothing changes (A-010). | Owner, 2026-10-23 | Adversarial and playful without moderation. |
| D-035 | Winner markets close when the draft starts, with the champion calls: a Bo1 match winner and Game 1 at the scheduled start (or when the series goes live first), Game N seven minutes after Game N-1 ends (or when it loads, if earlier). They are no longer open through the draft. | Owner, 2026-10-23 | Amends D-026 for winners. Objectives keep their own windows. |
| D-036 | A lane duel with no winner (a tie within 700 gold, a game over before 15:00, or a named player not playing) returns half the stake to both sides instead of a full refund. A game that is not played still voids in full. Picks accepted before this keep a full void. | Owner, 2026-10-23 | No free roll on a coin-flip duel. |
| D-037 | Series markets and Game 1's pre-draft markets (winner, champion calls, blind duels and kill lines) lock when the series goes live in the feed, early or late, rather than at the listed time; a 3-hour backstop covers the feed never reporting it. The page says "Locks when the draft starts" (with the listed time, or "running late") instead of counting down to a time that may not hold. | Owner, 2026-10-23 | Days run behind schedule; a match starting early still locks at once. |
| D-038 | A player can cancel their own open pick until its market locks: the whole stake comes back, the pick is marked CANCELLED and never settles, and it no longer counts toward the stake limit, standings, the match table or friends' views. Once a market locks every pick stands. | Owner, 2026-10-23 | Undo a mistake before the match without a support request. |
| D-039 | Going live starts a one-minute countdown instead of locking pre-draft markets on the spot (Game 1 winner, draft calls, blind duels, kill lines and team races); the game loading ends it sooner. The page shows the countdown and a toast when it starts. | Owner, 2026-10-23 | Amends D-037. The broadcast goes live 4-7 minutes before the draft (measured); one minute never reaches the draft. |
| D-040 | One timeline for every game market: blind at full odds before the draft, locked during it, then reopened from game start to 3:00 at the after-draft price (75% of the fair profit: 2.00 shows 1.75). First blood, first tower and Baron before 25:00 no longer stay open through the draft. One bet per market per person, blind or after the draft (kill lines: one per game; duels: one per lane). Cancel until 3:00: the whole stake before the draft starts, 75% after, never once the data has decided it; replacing a blind bet is cancel then bet. Champion pick and ban markets are no longer offered. New: game length over/under a half-minute line at this Worlds' median, settled on Leaguepedia's game time (the feed's clock if it has none). Bets on one outcome show combined (total stake, blended odds, total return); each keeps its own odds. | Owner, 2026-10-24 | Supersedes D-026 and the through-draft part of D-031; extends D-038. Picks already placed settle under their own rules. Blind odds reward calling it early; the lower after-draft price and 75% cancel make waiting cost something. |
| D-041 | Two three-way objectives join the game board: dragon soul and first Baron, each won by either team or by nobody ("No soul", "No Baron"). They follow the D-040 timeline (blind, then after the draft at the lower price). Nobody's price comes from how often this Worlds saw neither team take it; the rest splits like first tower, leaning to the stronger side. Settled from the game timeline (soul side; first Baron's team). | Owner, 2026-10-24 | Fills the mid and late game, which the other objectives (mostly settled by 15:00) leave empty. The old soul-element market stays retired (D-023). |

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
