# 17 · Visual direction research & anti-glass design brief (proposal)

**Date:** 2026-10-18  
**Status:** PROPOSED creative direction; user has rejected the existing glass/gradient-heavy look.  
**Decision:** Keep the ambitious feature scope and mobile-first workflows. Redesign the *visual language*, not the underlying game rules. Prefer **Arena Editorial / Solid Sportsbook** for the next design iteration, pending review of `design-lab/index.html`.

## 1. Critique of our existing prototype

The current proof of concept (`prototype/index.html`) is functional and thoughtful about interactions, but visually too similar to generic glassmorphic dashboard templates:

- The wallet hero uses a multi-stop gradient, illuminated green tinted surfaces, diagonal texture, and a large rounded box. It dominates the first viewport, pushing match choices below the fold.
- Match cards use gradients, nested soft surfaces, rounded corners inside rounded corners, and floating visual layers. It feels like a stack of translucent panes even when most backgrounds are technically opaque.
- Pill chips appear everywhere. The shapes and neon accent compete with the actual odds, names, kickoff time, and price.
- Repeated tiny uppercase captions and labels increase visual noise; important numbers need stronger editorial hierarchy.
- On desktop, the hero is very tall relative to the first slate; too much unused vertical space for a time-sensitive market catalogue.
- Mobile navigation uses `backdrop-filter: blur(...)`, creating literal frosted glass. The prototype also relies on broad `rgba` overlays and decorative glow.

**Not the problem:** dark mode itself, concise odds cards, persistent slip, bottom navigation, or the core information architecture. Keep those foundations.

## 2. Research: patterns worth borrowing (not copying)

| Reference | What research actually indicates | Transfer to Rift Exchange | Avoid |
|---|---|---|---|
| **Linear, March 2026 interface refresh** | Predictable headers, lower sidebar prominence, tight hierarchy, visual calm in a complex application. Linear described keeping central content in focus. | Consistent event header, secondary rails, compact organization, minimal ornamentation. | Copying Linear's 2025 mobile frosted-glass toolbar, or making our product look like issue tracking. |
| **Vercel Geist design system** | High-contrast accessible colors, explicitly separate primary/secondary backgrounds, purpose-built typography and scales. | Semantic design tokens, strong type scale, restrained 2–3 neutral solid surface levels. | Treating a design system as a ready-made branding identity. |
| **Shopify Polaris color guidance** | Surfaces carry hierarchy, text and fill have specified roles, color should not be the only status cue. | Solid panels, thin dividers, status badges with words/icons, coherent positive/negative roles. | Nested tinted cards where everything looks equally prominent. |
| **FotMob sports UI** | Live event header gives score/time and team identities pride of place, with stats organized behind tabs. | Format, two teams, countdown/series status, then categories/odds, all immediately scannable. | Filling the entire first viewport with a photo or decorative hero. |
| **Kalshi Pro / market workstation** | Dense market lists plus sorting/filtering, a dedicated account/positions area, a legible split-pane layout. | Strong numbers, compact odds tiles, stable desktop slip, explicit balance and open picks. | Using live exchange/order-book metaphors (we are *fixed-odds*, not trading). |
| **IBM Carbon data tables** | Consistent headers, row treatments, and information architecture for dense datasets. | Desktop league/ledger tables only where tabular scanning is best. | Forcing a desktop table into a 390px phone. |
| **Baymard mobile UX research (2026)** | Mobile users lose page overview, struggle with orientation and accidental taps; prioritized content and simpler views reduce friction. | Short wallet strip + first event visible immediately, predictable sticky navigation, obvious open slip and CTA. | Stacked big banners pushing essential choices several scrolls down. |
| **WCAG 2.2 / W3C** | Text contrast >=4.5:1 for typical text, >=3:1 for large text; AA target-size criterion minimum 24px or equivalent spacing. | Design for >=44–48px actual touch targets; maintain explicit focus rings, semantic labels, contrast testing. | Using low-contrast fashionable ghost text; color-only win/loss indicators. |

### Primary sources (reviewed October 2026)

- Linear (2026-03-12), *A calmer interface for a product in motion*: https://linear.app/now/behind-the-latest-design-refresh
- Linear (2026-03-12), *UI refresh*: https://linear.app/changelog/2026-03-12-ui-refresh
- Vercel, *Geist: Introduction*: https://vercel.com/geist/introduction
- Vercel, *Colors*: https://examples.vercel.com/geist/colors
- Vercel, *Typography*: https://vercel.com/geist/typography
- Shopify, *Polaris: Using color*: https://polaris-site-prod-kit.shopify.prod.shopifyapps.com/design/colors/using-color
- Shopify, *Polaris: Data visualizations*: https://polaris-site-prod-kit.shopify.prod.shopifyapps.com/design/data-visualizations
- FotMob reference: https://www.uxsnaps.com/soccer-match-details
- Kalshi Pro help (2026-07): https://prod-like.kalshi.com/pro/help/get-started
- Carbon data tables (2026-09-30): https://www.carbondesignsystem.com/building-blocks/core/components/data-table/specifications
- Baymard Institute, *Mobile E-commerce UX*: https://baymard.com/research/mcommerce-usability
- W3C, *SC 1.4.3 Contrast (Minimum)*: https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
- W3C, *SC 2.5.8 Target Size (Minimum)*: https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum

