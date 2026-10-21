"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Disclaimer } from "@/components/Disclaimer";
import { EventCard } from "@/components/EventCard";
import { countdown, dayLabel, longDate, rc, venueToday } from "@/lib/format";
import { useNow, useSeason } from "@/lib/hooks";
import type { EventT, MarketT, Standing } from "@/lib/types";

export default function TodayPage() {
  const { data: season } = useSeason();
  const now = useNow();
  const days = useMemo(() => season?.match_days ?? [], [season]);
  const today = season ? venueToday(season.timezone) : null;
  const defaultDay = useMemo(() => {
    if (!days.length || !today) return null;
    return days.find((d) => d >= today) ?? days[days.length - 1];
  }, [days, today]);
  const [day, setDay] = useState<string | null>(null);
  useEffect(() => {
    if (!day && defaultDay) setDay(defaultDay);
  }, [day, defaultDay]);

  const { data: events, isLoading } = useSWR<{ events: EventT[] }>(day ? `/events?date=${day}` : null);
  const { data: futures } = useSWR<{ markets: MarketT[] }>("/markets?category=FUTURES");
  const { data: league } = useSWR<{ standings: Standing[] }>("/league/standings");

  const open = futures?.markets.filter((m) => m.state === "OPEN") ?? [];
  const board = open.filter((m) => m.kind === "swiss_record");
  const boardLock = board[0] ? countdown(board[0].close_at, now) : null;
  const champion = open.find((m) => m.kind === "tournament_winner");

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">{day ? `${season?.stages_by_day[day] ?? "Worlds"} · ${longDate(day)}` : "Worlds 2026"}</div>
          <h1 style={{ marginTop: 6 }}>{day && day === today ? "Today's slate" : "Match day"}</h1>
        </div>
      </div>

      {days.length ? (
        <div className="chips daytabs" role="tablist" aria-label="Match days">
          {days.map((d) => {
            const l = dayLabel(d);
            return (
              <button key={d} role="tab" className="chip" aria-selected={d === day} onClick={() => setDay(d)}>
                <span>{d === today ? "Today" : l.dow}</span>
                <b className="num">{l.date}</b>
              </button>
            );
          })}
        </div>
      ) : null}

      {board.length ? (
        <Link className="banner section" href="/swiss" style={{ marginTop: 14 }}>
          <span>
            <span className="t" style={{ display: "block" }}>Swiss Board is open</span>
            <span className="s">Call each team&apos;s record{boardLock ? ` · locks in ${boardLock}` : ""}</span>
          </span>
          <span className="go">Open →</span>
        </Link>
      ) : null}

      <section className="section" aria-label="Matches">
        {isLoading || !events ? (
          <>
            <div className="skeleton" />
            <div className="skeleton" />
          </>
        ) : events.events.length === 0 ? (
          <div className="empty">
            <h3>No matches on this day</h3>
            <p>Pick another match day above, or browse futures while you wait.</p>
          </div>
        ) : (
          <>
            <div className="section-head">
              <h2>Match winner</h2>
              <span className="muted" style={{ fontSize: 13 }}>Tap a side to add it</span>
            </div>
            {events.events.map((e) => <EventCard key={e.id} event={e} now={now} />)}
          </>
        )}
      </section>

      <div className="two-col section">
        {champion ? (
          <section>
            <div className="section-head">
              <h2>Worlds champion</h2>
              <Link href="/explore?tab=FUTURES">All futures</Link>
            </div>
            <div className="rows">
              {champion.outcomes.slice(0, 4).map((o) => (
                <Link className="row" key={o.id} href="/explore?tab=FUTURES">
                  <div className="title">{o.label}</div>
                  <div className="amount num">{o.odds ? `${Number(o.odds).toFixed(2)}×` : "—"}</div>
                </Link>
              ))}
            </div>
          </section>
        ) : null}
        {league?.standings.length ? (
          <section>
            <div className="section-head">
              <h2>League</h2>
              <Link href="/league">Standings</Link>
            </div>
            <div className="rows">
              {league.standings.map((s) => (
                <div className={`standing${s.rank === 1 ? " leader" : ""}`} key={s.user.id}>
                  <div className="rank num">{s.rank}</div>
                  <div>
                    <div className="who">{s.user.display_name}</div>
                    <div className="meta num">{rc(s.open_stake_rc)} RC in play</div>
                  </div>
                  <div className="bal num">{rc(s.available_rc)}</div>
                </div>
              ))}
            </div>
          </section>
        ) : null}
      </div>
      <Disclaimer />
    </>
  );
}
