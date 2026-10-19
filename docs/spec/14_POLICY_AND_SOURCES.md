# 14 · Verified Worlds context, data access, and policy gates

**Research checkpoint:** 2026-10-18. Recheck the live event schedule, rules, data-provider terms, and Riot policies before deployment. This is an engineering/risk overview, not legal advice.

## Verified official Worlds 2026 facts

Primary source: [Riot — Worlds 2026 Primer (Oct 5, 2026)](https://lolesports.com/en-GB/news/worlds-2026-primer).

- **Play-Ins:** October 15–18 in Los Angeles; four teams, double-elimination, best-of-five; one team advances.
- **Swiss:** October 23, 24, 25, 26, 28, 29, 30, 31 in Allen, Texas; Bo1 and Bo3; teams advance after three match wins or exit after three losses.
- **Knockouts:** quarterfinals November 3–6; semifinals November 7–8; final November 14; all Bo5.
- **Initial Swiss draw:** October 18, with Tier 1 versus Tier 4 and Tier 2 versus Tier 3, and no same-region first-round pairing. Later draws match teams on equal records, forbid repeat Swiss opponents, and permit same-region pairing.
- **Pick'Em:** Swiss picks open October 18 and lock before the first Swiss match October 23. This *does not* lock our private game, whose windows we define explicitly.
- **Fearless Draft:** Verify precise draft constraints against the official 2026 competitive rulebook when defining champion markets. The prior Riot format explanation is not a substitute for per-event officiating rules.

**Operational rule:** Ingestion reads schedule/fixtures as facts with `observed_at`, `source_uri`, provider ID, revision, and `quality` flag. Demo seeds use imaginary fixture names **ATLAS / NOVA** to avoid confusing sample odds with actual scheduled matchups. Do not fabricate upcoming matchups after the draw.

## Data rights: do not treat live esports stats as an open public API

[Riot official esports data / GRID](https://riotesportsdata.com/en-us/league-of-legends/) confirms that GRID commercially distributes official fixtures, real-time data, scores, and statistics. The provider's FAQ currently says its live/fixture offerings are for commercial purposes and a broader noncommercial data portal is being developed. **This does not grant us access or redistribution rights.**

Recommended provider strategy:

1. **Build against typed fixture/result adapters and synthetic fixtures.** Ship a fully interactive frontend/engine without claiming live odds.
2. **For a strictly private local test**, allow manual fixture input and manually verified settlement by a friend using results they viewed. Keep provenance and corrections; no unauthorized automated scrape.
3. If approved, integrate an official or expressly licensed data source with an adapter, rate limits, and contract tests. Respect image/trademark licenses independently.
4. Avoid unofficial scraped endpoints, brittle embedded site JSON, replay scraping, broadcast capture, circumventing access controls, or copying sports-book prices without permission.
5. Gate every market by required fields: winner/exact score needs confirmed fixtures, champion stats need complete drafts, player props need complete verified box scores. Missing data → `HOLD`, then `VOID` at the published deadline if necessary.

Reference: [GRID data product](https://riotesportsdata.com/en-us/league-of-legends/).

## IMPORTANT: Riot third-party product policy

Read both [Riot General Policies](https://developer.riotgames.com/policies/general) and [LoL Developer API Policy](https://developer.riotgames.com/docs/lol). As checked Oct 18, both say a product **cannot feature betting or gambling functionality**. The LoL policy additionally requires registration for products serving players and prescribes a visible non-endorsement disclaimer, and constrains use of Riot IP. A virtual currency that cannot be redeemed **does not automatically exempt this sportsbook-like mechanic** from Riot's product policy. Small private groups and lack of API calls also do **not** constitute affirmative permission.

**Hard release gate:** Before deploying or distributing a Riot-branded, data-integrated prediction staking product, obtain qualified clarification/permission on whether the proposed play-credit staking mechanics are permitted. If not permitted, **do not deploy those mechanics as a Riot-linked third-party product**. Options: keep only a local, generic original-IP prototype without Riot assets/data; or pivot to a points-only forecasting competition with no risked bankroll, subject to a fresh policy check. This packet does not promise approval.

Prohibited regardless of provider: buyable credits, cash/crypto redemption, prizes of value, referral payouts, financial deposits, or third-party real betting. Do not promote risky behavior or loss-chasing via push notifications.

For any permitted LoL-connected deployment, the app should visibly show the required disclaimer, using the product name as directed in the policy:

> Rift Exchange is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

This is **a proposed text**; verify Riot's latest exact-required language at release.

## Example source metadata contract

```json
{
  "provider": "manual_verified",
  "external_event_id": "demo-swiss-a",
  "observed_at": "2026-10-23T19:15:00Z",
  "source_uri": "manual://admin-entry/17",
  "completeness": ["series_score", "game_1_draft"],
  "confidence": "human_review_required",
  "reviewed_by": null,
  "revision_hash": "sha256:..."
}
```

## Verification tasks before production

- [ ] Confirm fixture schedule, tournament-local date, stage format, draws and roster identities.
- [ ] Review official event rulebook for Fearless Draft, technical pauses, remakes, forfeits, champions and tie rules.
- [ ] Establish permission/viability under Riot third-party policies; **block release otherwise**.
- [ ] Verify all planned data fields can be legally sourced with necessary timeliness and completeness.
- [ ] Confirm asset rights for team marks, champion art, fonts, and any streams.
- [ ] Add and manually test missing-data, embargo and source-correction fallbacks.

## Sources / checked links

- [Worlds 2026 Primer, Riot LoL Esports](https://lolesports.com/en-GB/news/worlds-2026-primer)
- [Riot League of Legends Developer Policy](https://developer.riotgames.com/docs/lol)
- [Riot General Developer Policies](https://developer.riotgames.com/policies/general)
- [Riot official esports data — GRID](https://riotesportsdata.com/en-us/league-of-legends/)
- [Riot Developer Portal](https://developer.riotgames.com/)
