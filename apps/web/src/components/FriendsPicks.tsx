"use client";

import useSWR from "swr";
import { odds as fmtOdds, rc } from "@/lib/format";
import type { EventT, Pick } from "@/lib/types";
import { PickStatus } from "./bits";

/** Friends' picks on this match, each revealed once its market locks (the same rule as League). */
export function FriendsPicks({ event }: { event: EventT }) {
  const { data } = useSWR<{ picks: Pick[] }>(`/events/${event.id}/league`, { refreshInterval: 60000 });
  const picks = data?.picks ?? [];
  if (!picks.length) return null;
  const names = [...new Set(picks.map((p) => p.user?.display_name ?? "A friend"))];
  return (
    <details className="builder" style={{ marginTop: 12 }}>
      <summary>
        <span>
          <span className="t" style={{ display: "block" }}>Friends on this match</span>
          <span className="s">{names.join(", ")} · {picks.length} locked pick{picks.length === 1 ? "" : "s"}</span>
        </span>
        <span className="chev" aria-hidden="true">›</span>
      </summary>
      <div className="body">
        {picks.map((p) => (
          <div className="friend-pick" key={p.id}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 700, fontSize: 14 }}>
                <span className="muted">{p.user?.display_name} · </span>
                {p.outcome_label}
              </div>
              <div className="muted num" style={{ fontSize: 12 }}>
                {p.market_title} · {rc(p.stake_rc)} RC @ {fmtOdds(p.odds)}
              </div>
            </div>
            <PickStatus pick={p} />
          </div>
        ))}
      </div>
    </details>
  );
}
