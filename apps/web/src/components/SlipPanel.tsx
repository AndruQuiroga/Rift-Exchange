"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { useSWRConfig } from "swr";
import { api, ApiError } from "@/lib/api";
import { odds as fmtOdds, partialReturn, potentialReturn, rc } from "@/lib/format";
import { blended, useHoldings, useMe, type Holding } from "@/lib/hooks";
import { initials, useFriendsOnMatch } from "@/lib/friends";
import { STAKES, useSlip } from "@/lib/slip";
import { stakeLimits, type StakeLimit } from "@/lib/stake-limits";
import type { EventT, Quote, QuoteItem, Receipt } from "@/lib/types";
import { IconCheck, IconClose } from "./icons";
import { CancelPick } from "./CancelPick";
import { LockTimer, MarketClose } from "./Timing";

/** After placing: who else is on this match. Hidden picks show as a count until their market locks (A-010). */
function ReceiptFriends({ event }: { event: EventT }) {
  const { picks, pending } = useFriendsOnMatch(event.id);
  const names = [...new Set([...pending.map((r) => r.user.display_name), ...picks.map((p) => p.user?.display_name ?? "A friend")])];
  if (!names.length) {
    return <p className="muted" style={{ fontSize: 13, marginTop: 12 }}>No friends on {event.team_a?.code} vs {event.team_b?.code} yet. You&apos;re first in.</p>;
  }
  const hidden = pending.reduce((n, r) => n + r.picks, 0);
  const reveal = pending.map((r) => r.reveals_at).sort()[0];
  return (
    <Link className="receipt-friends" href={`/events/${event.id}`}>
      <span className="fdots">{names.slice(0, 4).map((n) => <span key={n} className="fdot">{initials(n)}</span>)}</span>
      <span style={{ minWidth: 0, flex: 1 }}>
        <b>{names.join(", ")}</b> {names.length === 1 ? "is" : "are"} on {event.team_a?.code} vs {event.team_b?.code}
        <span className="muted num" style={{ display: "block", fontSize: 12 }}>
          {hidden ? <>{hidden} hidden pick{hidden === 1 ? "" : "s"} · <LockTimer at={reveal} label="reveal in" compact /></> : `${picks.length} pick${picks.length === 1 ? "" : "s"} revealed`}
        </span>
      </span>
      <span aria-hidden="true">›</span>
    </Link>
  );
}

/**
 * Adding to a pick you already hold: each bet keeps its own odds, so show the bet you have, this one, and the
 * two together (total stake, blended price, total return), with which way the price moved since.
 */
function TopUp({ holding, stake, odds }: { holding: Holding; stake: number | null; odds: string }) {
  const add = stake ? potentialReturn(stake, odds) : 0;
  const was = blended(holding);
  const moved = Number(odds) > Number(was) ? "up" : Number(odds) < Number(was) ? "down" : null;
  const total = { ...holding, stake: holding.stake + (stake ?? 0), ret: holding.ret + add };
  return (
    <div className="topup num" aria-label="Adding to a pick you hold">
      <div className="topup-row">
        <span className="muted">You hold</span>
        <span>{rc(holding.stake)} RC @ {fmtOdds(was)}{holding.picks.length > 1 ? " avg" : ""} → {rc(holding.ret)}</span>
      </div>
      <div className="topup-row">
        <span className="muted">Adding</span>
        <span>
          {stake ? `${rc(stake)} RC` : "—"} @ {fmtOdds(odds)}
          {moved ? <span className={`topup-move ${moved}`}>{moved === "up" ? "▲" : "▼"} from {fmtOdds(was)}</span> : null}
          {stake ? ` → ${rc(add)}` : ""}
        </span>
      </div>
      <div className="topup-row total">
        <span>Together</span>
        <span><b>{rc(total.stake)} RC</b> @ {fmtOdds(blended(total))} avg → <b>{rc(total.ret)} RC</b></span>
      </div>
    </div>
  );
}

type Phase =
  | { kind: "edit" }
  | { kind: "review"; quote: Quote; previous?: Record<string, string> }
  | { kind: "busy"; label: string }
  | { kind: "receipt"; receipt: Receipt };