The following are **our product design interpretations**, not design prescriptions endorsed by the companies above.

## 3. Three researched visual directions

### A · Arena Editorial — recommended

**Mood:** premium esports broadcast × modern sportsbook × editorial sports coverage. Mature, crisp, confident, exciting on match day but calm when browsing.

- Near-black charcoal canvas, entirely solid charcoal panels, hairline dividers, no floating glow.
- An occasional striking accent, e.g., electric lime for selected odds / primary action, **not** used on every pill, caption, or border.
- Big, highly legible team names and score/format information; compact flat odds cells in gridded strips.
- Rectangular-to-modestly-rounded containers (8–12px), square-edged section separators, asymmetry from typography rather than effects.
- A slim, always-visible wallet balance at top; give event markets the hero space.
- A small editorial banner or stage title on special days only; never a giant daily-wallet hero.

Color seed (must validate every role with real UI):

```css
:root[data-theme="arena"] {
  --canvas: #0e1114;
  --shell: #12161a;
  --surface: #191e23;
  --surface-2: #242b32;
  --divider: #343c43;
  --text: #f6f8f9;
  --muted: #b7c1c9;
  --accent: #d7f46c;
  --accent-ink: #172008;
  --info: #7fd1ff;
  --win: #8ce2b1;
  --loss: #ff9f9d;
  --radius-card: 10px;
  --radius-control: 7px;
}
```

### B · Clean Sportsdesk — credible alternate

**Mood:** premium sports publication × modern fintech app. Clean light background, crisp outlined cards, electric blue for actions and selective warm yellow. If dark mode itself is part of what feels stale, choose this instead.

```css
:root[data-theme="sportsdesk"] {
  --canvas: #f2f4f3;
  --shell: #e9edec;
  --surface: #ffffff;
  --surface-2: #eef1f3;
  --divider: #ced6da;
  --text: #18212b;
  --muted: #4e5e69;
  --accent: #2057db;
  --accent-ink: #ffffff;
  --info: #2563eb;
  --win: #166a43;
  --loss: #b13c36;
  --radius-card: 10px;
  --radius-control: 8px;
}
```

### C · Match Terminal — credible alternate

**Mood:** esports analyst's event console × financial terminal. Dense dark, fine lines, monospace/tabular odds, tiny number of accent hues. Best as an optional **desktop power-user mode**, not the default for novices on a phone.

```css
:root[data-theme="terminal"] {
  --canvas: #0a0b0d;
  --shell: #0f1214;
  --surface: #14181b;
  --surface-2: #20272b;
  --divider: #354046;
  --text: #eaf0ed;
  --muted: #abbab4;
  --accent: #f4c65d;
  --accent-ink: #201806;
  --info: #83c7ff;
  --win: #7bdaa4;
  --loss: #ff9c9c;
  --radius-card: 3px;
  --radius-control: 3px;
}
```

## 4. Design rules — non-negotiable for our next prototype

1. **Absolutely no frosted glass.** Do not use `backdrop-filter`, translucent glass panels, decorative blurs, or elaborate gradients on interactive surfaces. A dark modal scrim is allowed for functionality; it is not a glass treatment.
2. **Hierarchy before decoration.** Prominent: team identities, odds, balance, locks, and selected slip. Secondary: round metadata and support labels. Muted: rarely needed notes.
3. **A sportsbook, not a corporate analytics dashboard.** Matchup cards are the key content; portfolio charts are secondary and live on a separate screen.
4. **Solid surfaces, limited nesting.** Canvas → card → selectable button. More than 3 nested panel tones is a design smell.
5. **Cap radii.** Primary cards 8–12px in Arena, buttons 6–8px, fully round only for compact status badges; no arbitrary 20–30px blobs.
6. **One signature accent.** Selected odds, primary CTA, active nav, and important positive changes may use it. Not every label and separator.
7. **Use numerical typography.** `font-variant-numeric: tabular-nums;` for odds, balances and countdowns. Strong face for odds, stable widths against data updates.
8. **Mobile above the fold.** On 390×844 aim to show league/brand header, concise wallet strip, event section title, and **first event's winner odds** without scrolling. Test in the browser with safe areas and real text lengths.
9. **Selection requires explicit state.** A selected odds tile changes filled background + has a check icon + has `aria-pressed`; odds updates are announced and accepted only on explicit review.
10. **Mobile slip is a solid sheet.** Responsive bottom sheet with overlay and focus management; no blur. Pin summary/CTA where possible; never hide the active stake field behind keyboard.
11. **Text ≥14px for important secondary copy; body 16px.** Meta labels can be 12–13px sparingly but not critical instructions, odds, or time labels. Check 200% zoom and font scaling.
12. **Meaningful motion only.** 120–180ms pressed/selection feedback. Respect reduced motion. No animated gradients, floating orbs, or pulse glows.
13. **High contrast and touch accessibility.** WCAG 2.2 AA for text/controls where applicable, practical interactive target 44–48px, visible keyboard focus, screen reader semantics.
14. **Never rely on color alone.** “Won / Lost / Void / Open / Locked” text and suitable iconography accompany any color.
15. **Don’t copy an existing brand.** Use external references for hierarchy and mechanics only; original branding, original team assets, and fictional prototype fixtures.

