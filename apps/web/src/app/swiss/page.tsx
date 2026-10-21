"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { TeamMark } from "@/components/bits";
import { IconBack } from "@/components/icons";
import { countdown, odds as fmtOdds, partialReturn, potentialReturn, rc } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import { teamName } from "@/lib/teams";
import type { MarketT, Pick } from "@/lib/types";

const RECORDS = [
  { code: "3-0", label: "3–0", note: "undefeated", slots: 2 },
  { code: "3-1", label: "3–1", note: "advance", slots: 3 },
  { code: "3-2", label: "3–2", note: "advance", slots: 3 },
  { code: "2-3", label: "2–3", note: "out", slots: 3 },
  { code: "1-3", label: "1–3", note: "out", slots: 3 },
  { code: "0-3", label: "0–3", note: "winless", slots: 2 },
];
const LABEL = "Swiss Board";

export default function SwissBoardPage() {
  const now = useNow();
  const slip = useSlip();
  const { data } = useSWR<{ markets: MarketT[] }>("/markets?category=FUTURES");
  const { data: picks } = useSWR<{ picks: Pick[] }>("/me/picks?state=open");
  const [selected, setSelected] = useState<string | null>(null);

  const board = useMemo(() => {
    const ms = (data?.markets ?? []).filter((m) => m.kind === "swiss_record");
    const price = (m: MarketT) => Number(m.outcomes.find((o) => o.code === "3-0")?.odds ?? 999);
    return ms.sort((x, y) => price(x) - price(y));
  }, [data]);
  const open = board.filter((m) => m.state === "OPEN");

  // Where each team sits: the slip line for its market, else an already-placed pick.
  const inSlip = (m: MarketT) => {
    const line = slip.lines.find((l) => l.marketId === m.id);
    return line ? m.outcomes.find((o) => o.id === line.outcomeId) : undefined;
  };
  const held = (m: MarketT) => (picks?.picks ?? []).filter((p) => p.market_title === m.title);
  const placedCount = board.filter((m) => inSlip(m) || held(m).length).length;
  const sel = board.find((m) => m.id === selected) ?? null;
  const lock = open[0] ? countdown(open[0].close_at, now) : null;

  if (data && !board.length) {
    return (
      <>
        <BackLink />
        <div className="empty" style={{ marginTop: 16 }}>
          <h3>The Swiss Board isn&apos;t priced yet</h3>
          <p>It opens once all sixteen Swiss teams are drawn.</p>
        </div>
      </>
    );
  }

  return (
    <>
      <BackLink />
      <div className="page-head" style={{ paddingTop: 8 }}>
        <div>
          <div className="eyebrow">Futures · Swiss stage · 16 teams</div>
          <h1 style={{ marginTop: 6 }}>Swiss Board</h1>
          <p>
            Tap a team, then the record you think it finishes on.{" "}
            {open.length ? (lock ? `Locks in ${lock}, at the first Swiss match.` : "Locks at the first Swiss match.") : "The board is locked."}
          </p>
        </div>
      </div>

      <div className="notice info">
        <b>Exact record</b> pays the full price. <b>Right side, wrong record</b> (it still advanced, or still went out) returns a quarter of that.
      </div>

      {open.length ? (
        <section className="tray section" aria-label="Teams to place" style={{ marginTop: 14 }}>
          <div className="tray-head">
            <span className="eyebrow">Unplaced</span>
            <span className="muted" style={{ fontSize: 13 }}>{sel ? `${sel.team?.code ?? ""} selected — pick a record` : "Tap a team"}</span>
          </div>
          <div className="teamchips">
            {board
              .filter((m) => !inSlip(m) && !held(m).length)
              .map((m) => (
                <button
                  key={m.id}
                  className="tchip"
                  aria-pressed={selected === m.id}
                  disabled={m.state !== "OPEN"}
                  onClick={() => setSelected(selected === m.id ? null : m.id)}
                  aria-label={teamName(m.team)}
                >
                  <TeamMark team={m.team ?? null} />
                  {m.team?.code ?? m.title}
                </button>
              ))}
            {placedCount === board.length ? <span className="muted" style={{ fontSize: 13 }}>All sixteen placed.</span> : null}
          </div>
        </section>
      ) : null}

      <div className="section" style={{ marginTop: 14 }}>
        {RECORDS.map((r) => {
          const here = board.filter((m) => inSlip(m)?.code === r.code);
          const heldHere = board.flatMap((m) => held(m).filter((p) => p.outcome_label === r.label).map((p) => ({ m, p })));
          const target = sel?.outcomes.find((o) => o.code === r.code);
          return (
            <div key={r.code}>
              {r.code === "2-3" ? <div className="cutline">Eliminated below</div> : null}
              <div className={`recrow${sel && target?.odds ? " target" : ""}`}>
                <div className="recrow-head">
                  <span>
                    <span className={`r num ${r.code.startsWith("3") ? "adv" : "out"}`}>{r.label}</span>{" "}
                    <span className="muted" style={{ fontSize: 13 }}>{r.note}</span>
                  </span>
                  <span className="muted num" style={{ fontSize: 13 }}>{here.length + heldHere.length} / {r.slots}</span>
                </div>
                <div className="teamchips">
                  {heldHere.map(({ m, p }) => (
                    <span key={p.id} className="tchip held" title="Already placed">
                      <TeamMark team={m.team ?? null} />
                      {m.team?.code} · placed
                    </span>
                  ))}
                  {here.map((m) => {
                    const o = inSlip(m)!;
                    return (
                      <button key={m.id} className="tchip placed" onClick={() => slip.remove(o.id)} aria-label={`Remove ${teamName(m.team)} from ${r.label}`}>
                        <TeamMark team={m.team ?? null} />
                        {m.team?.code}
                        <span className="o num">{fmtOdds(o.odds)}</span>
                      </button>
                    );
                  })}
                  {sel && target?.odds ? (
                    <button
                      className="drop num"
                      onClick={() => {
                        slip.toggle(sel, target, LABEL);
                        setSelected(null);
                      }}
                    >
                      + {sel.team?.code} here · {fmtOdds(target.odds)}
                    </button>
                  ) : null}
                </div>
                {sel && target?.odds ? (
                  <div className="muted num" style={{ fontSize: 12, marginTop: 6 }}>
                    100 RC returns {rc(potentialReturn(100, target.odds))} if exact, {rc(partialReturn(100, target.odds, String(sel.params.consolation ?? "0.25")))} if right side.
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      <p className="fineprint" style={{ textAlign: "left", marginTop: 14 }}>
        Slot counts are a guide, not a rule — leave a team unplaced if you have no read. Each placement is its own pick in your slip. Settles from official results when each team&apos;s Swiss run ends.
      </p>
    </>
  );
}

function BackLink() {
  return (
    <div style={{ paddingTop: 14 }}>
      <Link href="/" className="link" style={{ display: "inline-flex", alignItems: "center", gap: 6, minHeight: 44 }}>
        <IconBack width={16} height={16} /> Today
      </Link>
    </div>
  );
}
