"use client";

import type { ReactNode } from "react";
import { oddsSpoken, potentialReturn, rc } from "@/lib/format";
import { usePlaced } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import { teamName } from "@/lib/teams";
import type { EventT, MarketT, OutcomeT, Team } from "@/lib/types";
import { TeamMark } from "./bits";
import { eventLabel } from "./EventCard";
import { IconCheck, IconLock } from "./icons";
import { Odds } from "./Odds";

/**
 * Every price on the match page is this one button, with the same four looks: idle; in your slip
 * (filled, with a check); already placed (outlined, "Placed"); closed (muted, with a lock).
 * Tap toggles; tapping the other side of a market moves your pick there.
 */
export function PickButton({ event, market, outcome, className = "", label, children }: {
  event: EventT; market: MarketT; outcome: OutcomeT | undefined; className?: string; label: string; children?: ReactNode;
}) {
  const slip = useSlip();
  const placed = usePlaced();
  if (!outcome) return <span className={`pk empty ${className}`} aria-hidden="true" />;
  const selected = slip.isSelected(outcome.id);
  const held = placed.has(outcome.id);
  const won = market.result && !market.result.void && market.result.winning_codes.includes(outcome.code);
  const open = market.state === "OPEN" && outcome.odds !== null;
  return (
    <button
      type="button"
      className={`pk ${className}${won ? " won" : ""}${held ? " held" : ""}`}
      aria-pressed={selected}
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
  if (!held.length) return null;
  return (
    <p className="pk-note placed num">
      Placed · {held.map((o) => `${o.label} ${rc(placed.get(o.id) ?? 0)} RC`).join(" · ")}
    </p>
  );
}

/** The big winner cards at the top of a match or game: each team is one tap target with its price. */
export function WinnerCards({ event, market, caption }: { event: EventT; market: MarketT; caption: string }) {
  const side = (code: "A" | "B", team: Team | null) => (
    <PickButton event={event} market={market} outcome={market.outcomes.find((o) => o.code === code)} className={`win-card${code === "B" ? " right" : ""}`} label={`${teamName(team)} to win`}>
      <TeamMark team={team} large />
      <span className="win-code">{team?.code ?? "TBD"}</span>
      <span className="win-name">{teamName(team)}</span>
    </PickButton>
  );
  return (
    <section aria-label={caption}>
      <div className="win-cards">
        {side("A", event.team_a)}
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
