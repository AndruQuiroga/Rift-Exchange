"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { kickoff } from "@/lib/format";
import { dash, swissBoard, SWISS_COLUMNS, type SwissCell } from "@/lib/swiss";
import type { EventT, Team } from "@/lib/types";
import { TeamMark } from "./bits";
import { ChanceBar, useMyWinnerPick } from "./EventCard";
import { IconCheck } from "./icons";

/**
 * The whole Swiss stage laid out like the official board: every match slot from Round 1 to the final
 * records, TBD until drawn. Tap a team to pick the winner; tap the match for its draft and in-game picks.
 */
export function SwissLive({ calls, day }: { calls: Map<string, string>; day?: string | null }) {
  const { data } = useSWR<{ events: EventT[] }>("/events?stage=Swiss");
  const board = useMemo(() => swissBoard(data?.events ?? []), [data]);
  const scroller = useRef<HTMLDivElement>(null);
  const current = board.current;
  const [active, setActive] = useState(current);
  // When every round fits (wide desktop), there is nothing to page through.
  const [fits, setFits] = useState(false);

  const columnAt = (i: number) => scroller.current?.querySelector<HTMLElement>(`[data-col="${i}"]`) ?? null;
  // Centre a round: on phones it becomes the active column with its neighbours peeking in.
  const goTo = useCallback((i: number, smooth = true) => {
    const el = scroller.current;
    const target = Math.max(0, Math.min(SWISS_COLUMNS.length - 1, i));
    const col = columnAt(target);
    if (!el || !col) return;
    setActive(target); // the tab follows the tap straight away, not after the scroll settles
    el.scrollTo({ left: col.offsetLeft - el.offsetLeft - (el.clientWidth - col.offsetWidth) / 2, behavior: smooth ? "smooth" : "auto" });
  }, []);

  // Open on the round being played, not on Round 1.
  useEffect(() => {
    goTo(current, false);
    setActive(current);
  }, [current, data, goTo]);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => setFits(el.scrollWidth <= el.clientWidth + 1);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [data]);

  // The active round is whichever column sits nearest the middle after a swipe.
  function onScroll() {
    const el = scroller.current;
    if (!el) return;
    const mid = el.scrollLeft + el.clientWidth / 2;
    let best = 0;
    let dist = Infinity;
    SWISS_COLUMNS.forEach((_, i) => {
      const col = columnAt(i);
      if (!col) return;
      const d = Math.abs(col.offsetLeft - el.offsetLeft + col.offsetWidth / 2 - mid);
      if (d < dist) [best, dist] = [i, d];
    });
    setActive(best);
  }

  if (!data) return <div className="skeleton" style={{ height: 420 }} />;
  return (
    <div>
      {fits ? null : (
        <div className="sb-nav" role="group" aria-label="Rounds">
          <button type="button" className="icon-btn" aria-label="Previous round" disabled={active === 0} onClick={() => goTo(active - 1)}>
            ‹
          </button>
          <div className="sb-tabs">
            {SWISS_COLUMNS.map((col, i) => (
              <button key={col.title} type="button" aria-current={i === active ? "step" : undefined} onClick={() => goTo(i)}>
                {col.title.replace("Round ", "R")}
                {i === current ? <span className="dot" aria-label="now" /> : null}
              </button>
            ))}
          </div>
          <button type="button" className="icon-btn" aria-label="Next round" disabled={active === SWISS_COLUMNS.length - 1} onClick={() => goTo(active + 1)}>
            ›
          </button>
        </div>
      )}
    <div className="swiss-board" ref={scroller} onScroll={onScroll} role="group" aria-label="Swiss stage board">
      {SWISS_COLUMNS.map((col, i) => (
        <div className={`sb-col${i === active && !fits ? " active" : ""}`} key={col.title} data-col={i}>
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
  const mine = useMyWinnerPick(event.featured);
  const done = event.status === "COMPLETED";
  const scored = done || event.status === "LIVE";
  const side = (code: "A" | "B", team: Team | null) => {
    const call = team ? calls.get(team.id) : undefined;
    const picked = mine?.code === code;
    return (
      <span className={`sb-side${event.winner === code ? " won" : done ? " lost" : ""}`}>
        <TeamMark team={team} />
        <span className="code">{team?.code ?? "TBD"}</span>
        {picked ? <IconCheck className="picked" width={13} height={13} aria-label={mine?.placed ? "your placed pick" : "in your slip"} /> : null}
        {call ? <span className="call num" title="Your record call">{dash(call)}</span> : null}
        {scored ? <span className="px num">{event.score[code === "A" ? 0 : 1]}</span> : null}
      </span>
    );
  };
  return (
    <Link
      className={`sb-tile${today ? " today" : ""}${event.status === "LIVE" ? " live" : ""}`}
      href={`/events/${event.id}`}
      aria-label={`${event.team_a?.code ?? "TBD"} versus ${event.team_b?.code ?? "TBD"}${mine ? `, your pick ${mine.code === "A" ? event.team_a?.code : event.team_b?.code}` : ""}. Open match`}
    >
      {side("A", event.team_a)}
      {side("B", event.team_b)}
      {!scored && event.featured ? <ChanceBar event={event} market={event.featured} compact /> : null}
      <span className="sb-foot">
        <span className="num">{event.status === "LIVE" ? "Live" : done ? "Final" : kickoff(event.scheduled_at)}</span>
        <span>Open →</span>
      </span>
    </Link>
  );
}
