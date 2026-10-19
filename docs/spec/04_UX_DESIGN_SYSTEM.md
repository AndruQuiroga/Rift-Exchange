# 04 · UI/UX design system — primary product requirement

> **Design direction update (2026-10-18):** The earlier glass/gradient-heavy proof of concept was rejected. Treat the palette, radius and any glow/gradient examples below as **superseded visual proposals**. See [`17_VISUAL_DIRECTION_RESEARCH.md`](17_VISUAL_DIRECTION_RESEARCH.md) for the new anti-glass requirement, three alternate palettes, and the proposed **Arena Editorial** solid-surface direction. All workflow, responsiveness, interaction and accessibility requirements below remain valid.

**Design target:** a polished, sports-broadcast-inspired consumer product that happens to be a private three-player game. Not an admin dashboard with tables. Mobile is first, not retrofitted. The visual direction is a restrained **night-ink interface, warm lime action, cool blue secondary emphasis, dense-but-readable odds tiles, strong typography, and large breathable cards**. Do not use real sportsbook branding or clone any existing app.

## UX north star

Open on a phone → understand what's happening today → spot a compelling market → choose odds → adjust stake in a bottom sheet → understand payout → confirm → immediately see a receipt and updated wallet. Ideal: **three meaningful taps plus stake entry** from market to submission. More gestures for optional analysis, never compulsory.

## Primary mobile navigation

Bottom navigation with icon + short text, fixed above the safe-area inset:

`Today` · `Explore` · `My Picks` · `League` · `Profile`

Bottom sheet for Slip floats above the nav and never hides the active field. Slips remain intact while navigating. Desktop transforms to left rail/topbar and optional persistent right-rail slip/portfolio (min-width ~1180px), with central event cards that don't exceed readable width.

## Every required screen and behavior

| Screen | First impression / primary action | Important secondary content |
| --- | --- | --- |
| Today | Hero wallet summary, active match day, featured 2–3 fixtures, odds cards | Grant celebration subtle, next locks, available balance |
| Explore | Search and chips: All, Matches, Draft, Players, Futures | Sort by time or category; favorite team filters |
| Event | Series badge, team identities, score if live, status, time | Scrollable market tabs, market descriptions, stat provenance |
| Market detail | Clear proposition + outcome odds, rule footnote | Historical odds line, disabled state reason |
| Slip (sheet) | Selected outcomes, decimal odds, editable stake, **return & net gain** | Removable rows, error handling, all-in action, confirmation |
| Receipt | Accepted, timestamp, accepted quote, unique ID | Share a clean image/card later, link to My Picks |
| My Picks | Segmented Open / Settled; total at risk; result statuses | Sort, filter, market grouping, proof view |
| League | All 3 friends, provisional standings, daily swings | Leader stat, locked picks reveal, last-week activity |
| Player Profile | Win rate, ROI, biggest hit, losing streak | History chart with deposited grants annotated |
| Wallet | Available, open stakes, credits granted, realized net | Immutable ledger chronological entries |
| Admin | At-a-glance pending results, markets nearing lock | High priority error queue, source quality |
| Admin Market Builder | Template -> scope -> outcome -> evidence -> odds -> publish | Review summary, visibility warnings, versioned rules |
| Admin Settlement Inbox | Candidate result, evidence source, affected selections | Preview deltas before commit, double verification optional |
| Settings | Timezone, spoiler blur, notifications, reduced motion | Legal disclaimer, provenance, season switches |

## Phone wireframe — Today (390 × 844 conceptual)

```text
┌──────────────────────────────────┐
│  ◌ RIFT EXCHANGE       ◍ Profile │ ← Safe-area aware
│  WORLDS 2026  ·  SWISS           │
│                                  │
│ ┌──────────────────────────────┐ │
│ │ Available             + Day  │ │
│ │  4,250 RC           +1,000 RC│ │
│ │ Open stakes 2,750   View ›   │ │
│ └──────────────────────────────┘ │
│                                  │
│  Fri, Oct 23      8 events today │
│  [All] [Winners] [Draft] [Props] │ ← Horizontal chips
│                                  │
│ ┌──────────────────────────────┐ │
│ │ SWISS · BO1    Locks 0h 37m │ │
│ │ ATLAS         vs      NOVA  │ │
│ │                              │ │
│ │ Series winner                │ │
│ │ [ ATLAS 1.62× ][ NOVA 2.40×] │ │ ← 48px targets
│ │   +18 more markets        ›  │ │
│ └──────────────────────────────┘ │
│                                  │
│ ┌──────────────────────────────┐ │
│ │ ... next event card ...      │ │
│ └──────────────────────────────┘ │
│                                  │
│ ╭──────────────────────────────╮ │
│ │  2 picks       Review slip › │ │ ← Floating when nonempty
│ ╰──────────────────────────────╯ │
│  Today Explore Picks League Me   │ ← 5-tab bottom nav
└──────────────────────────────────┘
```

Fictional team names and odds are deliberate mock content only.

## Phone wireframe — Slip sheet

