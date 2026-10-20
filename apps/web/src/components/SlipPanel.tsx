"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { useSWRConfig } from "swr";
import { api, ApiError } from "@/lib/api";
import { odds as fmtOdds, potentialReturn, rc } from "@/lib/format";
import { useMe } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import type { Quote, QuoteItem, Receipt } from "@/lib/types";
import { IconClose } from "./icons";

type Phase =
  | { kind: "edit" }
  | { kind: "review"; quote: Quote; previous?: Record<string, string> }
  | { kind: "busy"; label: string }
  | { kind: "receipt"; receipt: Receipt };

export function SlipPanel({ onClose }: { onClose?: () => void }) {
  const slip = useSlip();
  const { data: me } = useMe();
  const { mutate } = useSWRConfig();
  const [phase, setPhase] = useState<Phase>({ kind: "edit" });
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const keyRef = useRef<{ quoteId: string; key: string } | null>(null);

  const available = me?.wallet.available_rc ?? 0;
  const lines = slip.lines;
  const staked = lines.reduce((s, l) => s + (l.stake ?? 0), 0);
  const possible = lines.reduce((s, l) => s + (l.stake ? potentialReturn(l.stake, l.odds) : 0), 0);
  const missing = lines.some((l) => !l.stake || l.stake <= 0);
  const over = staked > available;
  const activeId = active && lines.some((l) => l.outcomeId === active) ? active : lines[lines.length - 1]?.outcomeId;

  function preset(kind: "+100" | "25" | "50" | "all") {
    if (!activeId) return;
    const others = lines.filter((l) => l.outcomeId !== activeId).reduce((s, l) => s + (l.stake ?? 0), 0);
    const room = Math.max(available - others, 0);
    const current = lines.find((l) => l.outcomeId === activeId)?.stake ?? 0;
    const next =
      kind === "+100" ? Math.min(current + 100, room) : kind === "all" ? room : Math.floor((available * (kind === "25" ? 25 : 50)) / 100);
    slip.setStake(activeId, next > 0 ? next : null);
  }

  async function requestQuote(): Promise<Quote> {
    return api<Quote>("/quotes", { method: "POST", json: { items: lines.map((l) => ({ outcome_id: l.outcomeId, stake_rc: l.stake })) } });
  }

  async function review() {
    setError(null);
    setPhase({ kind: "busy", label: "Getting current prices…" });
    try {
      const quote = await requestQuote();
      const previous: Record<string, string> = {};
      for (const it of quote.items) {
        const line = lines.find((l) => l.outcomeId === it.outcome_id);
        if (line && line.odds !== it.odds) previous[it.outcome_id] = line.odds;
      }
      slip.updatePrices(quote.items);
      setPhase({ kind: "review", quote, previous });
    } catch (e) {
      setPhase({ kind: "edit" });
      setError(e instanceof ApiError ? e.message : "Couldn't get a quote.");
    }
  }

  async function place(quote: Quote, previousOdds?: Record<string, string>) {
    setError(null);
    if (!keyRef.current || keyRef.current.quoteId !== quote.quote_id) {
      keyRef.current = { quoteId: quote.quote_id, key: crypto.randomUUID() };
    }
    const key = keyRef.current.key;
    setPhase({ kind: "busy", label: "Placing your picks…" });
    try {
      const receipt = await api<Receipt>("/tickets", {
        method: "POST",
        headers: { "Idempotency-Key": key },
        json: { quote_id: quote.quote_id, confirm_odds_versions: Object.fromEntries(quote.items.map((i) => [i.outcome_id, i.odds_version])) },
      });
      done(receipt);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (e.code === "ODDS_CHANGED") {
        const next = e.details.new_quote as Quote;
        const prev = Object.fromEntries((e.details.previous_items as QuoteItem[]).map((i) => [i.outcome_id, i.odds]));
        slip.updatePrices(next.items);
        setPhase({ kind: "review", quote: next, previous: prev });
        return;
      }
      if (e.code === "QUOTE_EXPIRED") {
        // Re-quote; if every price is unchanged the player already agreed to these exact terms.
        try {
          const fresh = await requestQuote();
          const same = fresh.items.every((i) => quote.items.find((q) => q.outcome_id === i.outcome_id)?.odds === i.odds);
          if (same) return place(fresh);
          slip.updatePrices(fresh.items);
          setPhase({ kind: "review", quote: fresh, previous: previousOdds ?? Object.fromEntries(quote.items.map((i) => [i.outcome_id, i.odds])) });
        } catch (inner) {
          setPhase({ kind: "edit" });
          setError(inner instanceof ApiError ? inner.message : "Couldn't refresh prices.");
        }
        return;
      }
      if (e.code === "NETWORK" || e.status >= 500) {
        setPhase({ kind: "busy", label: "Checking whether your picks were received…" });
        try {
          const receipt = await api<Receipt>(`/tickets/by-key/${encodeURIComponent(key)}`);
          done(receipt);
        } catch (lookup) {
          setPhase({ kind: "review", quote });
          setError(
            lookup instanceof ApiError && lookup.status === 404
              ? "Your picks were not placed. You can safely try again."
              : "We couldn't confirm whether your picks went through. Check My Picks before retrying.",
          );
        }
        return;
      }
      setPhase({ kind: "edit" });
      setError(e.message);
    }
  }

  function done(receipt: Receipt) {
    keyRef.current = null;
    slip.clear();
    setPhase({ kind: "receipt", receipt });
    mutate((k) => typeof k === "string");
  }

  if (phase.kind === "receipt") {
    const r = phase.receipt;
    return (
      <div>
        <div className="slip-head">
          <h2>Picks placed</h2>
          {onClose ? (
            <button className="icon-btn" onClick={onClose} aria-label="Close slip">
              <IconClose width={20} height={20} />
            </button>
          ) : null}
        </div>
        <div className="notice success" role="status">
          {r.selections.length} pick{r.selections.length === 1 ? "" : "s"} accepted at{" "}
          {new Date(r.accepted_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}. Odds are locked in.
        </div>
        <div style={{ marginTop: 12 }}>
          {r.selections.map((s) => (
            <div className="slip-line" key={s.id}>
              <div className="top">
                <div>
                  <div className="sel">{s.outcome_label}</div>
                  <div className="ctx">{s.market_title}</div>
                </div>
                <div className="px num">{fmtOdds(s.odds)}×</div>
              </div>
              <div className="if-correct num">
                Staked <b>{rc(s.stake_rc)} RC</b> · returns <b>{rc(s.potential_return_rc)} RC</b> if correct
              </div>
            </div>
          ))}
        </div>
        <div className="totals num">
          <div>
            <span className="sub">Available now</span>
            <b>{rc(r.wallet.available_rc)} RC</b>
          </div>
          <div>
            <span className="sub">Receipt</span>
            <span className="muted" style={{ fontSize: 13 }}>{r.ticket_id.slice(0, 8)}</span>
          </div>
        </div>
        <Link className="btn secondary" href="/picks" style={{ marginTop: 14 }}>
          View my picks
        </Link>
        <button className="btn" style={{ marginTop: 8 }} onClick={() => setPhase({ kind: "edit" })}>
          Make more picks
        </button>
      </div>
    );
  }

  const reviewing = phase.kind === "review" ? phase : null;
  const changedIds = reviewing?.previous ? Object.keys(reviewing.previous) : [];

  return (
    <div>
      <div className="slip-head">
        <div>
          <h2>Your slip</h2>
          <div className="muted" style={{ fontSize: 13 }}>
            {lines.length === 0 ? "Tap any price to add a pick" : `${lines.length} independent pick${lines.length === 1 ? "" : "s"}`}
          </div>
        </div>
        {onClose ? (
          <button className="icon-btn" onClick={onClose} aria-label="Close slip">
            <IconClose width={20} height={20} />
          </button>
        ) : null}
      </div>

      {lines.length === 0 ? (
        <div className="empty" style={{ padding: "24px 16px" }}>
          <h3>Slip is empty</h3>
          <p>Pick an outcome to see stake, return and profit here.</p>
        </div>
      ) : (
        <>
          {lines.map((l) => {
            const was = reviewing?.previous?.[l.outcomeId];
            return (
              <div className="slip-line" key={l.outcomeId}>
                <div className="top">
                  <div style={{ minWidth: 0 }}>
                    <div className="sel">{l.outcomeLabel}</div>
                    <div className="ctx">
                      {l.marketTitle} · {l.eventLabel}
                    </div>
                  </div>
                  <div className="px num" aria-live="polite">
                    {was ? <span className="was">{fmtOdds(was)}</span> : null}
                    {fmtOdds(l.odds)}×
                  </div>
                </div>
                <div className="stake-row">
                  <label className="stake-input">
                    <span className="sr-only">Stake for {l.outcomeLabel}</span>
                    <input
                      className="num"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      placeholder="Stake"
                      value={l.stake ?? ""}
                      disabled={phase.kind !== "edit"}
                      onFocus={() => setActive(l.outcomeId)}
                      onChange={(e) => {
                        const digits = e.target.value.replace(/\D/g, "").slice(0, 12);
                        slip.setStake(l.outcomeId, digits ? Number(digits) : null);
                      }}
                    />
                    <span>RC</span>
                  </label>
                  <button className="icon-btn" aria-label={`Remove ${l.outcomeLabel}`} onClick={() => slip.remove(l.outcomeId)} disabled={phase.kind !== "edit"}>
                    <IconClose width={18} height={18} />
                  </button>
                </div>
                <div className="if-correct num">
                  If correct: <b>{l.stake ? `${rc(potentialReturn(l.stake, l.odds))} RC` : "—"}</b>
                  {l.stake ? ` (+${rc(potentialReturn(l.stake, l.odds) - l.stake)} profit)` : ""}
                </div>
              </div>
            );
          })}

          {phase.kind === "edit" ? (
            <div className="presets" role="group" aria-label="Stake shortcuts for the selected pick">
              <button onClick={() => preset("+100")}>+100</button>
              <button onClick={() => preset("25")}>25%</button>
              <button onClick={() => preset("50")}>50%</button>
              <button onClick={() => preset("all")}>All</button>
            </div>
          ) : null}

          <div className="totals num" aria-live="polite">
            <div>
              <span className="sub">Staked</span>
              <b>{rc(staked)} RC</b>
            </div>
            <div className="strong">
              <span>{lines.length > 1 ? "Return if all win" : "Return if correct"}</span>
              <span>{rc(possible)} RC</span>
            </div>
            <div>
              <span className="sub">{lines.length > 1 ? "Profit if all win" : "Profit if correct"}</span>
              <span className="win">+{rc(Math.max(possible - staked, 0))} RC</span>
            </div>
            <div>
              <span className="sub">Available after</span>
              <span className={over ? "loss" : undefined}>{rc(available - staked)} RC</span>
            </div>
          </div>

          <div style={{ marginTop: 14 }}>
            {over ? (
              <div className="notice error" role="alert">
                Available {rc(available)} RC; your slip needs {rc(staked)} RC.
              </div>
            ) : null}
            {error ? (
              <div className="notice error" role="alert" style={{ marginTop: over ? 8 : 0 }}>
                {error}
              </div>
            ) : null}
            {changedIds.length ? (
              <div className="notice" role="alert">
                {changedIds.length === 1 ? "A price changed" : "Some prices changed"} since you picked. Review the new odds before placing.
              </div>
            ) : null}
            {phase.kind === "busy" ? (
              <button className="btn" disabled style={{ marginTop: 10 }}>
                {phase.label}
              </button>
            ) : reviewing ? (
              <>
                <button className="btn" style={{ marginTop: 10 }} onClick={() => place(reviewing.quote, reviewing.previous)}>
                  {changedIds.length ? "Accept new odds & place" : `Place ${lines.length} pick${lines.length === 1 ? "" : "s"}`} · {rc(reviewing.quote.total_stake_rc)} RC
                </button>
                <button className="btn secondary" onClick={() => setPhase({ kind: "edit" })}>
                  Edit stakes
                </button>
              </>
            ) : (
              <button className="btn" style={{ marginTop: 10 }} disabled={missing || over || staked === 0} onClick={review}>
                {missing ? "Enter a stake for each pick" : "Review picks"}
              </button>
            )}
          </div>
        </>
      )}
      <p className="fineprint">Play credits only · no cash value · odds lock when placed</p>
    </div>
  );
}
