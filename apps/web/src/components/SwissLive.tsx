"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef } from "react";
import useSWR from "swr";
import { kickoff, oddsSpoken } from "@/lib/format";
import { usePlaced } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import { dash, swissBoard, SWISS_COLUMNS, type SwissCell } from "@/lib/swiss";
import type { EventT, Team } from "@/lib/types";
import { TeamMark } from "./bits";
import { eventLabel } from "./EventCard";
import { Odds } from "./Odds";

/**
 * The whole Swiss stage laid out like the official board: every match slot from Round 1 to the final
 * records, TBD until drawn. Tap a team to pick the winner; tap the match for its draft and in-game picks.
 */
export function SwissLive({ calls, day }: { calls: Map<string, string>; day?: string | null }) {
  const { data } = useSWR<{ events: EventT[] }>("/events?stage=Swiss");
  const board = useMemo(() => swissBoard(data?.events ?? []), [data]);
  const scroller = useRef<HTMLDivElement>(null);
  const current = board.current;

  // Open on the round being played, not on Round 1.
  useEffect(() => {
    const col = scroller.current?.querySelector<HTMLElement>(`[data-col="${current}"]`);
    if (col && scroller.current) scroller.current.scrollLeft = col.offsetLeft - scroller.current.offsetLeft;
  }, [current, data]);

  if (!data) return <div className="skeleton" style={{ height: 420 }} />;
  return (
    <div className="swiss-board" ref={scroller} role="group" aria-label="Swiss stage board">
      {SWISS_COLUMNS.map((col, i) => (
        <div className="sb-col" key={col.title} data-col={i}>
          <div className="sb-col-head">
            <span className="display">{col.title}</span>
            {i === current ? <span className="now">Now</span> : null}
          </div>
          <div className="sb-cells">
            {col.cells.map((cell) =>
              cell.kind === "pool" ? (
                <Pool key={cell.record} cell={cell} matches={board.pools.get(cell.record) ?? []} calls={calls} day={day} />
              ) : (
                <Finish key={cell.record} cell={cell} teams={board.finished.get(cell.record) ?? []} calls={calls} />
              ),
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// Advancement and elimination matches (a team on two wins or two losses) are best-of-three.
const decisive = (record: string) => record.includes("2");

function Pool({ cell, matches, calls, day }: { cell: SwissCell; matches: EventT[]; calls: Map<string, string>; day?: string | null }) {
  const empty = Math.max(cell.slots - matches.length, 0);
  return (
    <section className="sb-pool" aria-label={`${dash(cell.record)} pool`}>
      <div className="sb-pool-head">
        <span className="num">{dash(cell.record)}</span>
        <span className="muted">{decisive(cell.record) ? "Bo3" : "Bo1"}</span>
      </div>
      {matches.map((e) => <Tile key={e.id} event={e} calls={calls} today={!!day && e.local_date === day} />)}
      {Array.from({ length: empty }, (_, i) => (
        <div className="sb-tile tbd" key={`tbd-${i}`} aria-label="Match to be drawn">
          <div className="sb-side"><span className="mark" aria-hidden="true" /><span className="code">TBD</span></div>
          <div className="sb-side"><span className="mark" aria-hidden="true" /><span className="code">TBD</span></div>
        </div>
      ))}
    </section>
  );
}

function Finish({ cell, teams, calls }: { cell: SwissCell; teams: Team[]; calls: Map<string, string> }) {
  const adv = cell.record.startsWith("3");
  return (
    <section className={`sb-finish ${adv ? "adv" : "out"}`} aria-label={`Finished ${dash(cell.record)}`}>
      <div className="sb-pool-head">
        <span className="num">{dash(cell.record)}</span>
        <span>{adv ? "Through" : "Out"}</span>
      </div>
      {Array.from({ length: cell.slots }, (_, i) => {
        const t = teams[i];
        const call = t ? calls.get(t.id) : undefined;
        return (
          <div className={`sb-side${t ? "" : " tbd"}`} key={t?.id ?? `tbd-${i}`}>
            <TeamMark team={t ?? null} />
            <span className="code">{t?.code ?? "TBD"}</span>
            {call ? <span className={`call num${call === cell.record ? " hit" : ""}`}>{call === cell.record ? "Called" : dash(call)}</span> : null}
          </div>
        );
      })}
    </section>
  );
}

function Tile({ event, calls, today }: { event: EventT; calls: Map<string, string>; today: boolean }) {
  const slip = useSlip();
  const placed = usePlaced();
  const market = event.featured;
  const done = event.status === "COMPLETED";
  const label = eventLabel(event);
  const side = (code: "A" | "B", team: Team | null) => {
    const o = market?.outcomes.find((x) => x.code === code);
    const open = market?.state === "OPEN" && !!o?.odds;
    const call = team ? calls.get(team.id) : undefined;
    const inner = (
      <>
        <TeamMark team={team} />
        <span className="code">{team?.code ?? "TBD"}</span>
        {call ? <span className="call num" title="Your record call">{dash(call)}</span> : null}
        <span className="px num">
          {done || event.status === "LIVE" ? event.score[code === "A" ? 0 : 1] : o ? <Odds value={o.odds} /> : null}
        </span>
      </>
    );
    if (!o || !market || (!open && !slip.isSelected(o.id))) {
      return <div className={`sb-side${event.winner === code ? " won" : done ? " lost" : ""}`}>{inner}</div>;
    }
    return (
      <button
        type="button"
        className="sb-side"
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
    <div className={`sb-tile${today ? " today" : ""}${event.status === "LIVE" ? " live" : ""}`}>
      {side("A", event.team_a)}
      {side("B", event.team_b)}
      <Link className="sb-foot" href={`/events/${event.id}`}>
        <span className="num">{event.status === "LIVE" ? "Live" : done ? "Final" : kickoff(event.scheduled_at)}</span>
        <span>Picks →</span>
      </Link>
    </div>
  );
}
