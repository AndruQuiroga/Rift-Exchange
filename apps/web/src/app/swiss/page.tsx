"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { TeamMark } from "@/components/bits";
import { SwissProgress } from "@/components/SwissProgress";
import { IconBack } from "@/components/icons";
import { countdown, partialReturn, potentialReturn, rc } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import { teamName } from "@/lib/teams";
import type { MarketT, Pick } from "@/lib/types";
import { Odds } from "@/components/Odds";

// A full card has exactly as many teams on each record as the stage can produce.
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
  const held = (m: MarketT) => (picks?.picks ?? []).filter((p) => p.market_id === m.id);
  const placedCount = board.filter((m) => inSlip(m) || held(m).length).length;
  const sel = board.find((m) => m.id === selected) ?? null;
  const lock = open[0] ? countdown(open[0].close_at, now) : null;

  if (data && !board.length) {
    return (
      <>
        <BackLink />
        <div className="empty" style={{ marginTop: 16 }}>
          <h3>Record calls aren&apos;t priced yet</h3>
          <p>They open once all sixteen Swiss teams are drawn.</p>
        </div>
      </>
    );
  }

  return (
    <>
      <BackLink />
      <Head open={open.length > 0} lock={lock} />

      {open.length ? (
        <>
          <div className="notice info" style={{ marginTop: 14 }}>
            Fill the card: two 3–0s, three of each record in between, two 0–3s. <b>Exact record</b> pays the full price; <b>right side, wrong record</b> (it still advanced, or still went out) returns a quarter.
          </div>

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

          <div className="section" style={{ marginTop: 14 }}>
            {RECORDS.map((r) => {
              const here = board.filter((m) => inSlip(m)?.code === r.code);
              const heldHere = board.flatMap((m) => held(m).filter((p) => p.outcome_id === m.outcomes.find((o) => o.code === r.code)?.id).map((p) => ({ m, p })));
              const target = sel?.outcomes.find((o) => o.code === r.code);
              const full = here.length + heldHere.length >= r.slots;
              const canDrop = sel && target?.odds && !full;
              return (
                <div key={r.code}>
                  {r.code === "2-3" ? <div className="cutline">Eliminated below</div> : null}
                  <div className={`recrow${canDrop ? " target" : ""}${full ? " full" : ""}`}>
                    <div className="recrow-head">
                      <span>
                        <span className={`r num ${r.code.startsWith("3") ? "adv" : "out"}`}>{r.label}</span>{" "}
                        <span className="muted" style={{ fontSize: 13 }}>{r.note}</span>
                      </span>
                      <span className={`num ${full ? "win" : "muted"}`} style={{ fontSize: 13 }}>{here.length + heldHere.length} / {r.slots}</span>
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
                            <span className="o num"><Odds value={o.odds} /></span>
                          </button>
                        );
                      })}
                      {canDrop ? (
                        <button
                          className="drop num"
                          onClick={() => {
                            slip.toggle(sel, target, LABEL, { slip: true });
                            setSelected(null);
                          }}
                        >
                          + {sel.team?.code} here · <Odds value={target.odds} />
                        </button>
                      ) : sel && full ? (
                        <span className="muted" style={{ fontSize: 13, alignSelf: "center" }}>Full · tap a team here to free a slot</span>
                      ) : null}
                    </div>
                    {canDrop && target.odds ? (
                      <div className="muted num" style={{ fontSize: 12, marginTop: 6 }}>
                        {rc(slip.defaultStake)} RC returns {rc(potentialReturn(slip.defaultStake, target.odds))} if exact, {rc(partialReturn(slip.defaultStake, target.odds, String(sel.params.consolation ?? "0.25")))} if right side.
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
          <p className="fineprint" style={{ textAlign: "left", marginTop: 14 }}>
            Leave a team unplaced if you have no read. Each placement is its own pick in your slip. Settles from official results when each team&apos;s Swiss run ends.
          </p>
        </>
      ) : (
        <SwissProgress board={board} />
      )}
    </>
  );
}

function Head({ open, lock }: { open: boolean; lock: string | null }) {
  return (
    <div className="page-head" style={{ paddingTop: 8 }}>
      <div>
        <div className="eyebrow">Swiss stage · 16 teams · 3 wins to advance</div>
        <h1 style={{ marginTop: 6 }}>Record calls</h1>
        <p>
          {open
            ? `Call each team's final record before the stage starts. ${lock ? `Locks in ${lock}.` : "Locks at the first Swiss match."}`
            : "Your calls against each team's record so far. The live board is on Today."}
        </p>
      </div>
    </div>
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
