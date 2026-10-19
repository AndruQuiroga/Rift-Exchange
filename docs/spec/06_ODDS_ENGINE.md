# 06 · Probability and pricing engine

## Main distinction

The app is a **private prediction game**. Odds are a scoring mechanic and may be subjective or model-estimated; they are **not live commercial betting odds** and should not be labeled accurate forecasts. The administrator can set manual probabilities and attach an explanation. We should prefer simple, calibrated, interpretable models over pretending a complex ML model is precise.

## Pricing math

Let `p` = estimated probability of an outcome, where `0 < p < 1`. Fair decimal return multiplier `d=1/p` (includes principal). Optional game-design margin `m`, **off by default**: `d=(1-m)/p` for a single outcome, carefully document if enabled. To keep the league fun, default **zero house edge**. Show decimal odds to 2 decimals; store accepted exact decimal with 4–6 precision and use explicitly documented payout rounding. Manual odds never override accepted tickets.

Example: `p(A wins)=0.70` → `1.42857…×`, displayed `1.43×`. `p(B wins)=0.30` → `3.3333…×`, displayed `3.33×`. Amount returned on a 400 RC winning stake at accepted `1.45` exactly = `580` RC; profit `180` RC.

## Consistency constraints

For a complete mutually exclusive market (e.g., A/B winner), estimate outcome probabilities that sum to 1 within epsilon. If manual prices are entered, inverse-odds may sum to >1 (vig) or <1 (arbitrage); show warnings. For 'Yes/No' markets, odds for both sides must derive from the same probability forecast; do not post contradictory quotes without flagging the risk.

**Series score baseline from independent per-game win probability** `q` (temporary modeling simplification):

- Bo3: A 2–0 `q²`; A 2–1 `2q²(1−q)`; B 2–0 `(1−q)²`; B 2–1 `2(1−q)²q`. A wins = `3q²−2q³`.
- Bo5: A 3–0 `q³`; A 3–1 `3q³(1−q)`; A 3–2 `6q³(1−q)²`; B equivalents swap `q ↔ (1−q)`. A wins = `10q³−15q⁴+6q⁵`.

Do not confuse `q` (single-game team strength) with a separately estimated **series win probability**; invert the series model if needed, with a numerical solver. In reality, side, fatigue, draft adaptation, and Fearless Draft break independence. Label the baseline model and use later stateful simulation where data supports it.

## Odds model sequence

**Level 0 — Editorial:** human-admin estimates for fixture winner, score, draft props. Store `manual` and author + rationale. Use if data unavailable.

**Level 1 — Team strength:** Elo/Glicko-like ratings, regional priors, strength-of-schedule, patch recency decay. Separate per-game `q` and series distribution. Calibrate against held-out past games to reduce overconfidence. Use shrinkage for international matchups with little shared opposition.

**Level 2 — Champion picks/bans:** estimated `P(pick champion | series, teams, players, patch, side, game index, prior selected champions)`. Use hierarchical smoothing by team/region/global pool; sample legal Fearless Draft sequences, not independent pick events across Bo5. Produce an *aggregate chance* for 'appears anywhere in series' from simulations.

**Level 3 — Player props:** negative-binomial/Poisson family for kill totals with team pace, game length, position, matchup, patch; calibrate dispersion and excess zeros. For 'most kills', draw **joint** per-game or per-series simulated outcomes for all participants, preserve ties. Avoid invented precision and show broad confidence bands in admin.

**Level 4 — Correlated combos:** sample game state and compute joint event probabilities; no naive odds multiplication for correlated outcomes. Block combos until sufficient simulation coverage and regression tests.

## Data discipline

Training windows must not leak future results into earlier odds. Use recorded `snapshot_at` cutoffs and same-competition patch/version; keep model run version, feature cutoffs, source timestamps, holdout scores, calibration curves, and drift diagnostics. When uncertain, **disable market**; admin may publish transparent manual odds instead. Store `probability_estimate`, `confidence_label` (`verified_model`, `manual`, `experimental`), `odds_decimal`, and `as_of`.

## Risk and good game design

- Unlimited position size **up to available balance**; no artificial caps on a user's per-day allocation.
- `MAX_DECIMAL_ODDS` is a technical guardrail (suggest initial `100.00×`; configurable) to prevent implausible model tails/overflow, **not** a currency stake cap. Very low probability markets need editorial review.
- Use decimal/integers, no floats for balances. Validate multiplication bounds before accepting stakes.
- Price refresh cadence: only on meaningful fixture/draw/status/news updates (not fake continuously ticking prices). Every quote version is auditable.
- Long-term markets keep stakes unavailable until resolved/voided. Do not allow selling/cashout—the design is sportsbook-style.
- You do not need an actual counterparty or house bankroll because RC is nonredeemable scoring currency. Nevertheless record total game-wide issue and payout for diagnostics.

## Odds/testing quality bar

Check normalized outcome probabilities, accepted quote immutability, `p=0`/`p=1` handling (must suspend or reject rather than infinite/1× nonsense), Bo3/Bo5 sum probabilities ≈1, result grading across all scorelines, coherent early locking, amount rounding, calibration by stage, and broken data scenarios. UI displays estimated odds, not bookmaker authority.
