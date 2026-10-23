"use client";

import { initials, useFriendsOnMatch } from "@/lib/friends";
import { odds as fmtOdds, rc } from "@/lib/format";
import { usePlaced } from "@/lib/hooks";
import type { EventT, Pick } from "@/lib/types";
import { PickStatus } from "./bits";
import { LockTimer } from "./Timing";

/**
 * Friends on this match. Before a market locks only a count shows (A-010), with when it reveals; once it locks,
 * each friend's picks, and whether they are with you or against you on the same market.
 */
export function FriendsPicks({ event }: { event: EventT }) {
  const { picks, pending } = useFriendsOnMatch(event.id);
  const placed = usePlaced();
  if (!picks.length && !pending.length) return null;

  const mineByMarket = new Map<string, Set<string>>();
  for (const m of event.markets ?? []) {
    const held = m.outcomes.filter((o) => placed.has(o.id)).map((o) => o.id);
    if (held.length) mineByMarket.set(m.id, new Set(held));
  }
  const stance = (p: Pick) => {
    const mine = mineByMarket.get(p.market_id);
    return !mine ? null : mine.has(p.outcome_id) ? "with" : "against";
  };
  const byFriend = new Map<string, Pick[]>();
  for (const p of picks) {
    const name = p.user?.display_name ?? "A friend";
    byFriend.set(name, [...(byFriend.get(name) ?? []), p]);
  }

  return (
    <section className="mp-section friends" aria-label="Friends on this match">
      <div className="mp-head">
        <h2>Friends on this match</h2>
        <span className="muted">{byFriend.size + pending.filter((r) => !byFriend.has(r.user.display_name)).length} playing</span>
      </div>

      {pending.length ? (
        <div className="friend-pending">
          {pending.map((r) => (
            <div className="fp-row" key={r.user.handle}>
              <span className="fdot lg">{initials(r.user.display_name)}</span>
              <span style={{ minWidth: 0, flex: 1 }}>
                <b>{r.user.display_name}</b>
                <span className="muted"> has {r.picks} hidden pick{r.picks === 1 ? "" : "s"}</span>
              </span>
              <LockTimer at={r.reveals_at} label="Reveals in" />
            </div>
          ))}
        </div>
      ) : null}

      {[...byFriend.entries()].map(([name, list]) => {
        const staked = list.reduce((n, p) => n + p.stake_rc, 0);
        const withYou = list.filter((p) => stance(p) === "with").length;
        const against = list.filter((p) => stance(p) === "against").length;
        return (
          <details className="builder friend-group" key={name} open={byFriend.size === 1}>
            <summary>
              <span className="fdot lg">{initials(name)}</span>
              <span style={{ minWidth: 0, flex: 1 }}>
                <span className="t" style={{ display: "block" }}>{name}</span>
                <span className="s num">
                  {list.length} pick{list.length === 1 ? "" : "s"} · {rc(staked)} RC
                  {withYou ? <> · <span className="win">{withYou} with you</span></> : null}
                  {against ? <> · <span className="loss">{against} against you</span></> : null}
                </span>
              </span>
              <span className="chev" aria-hidden="true">›</span>
            </summary>
            <div className="body">
              {list.map((p) => {
                const s = stance(p);
                return (
                  <div className={`friend-pick${s ? ` ${s}` : ""}`} key={p.id}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 700, fontSize: 14 }}>
                        {p.outcome_label}
                        {s ? <span className={`stance ${s}`}>{s === "with" ? "With you" : "Against you"}</span> : null}
                      </div>
                      <div className="muted num" style={{ fontSize: 12 }}>
                        {p.market_title} · {rc(p.stake_rc)} RC @ {fmtOdds(p.odds)}
                      </div>
                    </div>
                    <PickStatus pick={p} />
                  </div>
                );
              })}
            </div>
          </details>
        );
      })}
    </section>
  );
}
