"use client";

import Link from "next/link";
import useSWR from "swr";
import { rc } from "@/lib/format";
import { dash, swissChance } from "@/lib/swiss";
import type { MarketT, Pick } from "@/lib/types";
import { TeamMark } from "./bits";

const ORDER = ["3-0", "3-1", "3-2", "2-3", "1-3", "0-3"];

/** Swiss Board picks, every state: open and settled. */
export function useSwissPicks() {
  const { data } = useSWR<{ picks: Pick[] }>("/me/picks");
  return (data?.picks ?? []).filter((p) => p.swiss_record != null);
}

/** After the board locks: each call against the team's record so far, and whether it can still land. */
export function SwissProgress({ board }: { board: MarketT[] }) {
  const picks = useSwissPicks();
  if (!picks.length) {
    return <div className="empty" style={{ marginTop: 14 }}><h3>No Swiss Board picks</h3><p>The board locked before you placed any teams.</p></div>;
  }
  const rows = picks
    .map((p) => {
      const m = board.find((x) => x.id === p.market_id);
      const called = m?.outcomes.find((o) => o.id === p.outcome_id)?.code ?? p.outcome_label.replace("–", "-");
      return { p, m, called, chance: swissChance(called, p.swiss_record ?? "0-0") };
    })
    .sort((a, b) => ORDER.indexOf(a.called) - ORDER.indexOf(b.called));
  return (
    <section className="section" aria-label="Your Swiss Board" style={{ marginTop: 14 }}>
      <div className="swiss-progress">
        {rows.map(({ p, m, called, chance }) => (
          <div className="sp-row" key={p.id}>
            <span className="sp-team">
              <TeamMark team={m?.team ?? null} />
              <b>{m?.team?.code ?? p.market_title}</b>
            </span>
            <span className="sp-rec num">
              <span className="muted">called</span> {dash(called)}
              <span className="muted"> · now</span> {dash(p.swiss_record ?? "0-0")}
            </span>
            <span className={`sp-state ${chance.tone}`}>
              {chance.text}
              {p.status !== "OPEN" && p.return_rc ? <span className="num"> · {rc(p.return_rc)} RC</span> : null}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

/** One line for Today once the board is locked: the live board, and how many exact calls are still alive. */
export function SwissSummary() {
  const picks = useSwissPicks();
  const alive = picks.filter((p) => {
    const called = p.outcome_label.replace("–", "-");
    return swissChance(called, p.swiss_record ?? "0-0").text === "Exact still possible";
  }).length;
  return (
    <Link className="banner quiet section" href="/swiss" style={{ marginTop: 14 }}>
      <span>
        <span className="t" style={{ display: "block" }}>Swiss live board</span>
        <span className="s num">
          Every round by record{picks.length ? ` · ${alive} of ${picks.length} exact calls still possible` : " · pick winners on the board"}
        </span>
      </span>
      <span className="go">Open →</span>
    </Link>
  );
}
