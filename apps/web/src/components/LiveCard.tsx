"use client";

import useSWR from "swr";
import { rc } from "@/lib/format";
import type { EventT, LiveEvent, LiveT } from "@/lib/types";
import { PickStatus } from "./bits";

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const EVENT_LABEL: Record<LiveEvent["type"], string> = {
  first_blood: "First blood",
  first_tower: "First tower",
  dragon: "Dragon",
  baron: "Baron",
  inhibitor: "Inhibitor",
};

/** Read-only while a series is live: the game state and how each of your picks on it is doing. */
export function LiveCard({ event }: { event: EventT }) {
  const { data: live } = useSWR<LiveT>(`/events/${event.id}/live`, { refreshInterval: 15000 });
  if (!live || live.status !== "LIVE") return null;
  const code = (t: "A" | "B" | null) => (t === "A" ? event.team_a?.code : t === "B" ? event.team_b?.code : "—");
  const lead = live.gold ? live.gold[0] - live.gold[1] : 0;
  const share = live.gold ? Math.min(Math.abs(lead) / 10000, 1) * 50 : 0;

  return (
    <section className="card livecard" aria-label="Live">
      <div className="card-head">
        <h2>
          <span className="status live" style={{ marginRight: 8 }}><span className="dot" />Live</span>
          {live.game_index ? `Game ${live.game_index}` : "Between games"}
        </h2>
        <span className="sub num">{live.game_clock_s !== null ? clock(live.game_clock_s) : ""}</span>
      </div>

      {live.gold ? (
        <>
          <div className="live-nums num">
            <span>{event.team_a?.code} <b>{live.kills?.[0] ?? 0}</b></span>
            <span className="muted">kills</span>
            <span><b>{live.kills?.[1] ?? 0}</b> {event.team_b?.code}</span>
          </div>
          <div className="goldbar" aria-label={`Gold lead ${lead >= 0 ? event.team_a?.code : event.team_b?.code} ${rc(Math.abs(lead))}`}>
            <span className="mid" />
            <span className="fill" style={lead >= 0 ? { right: "50%", width: `${share}%` } : { left: "50%", width: `${share}%` }} />
          </div>
          <div className="muted num" style={{ fontSize: 12, textAlign: "center", marginTop: 4 }}>
            {lead === 0 ? "Gold even" : `${lead > 0 ? event.team_a?.code : event.team_b?.code} +${(Math.abs(lead) / 1000).toFixed(1)}k gold`}
          </div>
        </>
      ) : null}

      {live.events.length ? (
        <div className="live-events">
          {live.events.slice(-6).map((e, i) => (
            <span className="tagpill num" key={i}>
              {EVENT_LABEL[e.type]}{e.detail ? ` · ${e.detail}` : ""} · {code(e.team)} {clock(e.at_s)}
            </span>
          ))}
        </div>
      ) : null}

      {live.my_picks.length ? (
        <div style={{ marginTop: 12, borderTop: "1px solid var(--divider)", paddingTop: 10 }}>
          <div className="eyebrow">Your picks on this match</div>
          {live.my_picks.map((p) => (
            <div className="live-pick" key={p.id}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 14 }}>{p.outcome_label}</div>
                <div className="muted" style={{ fontSize: 12 }}>
                  {p.market_title}
                  {p.live?.needed !== undefined && p.live.needed > 0 ? ` · ${p.live.current} so far, ${p.live.needed} more needed` : ""}
                  {p.live?.needed === 0 ? ` · ${p.live.current} so far, over the line` : ""}
                  {p.live?.score ? ` · ${p.live.score[0]}–${p.live.score[1]}` : ""}
                </div>
              </div>
              <PickStatus pick={p} />
            </div>
          ))}
        </div>
      ) : null}
      <p className="fineprint" style={{ textAlign: "left" }}>Nothing can be placed on a game in progress.</p>
    </section>
  );
}
