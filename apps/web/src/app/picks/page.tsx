"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { EventStatus, PickStatus } from "@/components/bits";
import { CancelPick } from "@/components/CancelPick";
import { kickoff, longDate, odds as fmtOdds, rc } from "@/lib/format";
import type { Pick } from "@/lib/types";

const signed = (n: number) => `${n >= 0 ? "+" : "−"}${rc(Math.abs(n))}`;

export default function PicksPage() {
  const [tab, setTab] = useState<"open" | "settled">("open");
  const { data } = useSWR<{ picks: Pick[] }>(`/me/picks?state=${tab}`);
  const picks = data?.picks;
  const atRisk = picks?.reduce((s, p) => s + p.stake_rc, 0) ?? 0;
  const toReturn = picks?.reduce((s, p) => s + p.potential_return_rc, 0) ?? 0;
  const net = picks?.reduce((s, p) => s + p.return_rc - p.stake_rc, 0) ?? 0;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>My picks</h1>
          <p className="num">
            {!picks ? " " : tab === "open" ? `${rc(atRisk)} RC in play · up to ${rc(toReturn)} RC back` : `${signed(net)} RC net on settled picks`}
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
          groupPicks(picks).map((g) => <MatchGroup key={g.key} group={g} open={tab === "open"} />)
        )}
      </section>
    </>
  );
}

type Group = { key: string; title: string; when: string; at: string; picks: Pick[] };

/** Picks under their match (newest match first); Swiss Board and other futures together at the end. */
function groupPicks(picks: Pick[]): Group[] {
  const groups: Group[] = [];
  for (const p of picks) {
    const ev = p.event;
    const key = ev?.id ?? "futures";
    let g = groups.find((x) => x.key === key);
    if (!g) {
      g = ev
        ? { key, title: `${ev.team_a?.code ?? "TBD"} vs ${ev.team_b?.code ?? "TBD"}`, when: `${longDate(ev.local_date)} · ${kickoff(ev.scheduled_at)}`, at: ev.scheduled_at, picks: [] }
        : { key, title: "Swiss Board & futures", when: "", at: "9999", picks: [] };
      groups.push(g);
    }
    g.picks.push(p);
  }
  return groups.sort((a, b) => (a.key === "futures" ? 1 : b.key === "futures" ? -1 : b.at.localeCompare(a.at)));
}

/** Bets on the same outcome with the same result, taken together: each top-up keeps its own odds. */
function stackPicks(picks: Pick[]): Pick[][] {
  const out = new Map<string, Pick[]>();
  for (const p of picks) {
    const key = `${p.market_id}:${p.outcome_id}:${p.status}`;
    out.set(key, [...(out.get(key) ?? []), p]);
  }
  return [...out.values()];
}

/** One match: its totals on top, then one row per outcome you backed. */
function MatchGroup({ group, open }: { group: Group; open: boolean }) {
  const ev = group.picks[0].event;
  const staked = group.picks.reduce((s, p) => s + p.stake_rc, 0);
  const back = group.picks.reduce((s, p) => s + (open ? p.potential_return_rc : p.return_rc), 0);
  const head = (
    <>
      <span className="pg-title">
        <b>{group.title}</b>
        <span className="muted">{group.when}</span>
      </span>
      <span className="pg-sum num">
        {ev ? <EventStatus status={ev.status} /> : null}
        <span>{rc(staked)} RC {open ? "in play" : "staked"}</span>
        <b className={open ? undefined : back - staked >= 0 ? "win" : "loss"}>{open ? `up to ${rc(back)}` : `${signed(back - staked)} RC`}</b>
      </span>
    </>
  );
  return (
    <div className="pick-group">
      {ev ? <Link className="pg-head" href={`/events/${ev.id}`}>{head}<span className="pg-go" aria-hidden="true">›</span></Link> : <div className="pg-head">{head}</div>}
      <div className="pg-rows">
        {stackPicks(group.picks).map((stack) => <PickRow key={stack[0].id} picks={stack} />)}
      </div>
    </div>
  );
}

/** One outcome you backed: total stake, blended odds and return, then each bet with its Cancel when there are several. */
function PickRow({ picks }: { picks: Pick[] }) {
  const p = picks[0];
  const many = picks.length > 1;
  const stake = picks.reduce((s, x) => s + x.stake_rc, 0);
  const open = p.status === "OPEN";
  const ret = picks.reduce((s, x) => s + (open ? x.potential_return_rc : x.return_rc), 0);
  const odds = many ? (picks.reduce((s, x) => s + x.potential_return_rc, 0) / stake).toFixed(2) : p.odds;
  const tone = p.status === "WON" || (p.status === "PARTIAL" && ret > stake) ? "win" : p.status === "LOST" ? "loss" : undefined;
  return (
    <article className="prow">
      <div className="prow-top">
        <div className="prow-what">
          <div className="prow-sel">{p.outcome_label}</div>
          <div className="prow-mkt">{p.market_title}{p.after_draft ? " · after draft" : ""}</div>
        </div>
        <PickStatus pick={p} />
      </div>
      <div className="prow-money num">
        <span>{rc(stake)} RC @ {fmtOdds(odds)}{many ? " avg" : ""}</span>
        <span className="prow-arrow" aria-hidden="true">→</span>
        <b className={tone}>{rc(ret)} RC</b>
        <span className="muted">{open ? "if it wins" : p.status === "CANCELLED" ? "refunded" : "returned"}</span>
        {many ? null : <CancelPick pick={p} />}
      </div>
      {many ? (
        <ul className="prow-bets num" aria-label={`${picks.length} bets on ${p.outcome_label}`}>
          {picks.map((x) => (
            <li key={x.id}>
              <span>{rc(x.stake_rc)} @ {fmtOdds(x.odds)} → {rc(open ? x.potential_return_rc : x.return_rc)}</span>
              <span className="muted">{new Date(x.accepted_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
              <CancelPick pick={x} compact />
            </li>
          ))}
        </ul>
      ) : null}
      {open && p.partial_return_rc !== null ? (
        <p className="prow-note num">Right side, wrong record returns {rc(picks.reduce((s, x) => s + (x.partial_return_rc ?? 0), 0))} RC.</p>
      ) : null}
      {p.status === "PARTIAL" ? (
        <p className="prow-note num">{p.kind === "lane_duel" ? "No winner: half your stake back." : `Right side, wrong record: ${rc(ret)} RC back.`}</p>
      ) : null}
      {p.status === "VOID" && p.void_reason ? <p className="prow-note">Void: {p.void_reason}. Your stake was returned.</p> : null}
      {p.market_state === "HOLD" && p.market_state_reason ? <p className="prow-note">{p.market_state_reason}</p> : null}
      {p.settled_revision > 1 ? <p className="prow-note">Corrected after a data update (revision {p.settled_revision}).</p> : null}
    </article>
  );
}
