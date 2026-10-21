"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef } from "react";
import useSWR from "swr";
import { kickoff, oddsSpoken } from "@/lib/format";
import { usePlaced } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import { dash, swissRounds, type SwissFinish } from "@/lib/swiss";
import type { EventT, Team } from "@/lib/types";
import { TeamMark } from "./bits";
import { eventLabel } from "./EventCard";
import { Odds } from "./Odds";

/** The whole Swiss stage on one board: a column per round, pools by record, winner picks right on each match. */
export function SwissLive({ calls }: { calls: Map<string, string> }) {
  const { data } = useSWR<{ events: EventT[] }>("/events?stage=Swiss");
  const board = useMemo(() => swissRounds(data?.events ?? []), [data]);
  const scroller = useRef<HTMLDivElement>(null);
  const current = board.rounds.find((r) => !r.done)?.index ?? board.rounds.length;

  // Open on the round being played, not on Round 1.
  useEffect(() => {
    const col = scroller.current?.querySelector<HTMLElement>(`[data-round="${current}"]`);
    if (col && scroller.current) scroller.current.scrollLeft = col.offsetLeft - scroller.current.offsetLeft;
  }, [current, data]);

  if (!data) return <div className="skeleton" style={{ marginTop: 14, height: 320 }} />;
  if (!data.events.length) {
    return (
      <div className="empty" style={{ marginTop: 14 }}>
        <h3>No Swiss matches yet</h3>
        <p>The board fills in as soon as the Swiss draw is published.</p>
      </div>
    );
  }
  return (
    <section className="section" aria-label="Swiss live board" style={{ marginTop: 14 }}>
      <p className="muted" style={{ fontSize: 13, marginBottom: 10 }}>
        Teams meet others on the same record. Pick each winner here, or open a match for its draft and in-game picks.
      </p>
      <div className="swiss-live" ref={scroller}>
        {board.rounds.map((r) => (
          <div className="sl-round" key={r.index} data-round={r.index} aria-label={`Round ${r.index}`}>
            <div className="sl-round-head">
              <span className="display">Round {r.index}</span>
              <span className={`muted${r.index === current ? " now" : ""}`}>{r.done ? "Done" : r.index === current ? "Now" : "Later"}</span>
            </div>
            {r.pools.map((p) => (
              <div className="sl-pool" key={p.record}>
                <div className={`sl-pool-head num${poolTone(p.record)}`}>{dash(p.record)}</div>
                {p.matches.map((e) => <SwissTile key={e.id} event={e} calls={calls} />)}
              </div>
            ))}
            {r.toDraw ? (
              <div className="sl-tbd">
                {r.toDraw} match{r.toDraw === 1 ? "" : "es"} drawn after Round {r.index - 1}
              </div>
            ) : null}
          </div>
        ))}
        <div className="sl-round" aria-label="Finished">
          <div className="sl-round-head">
            <span className="display">Finished</span>
          </div>
          <Finished title="Through" teams={board.advanced} tone="adv" calls={calls} />
          <Finished title="Out" teams={board.out} tone="out" calls={calls} />
        </div>
      </div>
    </section>
  );
}

// Pools one win from advancing or one loss from going out are the ones to watch.
const poolTone = (record: string) => (record[0] === "2" && record[2] !== "2" ? " adv" : record[2] === "2" && record[0] !== "2" ? " out" : record === "2-2" ? " decider" : "");

function SwissTile({ event, calls }: { event: EventT; calls: Map<string, string> }) {
  const slip = useSlip();
  const placed = usePlaced();
  const market = event.featured;
  const done = event.status === "COMPLETED";
  const label = eventLabel(event);
  const side = (code: "A" | "B", team: Team | null) => {
    const o = market?.outcomes.find((x) => x.code === code);
    const open = market?.state === "OPEN" && !!o?.odds;
    const won = event.winner === code;
    const call = team ? calls.get(team.id) : undefined;
    const inner = (
      <>
        <TeamMark team={team} />
        <span className="code">{team?.code ?? "TBD"}</span>
        {call ? <span className="call num" title="Your Swiss Board call">{dash(call)}</span> : null}
        <span className="px num">
          {done || event.status === "LIVE" ? event.score[code === "A" ? 0 : 1] : o ? <Odds value={o.odds} /> : "—"}
        </span>
      </>
    );
    if (!o || !market || (!open && !slip.isSelected(o.id))) {
      return <div className={`sl-side${won ? " won" : done ? " lost" : ""}`}>{inner}</div>;
    }
    return (
      <button
        type="button"
        className="sl-side"
        aria-pressed={slip.isSelected(o.id)}
        data-placed={placed.has(o.id) || undefined}
        onClick={() => slip.toggle(market, o, label)}
        aria-label={`${team?.code ?? "TBD"} to beat ${(code === "A" ? event.team_b : event.team_a)?.code ?? "TBD"}, ${oddsSpoken(o.odds)}`}
      >
        {inner}
      </button>
    );
  };
  return (
    <div className="sl-tile">
      {side("A", event.team_a)}
      {side("B", event.team_b)}
      <Link className="sl-foot" href={`/events/${event.id}`}>
        <span className="num">{event.status === "LIVE" ? "Live" : done ? "Final" : `${kickoff(event.scheduled_at)} · Bo${event.best_of}`}</span>
        <span>Match →</span>
      </Link>
    </div>
  );
}

function Finished({ title, teams, tone, calls }: { title: string; teams: SwissFinish[]; tone: "adv" | "out"; calls: Map<string, string> }) {
  return (
    <div className="sl-pool">
      <div className={`sl-pool-head ${tone}`}>{title}</div>
      {teams.length ? (
        teams.map(({ team, record }) => {
          const call = calls.get(team.id);
          return (
            <div className="sl-done" key={team.id}>
              <TeamMark team={team} />
              <b>{team.code}</b>
              <span className="num">{dash(record)}</span>
              {call ? <span className={`call num${call === record ? " hit" : ""}`}>{call === record ? "Called it" : `Called ${dash(call)}`}</span> : null}
            </div>
          );
        })
      ) : (
        <div className="sl-tbd">None yet</div>
      )}
    </div>
  );
}
