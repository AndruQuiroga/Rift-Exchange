"use client";

import Link from "next/link";
import { useMemo } from "react";
import useSWR from "swr";
import { rc } from "@/lib/format";
import { dash, swissChance } from "@/lib/swiss";
import type { MarketT, SwissCardT } from "@/lib/types";
import { TeamMark } from "./bits";

const ORDER = ["3-0", "3-1", "3-2", "2-3", "1-3", "0-3"];

/** Your free record card: calls, locked prices and rewards. */
export function useSwissCard() {
  return useSWR<SwissCardT>("/swiss/card");
}

/** team id -> the record you called for it, to tag teams on the Swiss board. */
export function useSwissCalls(markets: MarketT[] | undefined): Map<string, string> {
  const { data } = useSwissCard();
  return useMemo(() => {
    const out = new Map<string, string>();
    for (const c of data?.calls ?? []) {
      const team = markets?.find((m) => m.id === c.market_id)?.team;
      if (team) out.set(team.id, c.record);
    }
    return out;
  }, [data, markets]);
}

/** After the card locks: each call against the team's record so far, whether it can still land, and what it paid. */
export function SwissProgress({ board }: { board: MarketT[] }) {
  const { data } = useSwissCard();
  const calls = data?.calls ?? [];
  if (!calls.length) {
    return <div className="empty" style={{ marginTop: 14 }}><h3>No record calls</h3><p>The card locked before you made any calls.</p></div>;
  }
  const rows = calls
    .map((c) => ({ c, m: board.find((x) => x.id === c.market_id), chance: swissChance(c.record, c.swiss_record) }))
    .sort((a, b) => ORDER.indexOf(a.c.record) - ORDER.indexOf(b.c.record));
  return (
    <section className="section" aria-label="Your record calls" style={{ marginTop: 14 }}>
      <div className="swiss-progress">
        {rows.map(({ c, m, chance }) => (
          <div className="sp-row" key={c.market_id}>
            <span className="sp-team">
              <TeamMark team={m?.team ?? null} />
              <b>{m?.team?.code ?? "—"}</b>
            </span>
            <span className="sp-rec num">
              <span className="muted">called</span> {dash(c.record)}
              <span className="muted"> · now</span> {dash(c.swiss_record)}
            </span>
            <span className={`sp-state ${chance.tone}`}>
              {chance.text}
              {c.status === "OPEN" ? <span className="num muted"> · up to {rc(c.exact_rc)} RC</span> : c.reward_rc ? <span className="num"> · +{rc(c.reward_rc)} RC</span> : null}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

/** One line for Today once the card locks: how many exact calls are still alive. */
export function SwissSummary() {
  const { data } = useSwissCard();
  const calls = data?.calls ?? [];
  if (!calls.length) return null;
  const alive = calls.filter((c) => swissChance(c.record, c.swiss_record).text === "Exact still possible").length;
  const won = calls.reduce((s, c) => s + c.reward_rc, 0);
  return (
    <Link className="banner quiet section" href="/swiss" style={{ marginTop: 14 }}>
      <span>
        <span className="t" style={{ display: "block" }}>Your record calls</span>
        <span className="s num">
          {alive} of {calls.length} exact calls still possible{won ? ` · +${rc(won)} RC so far` : ""}
        </span>
      </span>
      <span className="go">View →</span>
    </Link>
  );
}