/** Opt in to placing a pick the moment its price is tapped, at your usual stake, with a few seconds to undo. */
export function QuickToggle() {
  const slip = useSlip();
  return (
    <label className="quick-toggle">
      <span>
        <span className="t">One-tap picks</span>
        <span className="s">Tap a price to place {rc(slip.defaultStake)} RC straight away · 5 s to undo</span>
      </span>
      <input type="checkbox" role="switch" checked={slip.quick} onChange={(e) => slip.setQuick(e.target.checked)} />
    </label>
  );
}

export function SlipPanel({ onClose }: { onClose?: () => void }) {
  const slip = useSlip();
  const { data: me } = useMe();
  const holdings = useHoldings();
  const { mutate } = useSWRConfig();
  const [phase, setPhase] = useState<Phase>({ kind: "edit" });
  const [error, setError] = useState<string | null>(null);
  const [limits, setLimits] = useState<Record<string, StakeLimit>>({});
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  // Picks whose stake is being typed by hand; the rest show their amount as a chip.
  const [editing, setEditing] = useState<Set<string>>(new Set());
  const keyRef = useRef<{ quoteId: string; key: string } | null>(null);

  const available = me?.wallet.available_rc ?? 0;
  const lines = slip.lines;
  const staked = lines.reduce((s, l) => s + (l.stake ?? 0), 0);
  const possible = lines.reduce((s, l) => s + (l.stake ? potentialReturn(l.stake, l.odds) : 0), 0);
  const missing = lines.some((l) => !l.stake || l.stake <= 0);
  const over = staked > available;
  const invalidLines = lines.filter((line) => limits[line.marketId] && (line.stake ?? 0) > limits[line.marketId].remaining);
  useEffect(() => {
    panelRef.current?.querySelector<HTMLElement>("[data-stake-error]")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [limits]);

  function showError(cause: unknown, fallback: string) {
    const affected = cause instanceof ApiError && cause.code === "STAKE_LIMIT" ? stakeLimits(cause.details) : [];
    if (affected.length) {
      setLimits((previous) => ({ ...previous, ...Object.fromEntries(affected.map((limit) => [limit.marketId, limit])) }));
      setPhase({ kind: "edit" });
      setError(null);
      return;
    }
    setError(cause instanceof ApiError ? cause.message : fallback);
  }

  async function requestQuote(): Promise<Quote> {
    return api<Quote>("/quotes", { method: "POST", json: { items: lines.map((l) => ({ outcome_id: l.outcomeId, stake_rc: l.stake })) } });
  }

  /** One tap: get today's prices and place. Only a price that moved since you picked stops to ask. */
  async function placeNow() {
    setError(null);
    setPhase({ kind: "busy", label: "Placing your picks…" });
    try {
      const quote = await requestQuote();
      const previous: Record<string, string> = {};
      for (const it of quote.items) {
        const line = lines.find((l) => l.outcomeId === it.outcome_id);
        if (line && line.odds !== it.odds) previous[it.outcome_id] = line.odds;
      }
      if (Object.keys(previous).length) {
        slip.updatePrices(quote.items);
        setPhase({ kind: "review", quote, previous });
        return;
      }
      await place(quote);
    } catch (e) {
      setPhase({ kind: "edit" });
      showError(e, "Couldn't place your picks.");
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
          showError(inner, "Couldn't refresh prices.");
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
      showError(e, "Couldn't place your picks.");
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
        <div className="receipt-hero" role="status">
          <span className="tick" aria-hidden="true"><IconCheck width={22} height={22} /></span>
          <span>
            <b>{r.selections.length} pick{r.selections.length === 1 ? "" : "s"} locked in</b>
            <span className="muted num" style={{ display: "block", fontSize: 13 }}>
              at {new Date(r.accepted_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })} · odds frozen ·{" "}
              {rc(r.selections.reduce((n, s) => n + s.potential_return_rc, 0))} RC back if all win
            </span>
          </span>
        </div>
        <div style={{ marginTop: 12 }}>
          {r.selections.map((s, i) => (
            <div className="slip-line reveal" style={{ animationDelay: `${i * 60}ms` }} key={s.id}>
              <div className="top">
                <div>
                  <div className="sel">{s.outcome_label}</div>
                  <div className="ctx">{s.market_title}{s.event ? ` · ${s.event.team_a?.code} vs ${s.event.team_b?.code}` : ""}</div>
                </div>
                <div className="px num">{fmtOdds(s.odds)}</div>
              </div>
              <div className="if-correct num">
                Staked <b>{rc(s.stake_rc)} RC</b> · returns <b>{rc(s.potential_return_rc)} RC</b> if correct
              </div>
              <div className="receipt-when">
                <MarketClose at={s.close_at} known={s.close_known} rule={s.close_rule} scheduledAt={s.event?.scheduled_at} label="Betting closes in" />
                <span className="muted">Result shows the moment it&apos;s known; credits follow 5 min later once the data holds.</span>
                <CancelPick pick={s} compact />
              </div>
            </div>
          ))}
        </div>
        {[...new Map(r.selections.filter((s) => s.event).map((s) => [s.event!.id, s.event!])).values()].map((e) => (
          <ReceiptFriends key={e.id} event={e} />
        ))}
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
  const groups = lines.reduce<{ label: string; lines: typeof lines }[]>((out, l) => {
    const g = out.find((x) => x.label === l.eventLabel);
    if (g) g.lines.push(l);
    else out.push({ label: l.eventLabel, lines: [l] });
    return out;
  }, []);

  return (
    <div ref={panelRef}>
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

      {invalidLines.length > 0 ? (
        <div className="notice error" role="alert" style={{ marginBottom: 14 }}>
          <strong>No bets were placed.</strong> {invalidLines.length === 1 ? "One pick exceeds its" : `${invalidLines.length} picks exceed their`} total market limit.
          {" "}Adjust or remove the highlighted {invalidLines.length === 1 ? "pick" : "picks"} below; your other picks are saved.
        </div>
      ) : null}
      {lines.length === 0 ? (
        <div className="empty" style={{ padding: "24px 16px" }}>
          <h3>Slip is empty</h3>
          <p>Pick an outcome to see stake, return and profit here.</p>
        </div>
      ) : (
        <>
          {groups.map((g) => (
            <div key={g.label} className="slip-group">
              {groups.length > 1 ? (
                <div className="slip-group-head">
                  <span>{g.label}</span>
                  <span className="muted num">{g.lines.length} pick{g.lines.length === 1 ? "" : "s"}</span>
                </div>
              ) : null}
          {g.lines.map((l) => {
            const was = reviewing?.previous?.[l.outcomeId];
            const limit = limits[l.marketId];
            const invalid = !!limit && (l.stake ?? 0) > limit.remaining;
            const limitId = `${panelId}-${l.outcomeId}-limit`;
            return (
              <div className="slip-line" key={l.outcomeId} data-stake-error={invalid || undefined}>
                <div className="top">
                  <div style={{ minWidth: 0 }}>
                    <div className="sel">{l.outcomeLabel}</div>
                    <div className="ctx">
                      {l.marketTitle}
                      {groups.length > 1 ? null : ` · ${l.eventLabel}`}
                    </div>
                    {l.closeAt ? <MarketClose at={l.closeAt} rule={l.closeRule === "draft" ? "draft" : null} known={!(l.closesWithGame && Date.parse(l.closeAt) - Date.now() > 600_000)} compact /> : null}
                  </div>
                  <div className="px num" aria-live="polite">
                    {was ? <span className="was">{fmtOdds(was)}</span> : null}
                    {fmtOdds(l.odds)}
                  </div>
                </div>
                <div className="stake-row">
                  {!editing.has(l.outcomeId) ? (
                    // Each pick has its own amounts, so they can differ without typing.
                    <div className="line-presets" role="group" aria-label={`Stake on ${l.outcomeLabel}`}>
                      {STAKES.map((v) => (
                        <button
                          key={v}
                          type="button"
                          className="num"
                          aria-pressed={l.stake === v}
                          disabled={phase.kind !== "edit" || (!!limit && v > limit.remaining)}
                          onClick={() => { slip.setStake(l.outcomeId, v); slip.setDefaultStake(v); }}
                        >
                          {v >= 1000 ? `${v / 1000}K` : v}
                        </button>
                      ))}
                      <button
                        type="button"
                        className="num"
                        aria-pressed={!!l.stake && !STAKES.includes(l.stake)}
                        disabled={phase.kind !== "edit"}
                        onClick={() => setEditing((e) => new Set(e).add(l.outcomeId))}
                        aria-label={`Custom stake on ${l.outcomeLabel}${l.stake && !STAKES.includes(l.stake) ? `, now ${l.stake} RC` : ""}`}
                      >
                        {l.stake && !STAKES.includes(l.stake) ? rc(l.stake) : "Other"}
                      </button>
                    </div>
                  ) : (
                  <label className="stake-input">
                    <span className="sr-only">Stake for {l.outcomeLabel}</span>
                    <input
                      className="num"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      placeholder="Stake"
                      autoFocus
                      value={l.stake ?? ""}
                      aria-invalid={invalid || undefined}
                      aria-describedby={limit ? limitId : undefined}
                      disabled={phase.kind !== "edit"}
                      onChange={(e) => {
                        const digits = e.target.value.replace(/\D/g, "").slice(0, 12);
                        slip.setStake(l.outcomeId, digits ? Number(digits) : null);
                      }}
                    />
                    <span>RC</span>
                  </label>
                  )}
                  <button className="icon-btn" aria-label={`Remove ${l.outcomeLabel}`} onClick={() => slip.remove(l.outcomeId)} disabled={phase.kind !== "edit"}>
                    <IconClose width={18} height={18} />
                  </button>
                </div>
                {limit ? (
                  <div id={limitId} className={invalid ? "notice error" : "hint"} style={{ marginTop: 8 }}>
                    <strong>{rc(limit.cap)} RC total limit on this market.</strong> You already have {rc(limit.placed)} RC staked across all bets; you can add {rc(limit.remaining)} RC more.
                    {invalid ? (
                      <div style={{ marginTop: 8 }}>
                        {limit.remaining > 0 ? (
                          <button type="button" className="btn secondary" onClick={() => slip.setStake(l.outcomeId, limit.remaining)}>
                            Use {rc(limit.remaining)} RC
                          </button>
                        ) : (
                          <button type="button" className="btn secondary" onClick={() => slip.remove(l.outcomeId)}>
                            Remove this pick — limit reached
                          </button>
                        )}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <div className="if-correct num">
                  If correct: <b>{l.stake ? `${rc(potentialReturn(l.stake, l.odds))} RC` : "—"}</b>
                  {l.stake ? ` (+${rc(potentialReturn(l.stake, l.odds) - l.stake)} profit)` : ""}
                  {l.stake && l.consolation ? <> · right side <b>{rc(partialReturn(l.stake, l.odds, l.consolation))} RC</b></> : null}
                </div>
                {holdings.get(l.outcomeId) ? <TopUp holding={holdings.get(l.outcomeId)!} stake={l.stake} odds={l.odds} /> : null}
              </div>
            );
          })}
            </div>
          ))}

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
                  Accept new odds &amp; place · {rc(reviewing.quote.total_stake_rc)} RC
                </button>
                <button className="btn secondary" onClick={() => setPhase({ kind: "edit" })}>
                  Edit stakes
                </button>
              </>
            ) : (
              <button className="btn" style={{ marginTop: 10 }} disabled={missing || over || staked === 0 || invalidLines.length > 0} onClick={placeNow}>
                {invalidLines.length ? "Fix highlighted stakes to continue" : missing ? "Enter a stake for each pick"
                  : `Place ${lines.length} pick${lines.length === 1 ? "" : "s"} · ${rc(staked)} RC`}
              </button>
            )}
          </div>
        </>
      )}
      {phase.kind === "edit" ? <QuickToggle /> : null}
      <p className="fineprint">Play credits only · no cash value · odds lock when placed</p>
    </div>
  );
}
