"use client";

import type { ReactNode } from "react";
import { odds as fmtOdds, oddsSpoken, potentialReturn, rc } from "@/lib/format";
import { initials, useFriendsOnMatch } from "@/lib/friends";
import { blended, mixed, useHoldings, usePlaced, type Holding } from "@/lib/hooks";
import { useSlip, type SlipLine } from "@/lib/slip";
import { teamColor, teamName } from "@/lib/teams";
import type { EventT, MarketT, OutcomeT, Team } from "@/lib/types";
import { TeamMark } from "./bits";
import { eventLabel } from "./EventCard";
import { IconCheck, IconLock } from "./icons";
import { Odds } from "./Odds";
import { CancelPick } from "./CancelPick";
import { PayoutNote } from "./Timing";

/** Friends who hold this outcome (shown once its market locks): a stack of initials. */
export function FriendDots({ eventId, outcomeId }: { eventId: string; outcomeId: string }) {
  const { byOutcome } = useFriendsOnMatch(eventId);
  const picks = byOutcome.get(outcomeId) ?? [];
  if (!picks.length) return null;
  const names = [...new Set(picks.map((p) => p.user?.display_name ?? "A friend"))];
  return (
    <span className="fdots" title={names.join(", ")} aria-label={`Also picked by ${names.join(", ")}`}>
      {names.slice(0, 3).map((n) => <span key={n} className="fdot">{initials(n)}</span>)}
      {names.length > 3 ? <span className="fdot more">+{names.length - 3}</span> : null}
    </span>
  );
}

/**
 * Every price on the match page is this one button, with the same four looks: idle; in your slip
 * (filled, with a check); already placed (outlined, "Placed"); closed (muted, with a lock).
 * Tap toggles; tapping the other side of a market moves your pick there.
 */
export function PickButton({ event, market, outcome, className = "", label, children, style, blocked }: {
  event: EventT; market: MarketT; outcome: OutcomeT | undefined; className?: string; label: string; children?: ReactNode;
  style?: React.CSSProperties; blocked?: boolean;
}) {
  const slip = useSlip();
  const placed = usePlaced();
  if (!outcome) return <span className={`pk empty ${className}`} aria-hidden="true" />;
  const selected = slip.isSelected(outcome.id);
  const held = placed.has(outcome.id);
  const won = market.result && !market.result.void && market.result.winning_codes.includes(outcome.code);
  // Known before it pays (D-032): the winning side lights up the moment the data shows it.
  const called = !market.result && market.call && !market.call.void && market.call.winning_codes.includes(outcome.code);
  // blocked: you called this blind, so the after-draft price waits until that bet is cancelled (D-040).
  const open = market.state === "OPEN" && outcome.odds !== null && !blocked;
  return (
    <button
      type="button"
      className={`pk ${className}${won ? " won" : ""}${called ? " called" : ""}${held ? " held" : ""}`}
      aria-pressed={selected}
      style={style}
      disabled={!open && !selected}
      onClick={() => slip.toggle(market, outcome, eventLabel(event))}
      aria-label={`${label}, ${won ? "won" : oddsSpoken(outcome.odds)}${selected ? ", in slip" : ""}${held ? ", already placed" : ""}`}
    >
      {children}
      <span className="pk-px num">
        {selected ? <IconCheck width={14} height={14} aria-hidden="true" /> : !open && !won ? <IconLock width={12} height={12} aria-hidden="true" /> : null}
        {won ? "Won" : <Odds value={outcome.odds} />}
      </span>
      {held && !selected ? <span className="pk-tag">Placed</span> : null}
      {called ? <span className="pk-tag result">{market.call?.final ? "Result" : "Live"}</span> : null}
      <FriendDots eventId={event.id} outcomeId={outcome.id} />
    </button>
  );
}

/**
 * What you have on a market, under its prices. Bets on one outcome are taken together (each top-up keeps its own
 * odds): the total staked, the blended price and the total return, then each bet with its Cancel. blind: the
 * blind market of an after-draft row (D-040), so a pick called before the draft still shows, tagged Blind.
 */
