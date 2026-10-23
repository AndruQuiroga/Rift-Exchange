"use client";

import Link from "next/link";
import useSWR from "swr";
import { useFriendsOnMatch } from "@/lib/friends";
import { odds as fmtOdds, rc } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import type { EventT, Pick } from "@/lib/types";
import { clockText } from "./Timing";

/** What a pick of yours brings back once everything known is counted (settled or already decided). */
function backOf(p: Pick): { back: number; result: string | null } {
  if (p.status !== "OPEN") return { back: p.return_rc, result: p.status };
  const r = p.call?.result ?? null;
  if (r === "WON") return { back: p.potential_return_rc, result: r };
  if (r === "VOID") return { back: p.stake_rc, result: r };
  if (r === "PARTIAL") return { back: Math.round(p.stake_rc / 2), result: r };
  return { back: 0, result: r };
}

/** After the match: what you staked, what comes back, when it lands, and how everyone did. */
export function PostGame({ event }: { event: EventT }) {
  const now = useNow(1000);
  const { data } = useSWR<{ picks: Pick[] }>("/me/picks");
  const { table } = useFriendsOnMatch(event.id);
  const { data: day } = useSWR<{ events: EventT[] }>(`/events?date=${event.local_date}`);
  const mine = (data?.picks ?? []).filter((p) => p.event?.id === event.id);
  const next = (day?.events ?? []).find((e) => e.status === "SCHEDULED" && Date.parse(e.scheduled_at) > Date.parse(event.scheduled_at));
  const winner = event.winner === "A" ? event.team_a : event.winner === "B" ? event.team_b : null;
  const loser = event.winner === "A" ? event.team_b : event.winner === "B" ? event.team_a : null;

  let staked = 0, back = 0, won = 0, lost = 0, half = 0, open = 0;
  let paysAt = 0;
  for (const p of mine) {
    staked += p.stake_rc;
    const b = backOf(p);
    back += b.back;
    if (b.result === "WON") won++;
    else if (b.result === "LOST") lost++;
    else if (b.result === "PARTIAL") half++;
    if (p.status === "OPEN") {
      open++;
      if (p.call?.pays_at) paysAt = Math.max(paysAt, Date.parse(p.call.pays_at));
    }
  }
  const net = back - staked;
  const landing = open ? (paysAt > now ? clockText(paysAt - now) : "soon") : "landed";

  return (
    <section className="postgame" aria-label="Your match">
      <div className="pg-hero">
        <div className="pg-score">
          <span className="pg-k">FINAL · BO{event.best_of}</span>
          <span className="pg-line"><b>{winner?.code ?? event.team_a?.code} {event.score[event.winner === "B" ? 1 : 0]}</b> <span className="muted">beat</span> {event.score[event.winner === "B" ? 0 : 1]} {loser?.code ?? event.team_b?.code}</span>
        </div>
        {mine.length ? (
          <>
            <div className="pg-net">
              <span className="muted">Your match</span>
              <span className={`pg-big num ${net >= 0 ? "up" : "down"}`}>{net >= 0 ? "+" : "−"}{rc(Math.abs(net))} RC</span>
              <span className="muted">{won} won · {lost} lost{half ? ` · ${half} half back` : ""}{open && won + lost + half < mine.length ? ` · ${mine.length - won - lost - half} waiting` : ""}</span>
            </div>
            <div className="pg-stats">
              <div><b className="num">{rc(staked)}</b><span>staked</span></div>
              <div><b className="num">{rc(back)}</b><span>{open ? "coming back" : "came back"}</span></div>
              <div><b className={`num${open ? " warn" : ""}`}>{landing}</b><span>{open ? "until it lands" : "credits"}</span></div>
            </div>
          </>
        ) : (
          <p className="muted" style={{ textAlign: "center", padding: "14px 0", margin: 0 }}>You didn&apos;t play this one.</p>
        )}
      </div>

      {table && table.length > 1 ? (
        <div className="pg-table">
          <h3 className="rv-sub">Match table</h3>
          {table.map((r) => (
            <div className={`pg-row${r.you ? " you" : ""}`} key={r.user.handle}>
              <span className="mt-rank num">{r.rank}</span>
              <span style={{ minWidth: 0, flex: 1 }}><b>{r.you ? "You" : r.user.display_name}</b><span className="muted"> · {r.won}W {r.lost}L{r.partial ? ` ${r.partial}½` : ""} · {rc(r.staked)} staked</span></span>
              <span className={`num ${r.net >= 0 ? "win" : "loss"}`} style={{ fontWeight: 800 }}>{r.net >= 0 ? "+" : "−"}{rc(Math.abs(r.net))}</span>
            </div>
          ))}
        </div>
      ) : null}

      {mine.length ? (
        <div className="pg-picks">
          <h3 className="rv-sub">Your picks</h3>
          {mine.map((p) => {
            const b = backOf(p);
            const tone = b.result === "WON" ? "won" : b.result === "LOST" ? "lost" : b.result === "PARTIAL" ? "half" : "";
            const diff = b.result ? b.back - p.stake_rc : null;
            return (
              <div className={`pg-pick ${tone} reveal`} key={p.id}>
                <span style={{ minWidth: 0 }}><b>{p.outcome_label}</b><span className="muted" style={{ display: "block", fontSize: 12 }}>{p.market_title} · {rc(p.stake_rc)} @ {fmtOdds(p.odds)}</span></span>
                <span className="num pg-diff">{diff === null ? (p.call?.pending_refund ? "ban check" : "waiting") : `${diff >= 0 ? "+" : "−"}${rc(Math.abs(diff))}`}</span>
              </div>
            );
          })}
        </div>
      ) : null}

      {next ? (
        <Link className="pg-next" href={`/events/${next.id}`}>
          <span>Next up: {next.team_a?.code ?? "TBD"} vs {next.team_b?.code ?? "TBD"}</span>
          <span>picks open →</span>
        </Link>
      ) : null}
    </section>
  );
}
