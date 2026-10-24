"use client";

import { useState } from "react";
import useSWR from "swr";
import { PickStatus } from "@/components/bits";
import { odds as fmtOdds, rc } from "@/lib/format";
import { useMe } from "@/lib/hooks";
import type { Pick, Standing } from "@/lib/types";

const signed = (n: number) => `${n >= 0 ? "+" : "−"}${rc(Math.abs(n))}`;
const record = (w: number, l: number) => `${w}W–${l}L`;

export default function LeaguePage() {
  const { data: league } = useSWR<{ standings: Standing[] }>("/league/standings");
  const { data: activity } = useSWR<{ activity: Pick[] }>("/league/activity");
  const { data: me } = useMe();
  const [view, setView] = useState<"today" | "season">("today");
  const provisional = league?.standings.some((s) => s.provisional);
  // Today: by today's net (then bankroll). Season: by bankroll, available plus what is in play.
  const rows = [...(league?.standings ?? [])].sort((a, b) =>
    view === "today" ? b.today_net_rc - a.today_net_rc || b.bankroll_rc - a.bankroll_rc : b.bankroll_rc - a.bankroll_rc);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>League</h1>
          <p>
            {view === "today" ? "Today's net and record, settled picks only" : "Ranked by bankroll: available plus in play"}
            {provisional ? " · moves as open picks settle" : ""}.
          </p>
        </div>
      </div>
      <div className="segmented" role="group" aria-label="Standings">
        <button aria-pressed={view === "today"} onClick={() => setView("today")}>Today</button>
        <button aria-pressed={view === "season"} onClick={() => setView("season")}>All time</button>
      </div>
      <div className="rows" style={{ marginTop: 12 }}>
        {!league ? (
          <div className="skeleton" style={{ border: 0 }} />
        ) : (
          rows.map((s) => {
            const rank = view === "today" ? s.today_rank : s.rank;
            const you = s.user.handle === me?.user.handle;
            return (
              <div className={`standing${rank === 1 ? " leader" : ""}${you ? " you" : ""}`} key={s.user.id}>
                <div className="rank num">{rank}</div>
                <div style={{ minWidth: 0 }}>
                  <div className="who">{s.user.display_name}{you ? <span className="you-tag">You</span> : null}</div>
                  <div className="meta num">
                    {view === "today" ? (
                      <>{rc(s.open_stake_rc)} in play · season {record(s.won, s.lost)}{" "}
                        <span className={s.realized_net_rc >= 0 ? "win" : "loss"}>{signed(s.realized_net_rc)}</span></>
                    ) : (
                      <>{rc(s.available_rc)} available · {rc(s.open_stake_rc)} in play</>
                    )}
                  </div>
                </div>
                <div className="bal num">
                  {view === "today" ? (
                    <span className={s.today_net_rc > 0 ? "win" : s.today_net_rc < 0 ? "loss" : undefined}>{signed(s.today_net_rc)}</span>
                  ) : (
                    rc(s.bankroll_rc)
                  )}
                  <small>
                    {view === "today" ? `${record(s.won_today, s.lost_today)} today`
                      : <>{record(s.won, s.lost)} · <span className={s.realized_net_rc >= 0 ? "win" : "loss"}>{signed(s.realized_net_rc)} net</span></>}
                  </small>
                </div>
              </div>
            );
          })
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
                    {p.event ? ` · ${p.event.team_a?.code} vs ${p.event.team_b?.code}` : ""} · {rc(p.stake_rc)} RC @ {fmtOdds(p.odds)}
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
