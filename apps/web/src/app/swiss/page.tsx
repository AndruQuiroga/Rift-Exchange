"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { TeamMark } from "@/components/bits";
import { SwissProgress, useSwissCard } from "@/components/SwissProgress";
import { IconBack } from "@/components/icons";
import { api, ApiError } from "@/lib/api";
import { countdown, odds as fmtOdds, rc } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { teamName } from "@/lib/teams";
import type { MarketT, SwissCardT } from "@/lib/types";

const RECORDS = [
  { code: "3-0", label: "3–0", note: "undefeated" },
  { code: "3-1", label: "3–1", note: "advance" },
  { code: "3-2", label: "3–2", note: "advance" },
  { code: "2-3", label: "2–3", note: "out" },
  { code: "1-3", label: "1–3", note: "out" },
  { code: "0-3", label: "0–3", note: "winless" },
];

/** The same capped reward the server pays: base x price, at most the cap. */
const rewardAt = (card: SwissCardT | undefined, odds: string | null) =>
  card && odds ? Math.min(Math.round(card.reward.base_rc * Number(odds)), card.reward.cap_rc) : 0;

export default function RecordCardPage() {
  const now = useNow();
  const { data } = useSWR<{ markets: MarketT[] }>("/markets?category=FUTURES");
  const { data: card, mutate } = useSwissCard();
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const board = useMemo(() => {
    const ms = (data?.markets ?? []).filter((m) => m.kind === "swiss_record");
    const price = (m: MarketT) => Number(m.outcomes.find((o) => o.code === "3-0")?.odds ?? 999);
    return ms.sort((x, y) => price(x) - price(y));
  }, [data]);
  const open = !!card?.open;
  const callOf = (m: MarketT) => card?.calls.find((c) => c.market_id === m.id);
  const sel = board.find((m) => m.id === selected) ?? null;
  const lock = card?.close_at ? countdown(card.close_at, now) : null;
  const made = card?.calls.length ?? 0;

  async function write(market: MarketT, outcomeId: string | null) {
    setBusy(market.id);
    setError(null);
    try {
      const next = await api<SwissCardT>(`/swiss/card/${market.id}`, outcomeId ? { method: "PUT", json: { outcome_id: outcomeId } } : { method: "DELETE" });
      await mutate(next, { revalidate: false });
      setSelected(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save that call. Try again.");
    } finally {
      setBusy(null);
    }
  }

  if (data && !board.length) {
    return (
      <>
        <BackLink />
        <Head open={false} lock={null} />
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
      <Head open={open} lock={lock} />

      {!card ? (
        <div className="skeleton" style={{ height: 320 }} />
      ) : open ? (
        <>
          <div className="notice info">
            <b>Free to play.</b> An exact record pays {rc(card.reward.base_rc)} RC × its price (up to {rc(card.reward.cap_rc)} RC); right side, wrong record pays a quarter of that. The price locks when you make the call.
          </div>

          <section className="tray section" aria-label="Teams to call" style={{ marginTop: 14 }}>
            <div className="tray-head">
              <span className="eyebrow">Not called · {made}/16 done</span>
              <span className="muted" style={{ fontSize: 13 }}>{sel ? `${sel.team?.code ?? ""} — pick a record` : "Tap a team"}</span>
            </div>
            <div className="teamchips">
              {board
                .filter((m) => !callOf(m))
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
              {made === board.length ? <span className="muted" style={{ fontSize: 13 }}>All sixteen called.</span> : null}
            </div>
          </section>

          {error ? <div className="notice error" role="alert" style={{ marginTop: 10 }}>{error}</div> : null}

          <div className="section" style={{ marginTop: 14 }}>
            {RECORDS.map((r) => {
              const slots = card.slots[r.code] ?? 0;
              const here = board.filter((m) => callOf(m)?.record === r.code);
              const target = sel?.outcomes.find((o) => o.code === r.code);
              const full = here.length >= slots;
              const canDrop = !!sel && !!target?.odds && !full;
              return (
                <div key={r.code}>
                  {r.code === "2-3" ? <div className="cutline">Eliminated below</div> : null}
                  <div className={`recrow${canDrop ? " target" : ""}${full ? " full" : ""}`}>
                    <div className="recrow-head">
                      <span>
                        <span className={`r num ${r.code.startsWith("3") ? "adv" : "out"}`}>{r.label}</span>{" "}
                        <span className="muted" style={{ fontSize: 13 }}>{r.note}</span>
                      </span>
                      <span className={`num ${full ? "win" : "muted"}`} style={{ fontSize: 13 }}>{here.length} / {slots}</span>
                    </div>
                    <div className="teamchips">
                      {here.map((m) => {
                        const c = callOf(m)!;
                        return (
                          <button
                            key={m.id}
                            className="tchip placed"
                            disabled={busy === m.id}
                            onClick={() => write(m, null)}
                            aria-label={`Remove ${teamName(m.team)} from ${r.label}`}
                            title={`Locked at ${fmtOdds(c.odds)} · tap to remove`}
                          >
                            <TeamMark team={m.team ?? null} />
                            {m.team?.code}
                            <span className="o num">{rc(c.exact_rc)} RC</span>
                          </button>
                        );
                      })}
                      {canDrop && sel && target ? (
                        <button className="drop num" disabled={busy === sel.id} onClick={() => write(sel, target.id)}>
                          + {sel.team?.code} here · {rc(rewardAt(card, target.odds))} RC
                        </button>
                      ) : sel && full ? (
                        <span className="muted" style={{ fontSize: 13, alignSelf: "center" }}>Full · tap a team here to free a slot</span>
                      ) : null}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <p className="fineprint" style={{ textAlign: "left", marginTop: 14 }}>
            Calls save as you make them; change them until the first Swiss match. Rewards pay when each team&apos;s Swiss run ends.
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
        <div className="eyebrow">Swiss stage · free record card</div>
        <h1 style={{ marginTop: 6 }}>Record calls</h1>
        <p>
          {open
            ? `Call each team's final Swiss record. ${lock ? `Locks in ${lock}.` : "Locks at the first Swiss match."}`
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