export function PickNote({ market, blind, tag }: { market: MarketT; blind?: MarketT; tag?: string }) {
  const slip = useSlip();
  const holdings = useHoldings();
  const line = slip.lines.find((l) => l.marketId === market.id);
  const rows = [...(blind ? [{ m: blind, tag: "Blind" }] : []), { m: market, tag: tag ?? (blind ? "After draft" : null) }]
    .flatMap(({ m, tag }) => m.outcomes.map((o) => ({ m, o, tag, h: holdings.get(o.id) })))
    .filter((r): r is typeof r & { h: Holding } => !!r.h);
  const call = market.result ? null : market.call;
  const shown = call ? market.outcomes.filter((o) => call.winning_codes.includes(o.code)).map((o) => o.label).join(", ") : "";
  if (!rows.length && !line) {
    return call ? (
      <p className="pk-note num reveal">
        {call.void ? "Void" : `Result: ${shown}`} · <PayoutNote payAt={call.pays_at} final={call.final} />
      </p>
    ) : null;
  }
  return (
    <div className="pk-notes">
      {rows.map(({ m, o, tag, h }) => {
        const c = m.result ? null : m.call;
        const verdict = !c ? null : c.void ? "Void" : c.winning_codes.includes(o.code) ? "Winning" : "Losing";
        const many = h.picks.length > 1;
        return (
          <div className={`pk-note placed num${c ? " reveal" : ""}`} key={o.id}>
            <div className="pkn-main">
              {tag ? <span className={`pkn-tag${tag === "Blind" ? " blind" : ""}`}>{tag}</span> : <span className="pkn-k">Your bet</span>}
              <b>{o.label}</b>
              <span>{rc(h.stake)} RC @ {fmtOdds(blended(h))}{mixed(h) ? " avg" : ""} → <b>{rc(h.ret)} RC</b></span>
              {verdict ? <b className={verdict === "Winning" ? "win" : verdict === "Losing" ? "loss" : ""}>{verdict}</b> : null}
              {c && verdict !== "Losing" ? <PayoutNote payAt={c.pays_at} final={c.final} /> : null}
              {many ? null : <CancelPick pick={h.picks[0]} compact />}
            </div>
            {many ? (
              <ul className="pkn-bets" aria-label={`Your ${h.picks.length} bets on ${o.label}`}>
                {h.picks.map((p) => (
                  <li key={p.id}>
                    <span>{rc(p.stake_rc)} @ {fmtOdds(p.odds)} → {rc(p.potential_return_rc)}</span>
                    <CancelPick pick={p} compact />
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        );
      })}
      {line ? <SlipNote line={line} holding={holdings.get(line.outcomeId)} /> : null}
    </div>
  );
}

/** The pick in your slip on this market, and what it does to a bet you already hold on the same side. */
function SlipNote({ line, holding }: { line: SlipLine; holding?: Holding }) {
  const ret = line.stake ? potentialReturn(line.stake, line.odds) : 0;
  return (
    <div className="pk-note num">
      <div className="pkn-main">
        <span className="pkn-tag slip">In slip</span>
        <b>{line.outcomeLabel}</b>
        {line.stake ? <span>{rc(line.stake)} RC @ {fmtOdds(line.odds)} → <b>{rc(ret)} RC</b></span> : <span className="muted">add a stake</span>}
      </div>
      {holding && line.stake ? (
        <div className="pkn-total">
          With your {rc(holding.stake)} RC: <b>{rc(holding.stake + line.stake)} RC</b> @{" "}
          {!mixed(holding) && Number(holding.picks[0].odds) === Number(line.odds) ? fmtOdds(line.odds)
            : `${fmtOdds(blended({ ...holding, stake: holding.stake + line.stake, ret: holding.ret + ret }))} avg`} → <b>{rc(holding.ret + ret)} RC</b>
        </div>
      ) : null}
    </div>
  );
}

/** The winner face-off: each team a tall card in its colour, its chance and price, VS between them. */
export function WinnerCards({ event, market, caption }: { event: EventT; market: MarketT; caption: string }) {
  const odds = (code: string) => Number(market.outcomes.find((o) => o.code === code)?.odds ?? 0);
  const [pa, pb] = [odds("A"), odds("B")].map((o) => (o > 0 ? 1 / o : 0));
  const chance = (code: "A" | "B") => (pa + pb > 0 ? Math.round((100 * (code === "A" ? pa : pb)) / (pa + pb)) : null);
  const side = (code: "A" | "B", team: Team | null) => (
    <PickButton
      event={event}
      market={market}
      outcome={market.outcomes.find((o) => o.code === code)}
      className={`win-card${code === "B" ? " right" : ""}`}
      style={{ "--team": teamColor(team) } as React.CSSProperties}
      label={`${teamName(team)} to win`}
    >
      <span className="win-ribbon" aria-hidden="true">Your pick</span>
      <TeamMark team={team} large />
      <span className="win-code">{team?.code ?? "TBD"}</span>
      <span className="win-name">{teamName(team)}{chance(code) !== null ? ` · ${chance(code)}% to win` : ""}</span>
    </PickButton>
  );
  return (
    <section aria-label={caption}>
      <div className="win-cards">
        {side("A", event.team_a)}
        <span className="win-vs" aria-hidden="true">VS</span>
        {side("B", event.team_b)}
      </div>
      <PickNote market={market} />
    </section>
  );
}

/** A team-vs-team market as one row: the first team's price on the left, the second's on the right. blind: the
 * blind market behind an after-draft row (D-040); holding it blocks this one's prices until it is cancelled. */
export function H2HRow({ event, market, label, left, right, hint, blind }: {
  event: EventT; market: MarketT; label: string; left?: OutcomeT; right?: OutcomeT; hint?: string; blind?: MarketT;
}) {
  const holdings = useHoldings();
  const blocked = !!blind && blind.outcomes.some((o) => holdings.has(o.id));
  const l = left ?? market.outcomes.find((o) => o.code === "A");
  const r = right ?? market.outcomes.find((o) => o.code === "B");
  // D-041: a third answer for neither team ("No soul", "No Baron"), a small pick under the label.
  const none = market.outcomes.find((o) => o.code === "NONE");
  return (
    <div className="h2h">
      <div className="h2h-row">
        <PickButton event={event} market={market} outcome={l} label={`${l?.label ?? ""}, ${label}`} blocked={blocked} />
        <span className="h2h-label">
          {label}
          {hint ? <small>{hint}</small> : null}
          {none ? (
            <PickButton event={event} market={market} outcome={none} className="mid-pk" label={`${none.label}, ${label}`} blocked={blocked}>
              <span className="pk-lbl">{none.label}</span>
            </PickButton>
          ) : null}
        </span>
        <PickButton event={event} market={market} outcome={r} label={`${r?.label ?? ""}, ${label}`} blocked={blocked} />
      </div>
      <PickNote market={market} blind={blind} />
    </div>
  );
}

/** A market whose answers aren't one per team (dragon type, games played, yes/no): its options in a row. */
export function ChoiceRow({ event, market, label, short, blind }: {
  event: EventT; market: MarketT; label: string; short?: (o: OutcomeT) => string; blind?: MarketT;
}) {
  const holdings = useHoldings();
  const blocked = !!blind && blind.outcomes.some((o) => holdings.has(o.id));
  return (
    <div className="h2h">
      <div className="choice-row">
        <span className="h2h-label left">{label}</span>
        <div
          className={`choice-opts${market.outcomes.length > 4 ? " many" : ""}`}
          style={market.outcomes.length > 4 ? undefined : { gridTemplateColumns: `repeat(${market.outcomes.length}, minmax(0, 1fr))` }}
        >
          {market.outcomes.map((o) => (
            <PickButton key={o.id} event={event} market={market} outcome={o} className="chip-pk" label={`${label}: ${o.label}`} blocked={blocked}>
              <span className="pk-lbl">{short ? short(o) : o.label}</span>
            </PickButton>
          ))}
        </div>
      </div>
      <PickNote market={market} blind={blind} />
    </div>
  );
}

/** Team codes pinned above the rows, so "left = GEN, right = IG" never has to be remembered. */
export function H2HHead({ event }: { event: EventT }) {
  return (
    <div className="h2h-head" aria-hidden="true">
      <span><TeamMark team={event.team_a} />{event.team_a?.code ?? "TBD"}</span>
      <span className="vs">VS</span>
      <span className="right">{event.team_b?.code ?? "TBD"}<TeamMark team={event.team_b} /></span>
    </div>
  );
}

/** A market that isn't open yet, shown greyed out so the page says what is coming and when. */
export function LockedRow({ label, left, right }: { label: string; left: string; right: string }) {
  return (
    <div className="h2h locked" aria-label={`${label}: opens when the game loads`}>
      <div className="h2h-row">
        <button type="button" className="pk" disabled tabIndex={-1}>
          <span className="pk-px"><IconLock width={12} height={12} aria-hidden="true" /> {left}</span>
        </button>
        <span className="h2h-label">{label}</span>
        <button type="button" className="pk" disabled tabIndex={-1}>
          <span className="pk-px"><IconLock width={12} height={12} aria-hidden="true" /> {right}</span>
        </button>
      </div>
    </div>
  );
}
