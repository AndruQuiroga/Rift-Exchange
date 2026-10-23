"use client";

import type { ReactNode } from "react";
import { oddsSpoken, potentialReturn, rc } from "@/lib/format";
import { initials, useFriendsOnMatch } from "@/lib/friends";
import { usePlaced } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import { teamColor, teamName } from "@/lib/teams";
import type { EventT, MarketT, OutcomeT, Team } from "@/lib/types";
import { TeamMark } from "./bits";
import { eventLabel } from "./EventCard";
import { IconCheck, IconLock } from "./icons";
import { Odds } from "./Odds";
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
export function PickButton({ event, market, outcome, className = "", label, children, style }: {
  event: EventT; market: MarketT; outcome: OutcomeT | undefined; className?: string; label: string; children?: ReactNode;
  style?: React.CSSProperties;
}) {
  const slip = useSlip();
  const placed = usePlaced();
  if (!outcome) return <span className={`pk empty ${className}`} aria-hidden="true" />;
  const selected = slip.isSelected(outcome.id);
  const held = placed.has(outcome.id);
  const won = market.result && !market.result.void && market.result.winning_codes.includes(outcome.code);
  // Known before it pays (D-032): the winning side lights up the moment the data shows it.
  const called = !market.result && market.call && !market.call.void && market.call.winning_codes.includes(outcome.code);
  const open = market.state === "OPEN" && outcome.odds !== null;
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

/** One line under a market saying what you have on it: the slip pick and its return, or what is placed. */
export function PickNote({ market }: { market: MarketT }) {
  const slip = useSlip();
  const placed = usePlaced();
  const line = slip.lines.find((l) => l.marketId === market.id);
  if (line) {
    return (
      <p className="pk-note num">
        Your pick · <b>{line.outcomeLabel}</b>
        {line.stake ? <> · {rc(line.stake)} RC → returns <b>{rc(potentialReturn(line.stake, line.odds))} RC</b></> : null}
      </p>
    );
  }
  const held = market.outcomes.filter((o) => placed.has(o.id));
  const call = market.result ? null : market.call;
  const shown = call ? market.outcomes.filter((o) => call.winning_codes.includes(o.code)).map((o) => o.label).join(", ") : "";
  if (!held.length) {
    return call ? (
      <p className="pk-note num reveal">
        {call.void ? "Void" : `Result: ${shown}`} · <PayoutNote payAt={call.pays_at} final={call.final} />
      </p>
    ) : null;
  }
  const winning = !!call && !call.void && held.some((o) => call.winning_codes.includes(o.code));
  return (
    <p className={`pk-note placed num${call ? " reveal" : ""}`}>
      Placed · {held.map((o) => `${o.label} ${rc(placed.get(o.id) ?? 0)} RC`).join(" · ")}
      {call ? (
        <>
          {" · "}
          <b className={call.void ? "" : winning ? "win" : "loss"}>{call.void ? "Void" : winning ? "Winning" : "Losing"}</b>
          {winning || call.void ? <>, <PayoutNote payAt={call.pays_at} final={call.final} /></> : null}
        </>
      ) : null}
    </p>
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

/** A team-vs-team market as one row: the first team's price on the left, the second's on the right. */
export function H2HRow({ event, market, label, left, right, hint }: {
  event: EventT; market: MarketT; label: string; left?: OutcomeT; right?: OutcomeT; hint?: string;
}) {
  const l = left ?? market.outcomes.find((o) => o.code === "A");
  const r = right ?? market.outcomes.find((o) => o.code === "B");
  return (
    <div className="h2h">
      <div className="h2h-row">
        <PickButton event={event} market={market} outcome={l} label={`${l?.label ?? ""}, ${label}`} />
        <span className="h2h-label">
          {label}
          {hint ? <small>{hint}</small> : null}
        </span>
        <PickButton event={event} market={market} outcome={r} label={`${r?.label ?? ""}, ${label}`} />
      </div>
      <PickNote market={market} />
    </div>
  );
}

/** A market whose answers aren't one per team (dragon type, games played, yes/no): its options in a row. */
export function ChoiceRow({ event, market, label, short }: { event: EventT; market: MarketT; label: string; short?: (o: OutcomeT) => string }) {
  return (
    <div className="h2h">
      <div className="choice-row">
        <span className="h2h-label left">{label}</span>
        <div
          className={`choice-opts${market.outcomes.length > 4 ? " many" : ""}`}
          style={market.outcomes.length > 4 ? undefined : { gridTemplateColumns: `repeat(${market.outcomes.length}, minmax(0, 1fr))` }}
        >
          {market.outcomes.map((o) => (
            <PickButton key={o.id} event={event} market={market} outcome={o} className="chip-pk" label={`${label}: ${o.label}`}>
              <span className="pk-lbl">{short ? short(o) : o.label}</span>
            </PickButton>
          ))}
        </div>
      </div>
      <PickNote market={market} />
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
