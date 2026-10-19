# 03 · Market catalog and outcome contracts

The goal is **deep, varied, understandable markets**, not arbitrary predicates. Every market has a name, scope, cutoff, required evidence fields, tie/void semantics, and model/version. No Bo1/Bo3/Bo5 score normalization: simply define separate markets appropriate to each format.

## Tier 1: reliable from scores alone

| Market | Scope | Example outcomes | Settlement | Close |
| --- | --- | --- | --- | --- |
| Series winner | Series incl. Bo1 | Team A / Team B | Winner of series; Bo1 is one game | Before series begins |
| Exact series score | Bo3 or Bo5 | A 2–0, A 2–1, B 2–0, B 2–1 | Actual series games won | Before series begins |
| Reaches decider | Bo3/Bo5 | Yes / No | Exactly 3 games for Bo3 / 5 for Bo5 | Before series begins |
| Total games | Bo3/Bo5 | 2/3 or 3/4/5 | Number played (void abnormal) | Before series begins |
| Game N winner | Individual game | A / B | Match result for indexed game | Before game N draft |
| Advances from Swiss | Stage | Yes / No | 3 wins before 3 losses | Before team's first Swiss match |
| Worlds champion | Tournament | One qualifying team | Final tournament winner | Long-term lock defined by admin |

Do not offer a Bo1 `exact score` market with fake 1–0 odds; simple winner is sufficient. For a Game 4 market, do not post until the fixture **can actually reach Game 4** and clarify void if it never takes place.

## Tier 2: draft-centric (strong LoL flavor)

| Market | Scope | Resolution & detail | Cutoff |
| --- | --- | --- | --- |
| Champion picked | Specific game | Yes if canonical champion ID appears in the ten draft picks | Before that game's draft |
| Champion banned | Specific game | Yes if canonical ID appears in ban phase | Before draft |
| Champion picked by team | Specific game | Yes if that team drafts champion | Before draft |
| Champion picked somewhere in series | Series | Yes if appears in any played game of series | Before Game 1 draft |
| Champion banned somewhere in series | Series | Yes if appears in at least one ban phase | Before Game 1 draft |
| Total unique picks | Series | Distinct champion IDs across every game, choose range | Before Game 1 draft |
| Most banned champion | Match day | One named champion, ties void under default rule | Before first draft of included schedule day |
| Most picked champion | Tournament/stage/day | Named champion; tie + games scoped clearly | Before stated scope begins |
| Team's first pick | Game | Named champion when verified as first draft selection | Before draft |
| Off-meta special | Series | Predeclared champion list; at least one picked | Before Game 1 draft |

Worlds 2026 uses Fearless Draft in multi-game series. A champion already picked in a series cannot be selected again in later games by either team. Model pick probabilities per **game index**, conditional on the champions exhausted in earlier games; don't assume independent identical drafts.

**Unavailable/missing ban or draft order telemetry:** hold market rather than infer from screenshots if certainty is poor. Never post a high-volume draft market before confirming the source provides the necessary fields.

## Tier 3: player / objective / game props

- **Most kills (Game N):** list eligible participating players; highest kills, tie → default void all tied-first winning tickets (or explicit co-winner rules); requires all ten kill totals.
- **Most kills (series, total):** aggregate across *played* games, explicitly series total (naturally favors longer series; it is a single-series prediction, not fantasy normalization).
- **Player kills over/under X.5 (Game N):** e.g. 5.5 means ≥6 for Over, ≤5 for Under; no ties.
- **First blood team/player:** must have authoritative game event timestamps; player credited by official stats; void if no valid event.
- **First tower/dragon/baron:** team winning named objective; absent objective → settle under a predeclared `NONE` option or void.
- **Pentakill occurs:** game or series; distinguish one vs multiple players.
- **Game duration band:** exact seconds from source; boundary in UTC elapsed seconds; interrupted/replayed games void unless contract covers it.
- **Total kills band:** sum of both teams' kill total in a game, not series unless explicitly marked.

**Quality rule:** no market without sufficient expected data quality, clear scope, and human-verifiable resolution.

## Tier 4: ambitious / feature-flagged

- **Same-event combination selections:** correlations modeled jointly; not product of independent legs when related (`A wins AND player A most kills`). Must define outcome dependencies and partial void pricing.
- **Daily specials / featured long-shots:** editorial markets like 'Any Garen pick today?' with controlled whitelist and reliability review.
- **Stage futures:** exact Swiss finish (3–0, 3–1, 3–2, out), finals matchup, number of reverse sweeps.
- **Community requests:** friends suggest markets; admin approves wording/odds/cutoff/evidence, no retroactive additions after lock.
- **Market trend/history:** display historical quotes and how they moved pre-lock; only a snapshot, not saleable positions.
- **Favorite templates:** one-tap filter of your preferred teams/champions, not one-tap bet placement.

## Contract schema for every market

```yaml
market_definition:
  kind: champion_picked
  scope: game
  display_name: "Will Orianna be picked in Game 1?"
  lock_rule: before_draft_start
  eligible_formats: [BO1, BO3, BO5]
  outcome_type: YES_NO
  required_fields: [game.draft.picks.champion_id, game.status]
  settlement_rule: champion_any_pick
  tie_policy: not_applicable
  void_policy: game_not_played_or_data_unverifiable
  odds_model_key: champion_pick_game_v1
  rule_version: 1
  source_confidence_minimum: confirmed
```

Odds for each selection carry `odds_version` and a frozen snapshot of that market definition at acceptance. Market-definition editors cannot change accepted tickets.

## Settlement precedence

1. Confirmed authoritative fixture/game IDs and rosters.
2. Full confirmed relevant stat/draft evidence.
3. Validate eligibility, cutoff, data completeness, and ties.
4. Grade outcome deterministically; `WIN`, `LOSS`, `VOID`, or `HOLD`.
5. Commit a single ledger settlement event and annotate proof links.
6. If results corrected later, reverse and regrade; audit everything.

## Market management priorities

Display Tier 1 first; Tier 2 as compelling second tab; Tier 3 after data is confirmed; Tier 4 behind explicit readiness flags. The ambitious target is all four tiers, but **never ship fragile odds or unverifiable prop markets just to fill a card**.