```text
╭──────────────────────────────────╮
│  ━                               │
│  Your slip                   ×   │
│  2 independent picks             │
│ ┌──────────────────────────────┐ │
│ │ Atlas wins               1.62×│ │
│ │ Stake RC  [ 400    ]     ✕   │ │
│ │ If correct: 648 RC            │ │
│ ├──────────────────────────────┤ │
│ │ 2–1 exact score          3.40×│ │
│ │ Stake RC  [ 250    ]     ✕   │ │
│ │ If correct: 850 RC            │ │
│ └──────────────────────────────┘ │
│ [ +100 ] [ 25% ] [ 50% ] [ ALL ] │
│ --------------------------------│
│ Staked                   650 RC │
│ Total possible return  1,498 RC │
│ Net gain if both win      848 RC │
│ Available after         3,600 RC │
│ [ Review & place 2 picks  →    ]│
│ Play credits only • No value     │
╰──────────────────────────────────╯
```

When slip selections are independent singles, total 'possible return' is **only if all succeed**. Never mislabel it a guaranteed payout. If there are conflicting picks on different events, copy should emphasize conditionality.

## Desktop wireframe

```text
┌────── rail ─────┬──────────── Today · center ────────────┬── slip rail ────────┐
│ brand          │ topbar: tournament · search · account  │ Available 4,250 RC│
│ Today          │                                          │ 2 picks           │
│ Explore        │ large featured match / round summary     │ stake controls    │
│ My Picks       │ ┌── event card ─┬── event card ─┐        │ potential return  │
│ League         │ │ winner odds   │ │ draft odds  │        │ [PLACE PICKS]     │
│ History        │ └───────────────┴───────────────┘        │                   │
│ Profile        │ trending markets · activity timeline     │ payout explainer  │
└────────────────┴──────────────────────────────────────────┴───────────────────┘
```

## Design token proposal

| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#090F18` | Overall deep ink |
| `--surface` | `#121B29` | Content cards |
| `--surface-raised` | `#1A2738` | Active tiles/sheet |
| `--line` | `#2B394B` | Separators |
| `--text` | `#F4F8FB` | Headings and balances |
| `--muted` | `#B1C0CC` | Secondary info |
| `--accent` | `#D7F36B` | Primary action / winning glow |
| `--info` | `#8FD1E7` | Neutral live/secondary |
| `--positive` | `#9CE5BB` | Won / good balance |
| `--negative` | `#FF9A9F` | Lost / risks / errors |
| Radius | 14 / 20 / 26px | Tiles, cards, sheets |
| Spacing | 4/8/12/16/24/32px | Consistent rhythm |
| Typography | system/Inter, tabular numerals | Short labels; stable RC digits |

Colors are starting points; perform contrast checks for each use. Accessible text ≥ 4.5:1 for standard-size text. Do not encode win/loss in color alone.

## Detailed component behavior

**Odds tile:** value as largest line, market outcome above or beside; `selected` has persistent color fill, border, checkmark, and `aria-pressed=true`. `suspended` shows lock icon and why; `stale` animates once, then displays 'updated price' label; don't silently auto-submit. A tile never moves position because its value changed (tabular numbers and stable width).

**Event card:** stage/format/clock header, two team panels, compact winner market, `more markets` affordance. Support 320px without horizontal overflow, keyboard focus, skeleton when loading, and text-only fallback if assets unavailable.

**Wallet bar:** available balance prominent; open stake visually subordinate; grants as subtle toast with ledger entry. If available=0, show next scheduled grant date without shame or guilt nudging.

**Slip input:** numeric keyboard `inputmode=numeric`, currency suffix, input validation on blur and submit, easy clear, presets, use exact whole RC only. Keep keyboard + primary action visible via sheet resize/pan. If user taps an odd while slip open, update the selection not duplicate it.

**League view:** main trophy row plus concise 3-person leaderboard. Show balances and open stake separately; if mid-event, label 'provisional'. Activity feed hides picks until each market locks (privacy fairness default). On reveal, list user-friendly summaries, not raw JSON.

**Data status:** clear **Scheduled / Open / Locked / Live / Awaiting data / Grading / Won / Lost / Void / Corrected**. If a fixture is live, view odds but no v1 betting; never imply acceptance is possible.

## Mobile-specific requirements

- Minimum 44×44px touch target; odds tiles typically ≥48px high; minimum 8px between close interactive targets.
- iOS/Android safe areas via `env(safe-area-inset-bottom)`; fixed nav cannot overlap slip confirm.
- Short top section visible without scrolling: wallet + first match + odds on 390×844; collapse noncritical metadata.
- Avoid hover-only controls; prioritize touch, thumb reach, native select when helpful.
- Inputs never zoom on iOS (`font-size: 16px+`).
- Better empty states: 'No active markets today; next slate ...', not empty tables.
- Skeletons for 300ms+ loads; nonblocking errors with retry; optimistic **selection** UI only, not optimistic financial acceptance.
- Use localized event time with explicit zone switch and countdown; UTC timestamps on server.
- Announce quote conflicts, toasts, slip totals, and settlement changes accessibly (`aria-live`).
- Persist unsubmitted slip locally and re-validate everything on checkout.
- Focus trap in modal/sheet; Escape/back closes; opening focus moves inside; returning focus to triggering tile.
- Prefers-reduced-motion disables movement transitions, not status feedback.

## Usability testing protocol

Put each friend on a phone for ten minutes and watch, don't coach. Ask them to: (1) pick winner, (2) add first-game champion prediction, (3) stake 75 RC and change to 400, (4) explain total return vs net, (5) locate a losing pick, (6) explain why a market is locked, (7) find next grant. Record confusion, taps, keyboard obstruction, and task completion. **A screen is not complete simply because it renders.**