## 5. Recommended component layout

### Today on a phone

```text
┌────────────────────────────────┐
│ RIFT EXCHANGE       ● 3 FRIENDS│
│ SWISS · OCT 23                 │
├────────────────────────────────┤
│ 4,250 RC available   +1k today│   ← flat compact 64–76px bar
├────────────────────────────────┤
│ TODAY'S MATCHES      6 events ›│
│ [All] Winners Draft Props      │
│                                │
│ 12:00  SWISS · BO1    LOCKS 32m│
│ ATLAS      — VS —        NOVA  │
│                                │
│ SERIES WINNER                  │
│ ┌─────────────┬──────────────┐ │
│ │ Atlas       │ Nova         │ │
│ │ 1.62×       │ 2.40×        │ │
│ └─────────────┴──────────────┘ │
│ 18 MORE MARKETS                │
├────────────────────────────────┤
│ NEXT EVENT ...                 │
│                                │
│ [ 2 PICKS   REVIEW SLIP  →   ] │ ← sticky only when nonempty
│ Today Explore Picks League You │
└────────────────────────────────┘
```

### Component contract

**Odds rows:** the proposition is clear in text; two/three choices are evenly distributed; price is 18–22px bold, line-height stable; button is a single target; hover only on desktop; no nested glass tiles; locked tiles retain text and show why.  
**Wallet:** compact but memorable; display `Available`, `Staked`, and optional day grant without occupying the main screen.  
**League:** 3 rows + standings swing chips, not oversized podium art. A small celebratory trophy illustration or medal may appear in winner screens only.  
**Portfolio:** numbers/data columns aligned, mobile tickets as flat stacked rows; open, settled, void states explicit.  
**Event page:** scoreboard-like top header; outcome category tabs; market rows; right-rail slip on desktop.  
**Admin:** separate task-focused UI; can be denser but use same tokens and status styles.

## 6. Mobile acceptance criteria

- At 320 / 360 / 390 / 430px: zero unintended horizontal scrolling; odds text wraps rather than truncating the only meaningful distinction.
- At 390×844, the first actionable match market is visible before scrolling with default text size; test on browser and real phone.
- ≥44px clickable height on all primary taps; WCAG 2.2 minimum hit-area rule still checked.
- Odds tile selected via keyboard and touch; selection state audible to screen reader.
- When user picks outcome: mobile slip CTA becomes available with selection count; selected odds remain selected after navigation.
- Sheet opening/closing never traps page behind inaccessible content or loses focus.
- Stake values and total returns are readable with keyboard open; no optimistic acceptance.
- Full-page 200% zoom and reduced motion modes pass manual inspection.
- Performance budget: minimal font files; no decorative image/video background; no large blur effects; optimize first-viewport content rendering.

## 7. Suggested build instructions for agent

> Before touching app logic, implement a visual-only skin pass. Read `17_VISUAL_DIRECTION_RESEARCH.md` and `04_UX_DESIGN_SYSTEM.md`. Default to **Arena Editorial** but keep a design token architecture that supports alternative themes. Remove frosted-glass styling, glow, decorative gradients, exaggerated radii, oversized wallet hero and excessive pill chips. Rebuild Today → Event → Slip → My Picks → League with solid surfaces and typographic hierarchy. Preserve all existing flows and safety rules. Capture 390px and 1440px screenshots, verify 320px and 200% zoom, and demonstrate selection/quote/receipt states. Do not change market or economy rules as part of the redesign. Any three-style demo belongs in `design-lab/` and should not be confused with shipping product UX.

## 8. What should be decided after visual review

- Does the preferred direction feel **more sports broadcast** (Arena) or **more clean editorial** (Sportsdesk)?
- Dark-only vs. support both light/dark while keeping shared layout and components?
- Odds presentation density: default 2 choices/row on mobile; 3+ with horizontal paged groups only when necessary.
- Team identity: small original-IP monogram now; approved assets later if allowed.
- Animations: intentionally restrained, never casino-like dopamine cues.

**Do not** lock final colors/radii until all three styles are inspected on a phone at 390px, desktop at 1440px, and with the same sample markets.
