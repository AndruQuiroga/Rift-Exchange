"use client";

import Link from "next/link";
import type { EventT, MarketT, OutcomeT, Team } from "@/lib/types";
import { countdown, kickoff, odds as fmtOdds, oddsSpoken } from "@/lib/format";
import { useSlip } from "@/lib/slip";
import { teamName } from "@/lib/teams";
import { EventStatus, TeamMark } from "./bits";

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

/** One side of a match winner market: the team and its price in a single tap target. */
export function SideButton({ market, outcome, team, label, right }: { market: MarketT; outcome: OutcomeT; team: Team | null; label: string; right?: boolean }) {
  const slip = useSlip();
  const selected = slip.isSelected(outcome.id);
  const won = market.result && !market.result.void && market.result.winning_codes.includes(outcome.code);
  const open = market.state === "OPEN" && outcome.odds !== null;
  return (
    <button
      type="button"
      className={`side${right ? " right" : ""}${won ? " won" : ""}`}
      aria-pressed={selected}
      disabled={!open && !selected}
      onClick={() => slip.toggle(market, outcome, label)}
      aria-label={`${teamName(team)} to win, ${oddsSpoken(outcome.odds)}${selected ? ", in slip" : ""}`}
    >
      <span className="who">
        <TeamMark team={team} />
        <span style={{ minWidth: 0 }}>
          <span className="code">{team?.code ?? "TBD"}</span>
          <span className="nm">{teamName(team)}</span>
        </span>
      </span>
      <span className="px num">{won ? "Won" : fmtOdds(outcome.odds)}</span>
    </button>
  );
}

/** Only what can be tapped now, plus one line saying when the in-game picks open. */
function matchTags(event: EventT): { now: string[]; later: string | null } {
  const cats = event.categories ?? [];
  const pregame = event.featured?.state === "OPEN";
  const between = event.status === "LIVE" && cats.includes("WINNER"); // the next game's winner and draft are open
  const now: string[] = [];
  if (pregame && event.best_of > 1) now.push("Score");
  if (pregame || between) now.push("Draft");
  if (cats.includes("OBJECTIVES")) now.push("Objectives");
  if (event.early_open) now.push("Duels", "Kill line");
  const later = !event.early_open && (pregame || between) ? "Duels at game start" : null;
  return { now, later };
}

export function EventCard({ event, now }: { event: EventT; now: number }) {
  const cd = event.close_at ? countdown(event.close_at, now) : null;
  const market = event.featured;
  const a = market?.outcomes.find((o) => o.code === "A");
  const b = market?.outcomes.find((o) => o.code === "B");
  const ready = event.team_a && event.team_b;
  const tags = matchTags(event);
  return (
    <article className="mrow" aria-label={`${teamName(event.team_a)} versus ${teamName(event.team_b)}`}>
      <div className="mrow-meta">
        <span className="num">
          <b>{kickoff(event.scheduled_at)}</b> · Bo{event.best_of}
          {event.status === "LIVE" || event.status === "COMPLETED" ? ` · ${event.score[0]}–${event.score[1]}` : ""}
        </span>
        <EventStatus status={event.status} closeAt={event.close_at} countdownText={cd} />
      </div>
      {market && a && b ? (
        <div className="mrow-sides">
          <SideButton market={market} outcome={a} team={event.team_a} label={eventLabel(event)} />
          <SideButton market={market} outcome={b} team={event.team_b} label={eventLabel(event)} right />
        </div>
      ) : (
        <Matchup event={event} />
      )}
      {ready ? (
        <Link className="mrow-foot" href={`/events/${event.id}`}>
          <span className="tags">
            {tags.now.map((t) => (
              <span className="tagpill" key={t}>{t}</span>
            ))}
            {tags.later ? <span className="tagpill later">{tags.later}</span> : null}
          </span>
          <span className="link">Match →</span>
        </Link>
      ) : (
        <p className="muted" style={{ marginTop: 10, fontSize: 13 }}>Prices open once the Swiss draw sets this matchup.</p>
      )}
    </article>
  );
}
