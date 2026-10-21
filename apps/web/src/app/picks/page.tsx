"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { PickStatus } from "@/components/bits";
import { odds as fmtOdds, rc } from "@/lib/format";
import type { Pick } from "@/lib/types";

export default function PicksPage() {
  const [tab, setTab] = useState<"open" | "settled">("open");
  const { data } = useSWR<{ picks: Pick[] }>(`/me/picks?state=${tab}`);
  const picks = data?.picks;
  const atRisk = picks?.reduce((s, p) => s + p.stake_rc, 0) ?? 0;
  const net = picks?.reduce((s, p) => s + p.return_rc - p.stake_rc, 0) ?? 0;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>My picks</h1>
          <p className="num">
            {tab === "open" ? `${rc(atRisk)} RC in play` : picks ? `${net >= 0 ? "+" : "−"}${rc(Math.abs(net))} RC net on settled picks` : " "}
          </p>
        </div>
      </div>
      <div className="segmented" role="group" aria-label="Pick status">
        <button aria-pressed={tab === "open"} onClick={() => setTab("open")}>Open</button>
        <button aria-pressed={tab === "settled"} onClick={() => setTab("settled")}>Settled</button>
      </div>
      <section className="section">
        {!picks ? (
          <div className="skeleton" />
        ) : picks.length === 0 ? (
          <div className="empty">
            <h3>{tab === "open" ? "No open picks" : "Nothing settled yet"}</h3>
            <p>{tab === "open" ? "Find a matchup and back your read." : "Settled picks show up here with their returns."}</p>
            {tab === "open" ? (
              <Link className="btn small" href="/" style={{ marginTop: 14 }}>
                See today&apos;s matches
              </Link>
            ) : null}
          </div>
        ) : (
          picks.map((p) => <PickCard key={p.id} pick={p} />)
        )}
      </section>
    </>
  );
}

function PickCard({ pick: p }: { pick: Pick }) {
  const ev = p.event;
  return (
    <article className="pick">
      <div className="pick-top">
        <div style={{ minWidth: 0 }}>
          <div className="pick-sel">{p.outcome_label}</div>
          <div className="pick-mkt">
            {p.market_title}
            {ev ? ` · ${ev.team_a?.code ?? "TBD"} vs ${ev.team_b?.code ?? "TBD"}` : ""}
          </div>
        </div>
        <PickStatus pick={p} />
      </div>
      <div className="pick-nums num">
        <div>
          Stake<b>{rc(p.stake_rc)}</b>
        </div>
        <div>
          Odds<b>{fmtOdds(p.odds)}</b>
        </div>
        <div>
          {p.status === "OPEN" ? "To return" : "Returned"}
          <b className={p.status === "WON" || p.status === "PARTIAL" ? "win" : p.status === "LOST" ? "loss" : undefined}>
            {rc(p.status === "OPEN" ? p.potential_return_rc : p.return_rc)}
          </b>
        </div>
      </div>
      {p.status === "OPEN" && p.partial_return_rc !== null ? (
        <p className="muted num" style={{ fontSize: 13, marginTop: 8 }}>Right side, wrong record returns {rc(p.partial_return_rc)} RC.</p>
      ) : null}
      {p.status === "VOID" && p.void_reason ? (
        <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>Void — {p.void_reason}. Your stake was returned.</p>
      ) : null}
      {p.market_state === "HOLD" && p.market_state_reason ? <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>{p.market_state_reason}</p> : null}
      {p.settled_revision > 1 ? <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>Corrected after a data update (revision {p.settled_revision}).</p> : null}
    </article>
  );
}
