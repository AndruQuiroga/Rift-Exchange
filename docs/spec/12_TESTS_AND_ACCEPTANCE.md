# 12 · QA matrix and release acceptance

## Payment-grade correctness for fake credits

Use a rigorous integrity bar even though RC is fictional. It is a competition and bugs destroy the fun.

### Property-based money tests

- For all wallet balances `b>=0` and stakes `s>0`, placement succeeds iff `s<=b` and market/quote valid; resulting wallet `b-s>=0`.
- Two simultaneous all-in requests on same wallet cannot both debit it.
- Retry same `Idempotency-Key` returns same ticket; no extra stake debit.
- Grant day job retried 100× credits 1,000 RC exactly once.
- For win: return `round_half_up(stake * accepted_odds)`; loss returns 0; void returns exact stake.
- Repeated settlement with same revision cannot double credit.
- Regrading from prior win to loss reverses prior payout exactly; reverse correction yields original balance.
- Odds revisions cannot mutate existing accepted tickets.
- Balance generated from ledger matches cached wallet in all randomized test sequences.
- Rejected tickets cannot leave orphaned selection or ledger debit.
- A conflicting quote response cannot be accepted without user confirming updated terms.

### Unit markets

- Bo1 vs Bo3 vs Bo5 score distributions sum to 1 and only expose legal outcomes.
- Winner and exact-score settlement for every legal match score.
- Champion picked Game 1 = yes even if banned later? Game 1 uniquely scoped; no cross-game leakage.
- Multi-game Fearless validation flags repeated picks in same series.
- Most-banned over match day includes only played eligible games; ties follow published void rule.
- Player most-kills confirms complete roster and stats, ties void; nonparticipants void.
- A game four selection voids if series ended 3–0 (should normally not have been offered early in v1).
- Forfeit/remake/postpone logic sends incomplete props to VOID/HOLD, no casual winner assignment.

## End-to-end UX tests (Playwright)

| Scenario | 320px | 390px | 768px | 1440px |
| --- | :---: | :---: | :---: | :---: |
| See first match and wallet without overflow | ✓ | ✓ | ✓ | ✓ |
| Tap an odds tile, toggle selection state | ✓ | ✓ | ✓ | ✓ |
| Place two singles in a slip and view receipt | ✓ | ✓ | ✓ | ✓ |
| Keyboard does not hide stake/confirmation | ✓ | ✓ | n/a | n/a |
| Browser back closes slip without losing picks | ✓ | ✓ | ✓ | ✓ |
| Leaderboard clearly distinguishes open stake and balance | ✓ | ✓ | ✓ | ✓ |
| No-data, locked, and price-changed states readable | ✓ | ✓ | ✓ | ✓ |
| Long player names and translations wrap | ✓ | ✓ | ✓ | ✓ |
| Accessible keyboard flow / 200% zoom | ✓ | ✓ | ✓ | ✓ |

## Accessibility

WCAG 2.2 AA target, including 44×44 targets, contrast, visible focus, logical heading order, alt labels, `aria-pressed` odds tiles, informative alert/live regions, screen-reader table names, Escape/modal focus trap, reduced motion, no color-only result badges. Audit with axe and manually test VoiceOver/TalkBack at least once.

## Failure-state tests

Kill API during placement after DB commit; verify idempotent retry + accurate receipt. Kill worker halfway through grant; retry and reconcile. Delay result provider 6 hours; keep incomplete markets in HOLD and display why. Race fixture start against ticket acceptance; no accepted late ticket. Change local phone time; impossible to bypass lock. Reload PWA while slip open; local draft survives but re-quotes.

## Performance/load

Run Lighthouse CI for mobile 4G simulation. Targets: LCP under 2.5s, CLS under 0.1, INP under 200ms under reasonable local conditions, no giant client bundles of champion art, lazy-load market sections, avoid full-page re-renders on odd updates. Backend 10 concurrent simulated users even though group has 3. Verify layout with Android Chromium and iOS Safari if accessible.

## Completion criteria

**No scope slice is 'done' until:** implementation + contract tests + storybook or component state previews + 390px and 1440px screenshots + accessibility pass + audit logs for sensitive actions + docs updated. A simplistic desktop CRUD app fails the definition of done even if all endpoints work.
