"use client";

import { useEffect, useRef } from "react";
import { usePlaced } from "@/lib/hooks";
import { useToast } from "@/lib/toasts";
import type { EventT, MarketT } from "@/lib/types";
import { FriendDots } from "./H2H";
import { PayoutNote } from "./Timing";

/** What a market resolved to: settled, or called and waiting to pay (D-032). Null while it is still open. */
function outcomeOf(m: MarketT): { labels: string; void: boolean; final: boolean; paid: boolean; payAt: string | null; codes: string[] } | null {
  const r = m.result ?? (m.call ? { void: m.call.void, winning_codes: m.call.winning_codes } : null);
  if (!r) return null;
  const labels = m.outcomes.filter((o) => r.winning_codes.includes(o.code)).map((o) => o.label).join(", ");
  return { labels, void: r.void, final: !!m.result || !!m.call?.final, paid: !!m.result, payAt: m.call?.pays_at ?? null, codes: r.winning_codes };
}

const forGame = (m: MarketT, game: number, bo1: boolean) =>
  m.params.game_index === game || (bo1 && m.params.game_index === undefined && m.scope === "SERIES");

/** "Results so far": every market of this game the data has already decided — the draft, firsts, baron, gold at
 * 15 — with your pick on it and friends who picked it. Fills in as the game is played. */
export function ResultsSoFar({ event, game }: { event: EventT; game: number }) {
  const placed = usePlaced();
  const rows = (event.markets ?? [])
    .filter((m) => forGame(m, game, event.best_of === 1))
    .map((m) => ({ m, out: outcomeOf(m) }))
    .filter((r): r is { m: MarketT; out: NonNullable<ReturnType<typeof outcomeOf>> } => !!r.out);
  if (!rows.length) return null;
  return (
    <section className="mp-section results" aria-label="Results so far">
      <div className="mp-head">
        <h2>Results so far</h2>
        <span className="muted">{rows.length} decided</span>
      </div>
      <div className="result-rows">
        {rows.map(({ m, out }) => {
          const mine = m.outcomes.filter((o) => placed.has(o.id));
          const verdict = !mine.length ? null : out.void ? "void" : mine.some((o) => out.codes.includes(o.code)) ? "won" : "lost";
          const winner = m.outcomes.find((o) => out.codes.includes(o.code));
          return (
            <div className={`result-row reveal${verdict ? ` ${verdict}` : ""}`} key={m.id}>
              <div style={{ minWidth: 0 }}>
                <div className="r-title">{m.title}</div>
                <div className="r-sub num">
                  {out.paid ? "Paid" : out.final ? "Result in" : "Called live"}
                  {out.paid ? null : <> · <PayoutNote payAt={out.payAt} final={out.final} /></>}
                </div>
              </div>
              <div className="r-right">
                <span className="r-val">{out.void ? "Void" : out.labels || "—"}</span>
                {verdict ? <span className={`status ${verdict}`}><span className="dot" />{verdict === "won" ? "You won" : verdict === "lost" ? "You lost" : "Void"}</span> : null}
                {winner ? <FriendDots eventId={event.id} outcomeId={winner.id} /> : null}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/**
 * A toast the moment a market is decided while you watch (first dragon, gold at 15, the draft...), saying how
 * it went for your pick. Results already known when the page opened don't toast.
 */
export function DeciderToasts({ event }: { event: EventT }) {
  const placed = usePlaced();
  const toast = useToast();
  const seen = useRef<Set<string> | null>(null);
  const lastStatus = useRef(event.status);

  // D-039: the broadcast going live starts a one-minute countdown on pre-draft picks; say so once, as it starts.
  useEffect(() => {
    const was = lastStatus.current;
    lastStatus.current = event.status;
    if (was !== "SCHEDULED" || event.status !== "LIVE") return;
    const closing = (event.markets ?? []).some((m) => m.state === "OPEN" && Date.parse(m.close_at) - Date.now() < 120_000);
    if (closing) {
      toast({ key: `countdown:${event.id}`, tone: "money", badge: "1:00", kicker: "Match is live",
              text: "Blind picks, the winner and draft calls close in a minute" });
    }
  }, [event.status, event.markets, event.id, toast]);

  useEffect(() => {
    const decided = (event.markets ?? []).map((m) => ({ m, out: outcomeOf(m) })).filter((r) => r.out);
    if (seen.current === null) {
      seen.current = new Set(decided.map((r) => r.m.id));
      return;
    }
    for (const { m, out } of decided) {
      if (seen.current.has(m.id)) continue;
      seen.current.add(m.id);
      const mine = m.outcomes.filter((o) => placed.has(o.id));
      if (!mine.length) continue; // only what you have a pick on
      const won = !!mine.length && !out!.void && mine.some((o) => out!.codes.includes(o.code));
      const staked = mine.reduce((n, o) => n + (placed.get(o.id) ?? 0), 0);
      const winner = m.outcomes.find((o) => out!.codes.includes(o.code));
      toast({
        key: `decided:${m.id}`,
        tone: !mine.length || out!.void ? "info" : won ? "good" : "rival",
        badge: won && winner?.odds ? `+${Math.round(staked * (Number(winner.odds) - 1))}` : (winner?.label ?? "—").slice(0, 4),
        kicker: m.title,
        text: out!.void ? "Void: stakes come back" : `${out!.labels}${!mine.length ? "" : won ? ". You called it." : ". Not your side."}`,
      });
    }
  }, [event.markets, placed, toast]);
  return null;
}
