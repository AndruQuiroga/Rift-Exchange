"use client";

import useSWR from "swr";
import { PickStatus } from "@/components/bits";
import { rc } from "@/lib/format";
import type { Pick, Standing } from "@/lib/types";

export default function LeaguePage() {
  const { data: league } = useSWR<{ standings: Standing[] }>("/league/standings");
  const { data: activity } = useSWR<{ activity: Pick[] }>("/league/activity");
  const provisional = league?.standings.some((s) => s.provisional);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>League</h1>
          <p>Ranked by available credits{provisional ? " · provisional while picks are open" : ""}.</p>
        </div>
      </div>
      <div className="rows">
        {!league ? (
          <div className="skeleton" style={{ border: 0 }} />
        ) : (
          league.standings.map((s) => (
            <div className={`standing${s.rank === 1 ? " leader" : ""}`} key={s.user.id}>
              <div className="rank num">{s.rank}</div>
              <div>
                <div className="who">{s.user.display_name}</div>
                <div className="meta num">
                  {rc(s.open_stake_rc)} in play · {s.won}W–{s.lost}L ·{" "}
                  <span className={s.realized_net_rc >= 0 ? "win" : "loss"}>
                    {s.realized_net_rc >= 0 ? "+" : "−"}
                    {rc(Math.abs(s.realized_net_rc))} net
                  </span>
                </div>
              </div>
              <div className="bal num">{rc(s.available_rc)}</div>
            </div>
          ))
        )}
      </div>

      <section className="section">
        <div className="section-head">
          <h2>Locked-in reads</h2>
        </div>
        <p className="muted" style={{ fontSize: 14, marginBottom: 12 }}>Friends&apos; picks appear here once each market locks.</p>
        {activity?.activity.length ? (
          activity.activity.map((p) => (
            <article className="pick" key={p.id}>
              <div className="pick-top">
                <div style={{ minWidth: 0 }}>
                  <div className="eyebrow" style={{ marginBottom: 4 }}>{p.user?.display_name}</div>
                  <div className="pick-sel">{p.outcome_label}</div>
                  <div className="pick-mkt">
                    {p.market_title}
                    {p.event ? ` · ${p.event.team_a?.code} vs ${p.event.team_b?.code}` : ""} · {rc(p.stake_rc)} RC @ {Number(p.odds).toFixed(2)}×
                  </div>
                </div>
                <PickStatus pick={p} />
              </div>
            </article>
          ))
        ) : (
          <div className="empty">
            <h3>Nothing revealed yet</h3>
            <p>Picks stay private until their market locks.</p>
          </div>
        )}
      </section>
    </>
  );
}
