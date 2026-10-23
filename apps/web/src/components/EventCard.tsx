"use client";

import Link from "next/link";
import type { EventT, MarketT } from "@/lib/types";
import { countdown, odds as fmtOdds, kickoff } from "@/lib/format";
import { usePlaced } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import { teamName } from "@/lib/teams";
import { EventStatus, TeamMark } from "./bits";
import { IconCheck } from "./icons";
import { LockTimer } from "./Timing";

export function eventLabel(e: EventT) {
  return `${e.team_a?.code ?? "TBD"} vs ${e.team_b?.code ?? "TBD"}`;
}

export function Matchup({ event, large }: { event: EventT; large?: boolean }) {
  const showScore = event.status === "LIVE" || event.status === "COMPLETED";
  return (
    <div className="matchup">
      <div className="team">
        <TeamMark team={event.team_a} large={large} />
        <div>
          <div className="team-name">{event.team_a?.code ?? "TBD"}</div>
          <div className="team-full">{event.team_a ? teamName(event.team_a) : "To be drawn"}</div>
        </div>
      </div>
      {showScore ? (
        <div className="score num" aria-label={`Score ${event.score[0]} to ${event.score[1]}`}>
          {event.score[0]}–{event.score[1]}
        </div>
      ) : (
        <div className="vs">VS</div>
      )}
      <div className="team right">
        <TeamMark team={event.team_b} large={large} />
        <div>
          <div className="team-name">{event.team_b?.code ?? "TBD"}</div>
          <div className="team-full">{event.team_b ? teamName(event.team_b) : "To be drawn"}</div>
        </div>
      </div>
    </div>
  );
}

/** Your side of a match winner, from the slip or what you have placed: the indicator on every match card. */
export function useMyWinnerPick(market: MarketT | null | undefined): { code: string; placed: boolean } | null {
  const slip = useSlip();
  const placed = usePlaced();
  if (!market) return null;
  const inSlip = market.outcomes.find((o) => slip.isSelected(o.id));
  if (inSlip) return { code: inSlip.code, placed: false };
  const held = market.outcomes.find((o) => placed.has(o.id));
  return held ? { code: held.code, placed: true } : null;
}

/** Each team's chance from the winner prices (overround removed), as a split bar with the prices under it. */
export function ChanceBar({ event, market, compact }: { event: EventT; market: MarketT; compact?: boolean }) {
  const a = market.outcomes.find((o) => o.code === "A");
  const b = market.outcomes.find((o) => o.code === "B");
  if (!a?.odds || !b?.odds) return null;
  const pa = 1 / Number(a.odds);
  const pb = 1 / Number(b.odds);
  const share = Math.round((100 * pa) / (pa + pb));
  const fav = share >= 50 ? "A" : "B";
  return (
    <span className={`chance${compact ? " compact" : ""}`} aria-label={`${event.team_a?.code} ${share}%, ${event.team_b?.code} ${100 - share}%`}>
      <span className="bar" aria-hidden="true">
        <span className={fav === "A" ? "fav" : ""} style={{ width: `${share}%` }} />
        <span className={fav === "B" ? "fav" : ""} style={{ width: `${100 - share}%` }} />
      </span>
      <span className="nums num" aria-hidden="true">
        <span>{share}% · {fmtOdds(a.odds)}</span>
        <span>{fmtOdds(b.odds)} · {100 - share}%</span>
      </span>
    </span>
  );
}

/** A match on Today: one tap target. The bar shows who is favoured; the match page takes every pick. */
export function EventCard({ event, now }: { event: EventT; now: number }) {
  // Cards count down to the scheduled start: a Bo1 winner stays open through the draft (D-026).
  const cd = countdown(event.scheduled_at, now);
  const market = event.featured;
  const mine = useMyWinnerPick(market);
  const ready = event.team_a && event.team_b;
  const body = (
    <>
      <span className="mrow-meta">
        <span className="num">
          <b>{kickoff(event.scheduled_at)}</b> · Bo{event.best_of}
        </span>
        {mine ? (
          <span className="mypick"><IconCheck width={12} height={12} aria-hidden="true" /> {mine.placed ? "Placed" : "In slip"}: {mine.code === "A" ? event.team_a?.code : event.team_b?.code}</span>
        ) : event.status === "SCHEDULED" && market?.state === "OPEN" && market.close_known !== false && Date.parse(market.close_at) - now < 3600_000 ? (
          <LockTimer at={market.close_at} label="Locks in" />
        ) : (
          <EventStatus status={event.status} closeAt={event.scheduled_at} countdownText={cd} />
        )}
      </span>
      <Matchup event={event} />
      {market && event.status === "SCHEDULED" ? <ChanceBar event={event} market={market} /> : null}
      {ready ? null : <span className="muted" style={{ fontSize: 13 }}>Prices open once the Swiss draw sets this matchup.</span>}
    </>
  );
  return ready ? (
    <Link className="mrow tap" href={`/events/${event.id}`} aria-label={`${teamName(event.team_a)} versus ${teamName(event.team_b)}, ${kickoff(event.scheduled_at)}. Open match`}>
      {body}
    </Link>
  ) : (
    <article className="mrow">{body}</article>
  );
}
