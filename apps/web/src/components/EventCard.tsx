"use client";

import Link from "next/link";
import type { EventT } from "@/lib/types";
import { countdown, kickoff } from "@/lib/format";
import { EventStatus, MarketBlock, TeamMark } from "./bits";
import { IconArrow } from "./icons";

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
          <div className="team-full">{event.team_a?.name ?? "To be drawn"}</div>
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
          <div className="team-full">{event.team_b?.name ?? "To be drawn"}</div>
        </div>
      </div>
    </div>
  );
}

export function EventCard({ event, now }: { event: EventT; now: number }) {
  const more = (event.market_count ?? 0) - (event.featured ? 1 : 0);
  const cd = event.close_at ? countdown(event.close_at, now) : null;
  return (
    <article className="event" aria-label={`${event.team_a?.name ?? "TBD"} versus ${event.team_b?.name ?? "TBD"}`}>
      <div className="event-meta">
        <span>
          <span className="fmt">
            {event.stage} · Bo{event.best_of}
          </span>
          <span className="num"> · {kickoff(event.scheduled_at)}</span>
        </span>
        <EventStatus status={event.status} closeAt={event.close_at} countdownText={cd} />
      </div>
      <div className="event-body">
        <Matchup event={event} />
        {event.featured ? (
          <div style={{ marginTop: 12 }}>
            <MarketBlock market={event.featured} eventLabel={eventLabel(event)} compact />
          </div>
        ) : !event.team_a || !event.team_b ? (
          <p className="muted" style={{ marginTop: 12, fontSize: 14 }}>
            Markets open once the Swiss draw sets this matchup.
          </p>
        ) : null}
        {event.team_a && event.team_b ? (
          <div className="event-foot">
            <Link className="link" href={`/events/${event.id}`}>
              {more > 0 ? `${more} more market${more === 1 ? "" : "s"} · rules` : "Match details & rules"}{" "}
              <IconArrow width={14} height={14} style={{ verticalAlign: "-2px" }} />
            </Link>
          </div>
        ) : null}
      </div>
    </article>
  );
}
