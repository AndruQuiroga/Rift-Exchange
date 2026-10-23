"use client";

import type { MarketT, OutcomeT, Pick, Team } from "@/lib/types";
import { odds as fmtOdds, oddsSpoken } from "@/lib/format";
import { usePlaced } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import { IconCheck, IconLock } from "./icons";
import { Odds } from "./Odds";
import { CallStatus } from "./Timing";

export function TeamMark({ team, large }: { team: Team | null; large?: boolean }) {
  const src = team?.image_url?.replace(/^http:/, "https:");
  return (
    <span className={`mark${large ? " lg" : ""}`} aria-hidden="true">
      {/* eslint-disable-next-line @next/next/no-img-element -- tiny remote team marks; no optimiser needed */}
      {src ? <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" /> : (team?.code ?? "TBD").slice(0, 3)}
    </span>
  );
}

export function OddsButton({ market, outcome, eventLabel }: { market: MarketT; outcome: OutcomeT; eventLabel: string }) {
  const slip = useSlip();
  const selected = slip.isSelected(outcome.id);
  const placed = usePlaced().has(outcome.id);
  const winner = market.result && !market.result.void && market.result.winning_codes.includes(outcome.code);
  const available = market.state === "OPEN" && outcome.odds !== null;
  return (
    <button
      type="button"
      className={`odds${winner ? " won" : ""}`}
      aria-pressed={selected}
      data-placed={placed || undefined}
      disabled={!available && !selected}
      onClick={() => slip.toggle(market, outcome, eventLabel)}
      aria-label={`${outcome.label}, ${oddsSpoken(outcome.odds)}${selected ? ", in slip" : ""}${placed ? ", already placed" : ""}${!available ? ", unavailable" : ""}`}
    >
      <span className="lbl">{outcome.label}</span>
      <span className="px num">
        {winner ? (
          <span className="badge win">Won</span>
        ) : market.state === "OPEN" ? (
          outcome.odds ? (
            <Odds value={outcome.odds} />
          ) : (
            <small>—</small>
          )
        ) : (
          <>
            <span className="muted">{fmtOdds(outcome.odds)}</span>
          </>
        )}
      </span>
      <span className="check" aria-hidden="true">
        <IconCheck width={18} height={18} />
      </span>
    </button>
  );
}

const STATE_COPY: Record<string, string> = {
  LOCKED: "Locked",
  SUSPENDED: "Suspended",
  HOLD: "Awaiting data",
  SETTLED: "Settled",
  VOID: "Void",
};

export function MarketBlock({ market, eventLabel, compact }: { market: MarketT; eventLabel: string; compact?: boolean }) {
  const n = market.outcomes.length;
  const layout = n === 2 ? "" : n === 3 ? " three" : " list";
  return (
    <section className="market" aria-labelledby={`m-${market.id}`}>
      <div className="market-head">
        <h3 id={`m-${market.id}`}>{market.title}</h3>
        {market.state !== "OPEN" ? (
          <span className="state-note">
            <IconLock width={14} height={14} /> {STATE_COPY[market.state] ?? market.state}
          </span>
        ) : market.confidence === "EXPERIMENTAL" ? (
          <span className="tag">Experimental odds</span>
        ) : null}
      </div>
      <div className={`odds-grid${layout}`}>
        {market.outcomes.map((o) => (
          <OddsButton key={o.id} market={market} outcome={o} eventLabel={eventLabel} />
        ))}
      </div>
      {compact ? null : (
      <div className="rules">
        <p className="muted">{market.rules.split(/(?<=\.)\s/)[0]}</p>
        {market.state_reason && market.state !== "OPEN" ? <p style={{ marginTop: 6 }}>Status: {market.state_reason}</p> : null}
        {market.result ? <p style={{ marginTop: 6 }}>Result: {market.result.reason}{market.result.revision > 1 ? ` (correction #${market.result.revision - 1})` : ""}</p> : null}
        <details>
          <summary>Full rules</summary>
          <p>{market.rules}</p>
        </details>
      </div>
      )}
    </section>
  );
}

export function PickStatus({ pick }: { pick: Pick }) {
  if (pick.status === "WON") return <span className="status won"><span className="dot" />Won</span>;
  if (pick.status === "PARTIAL") {
    const ban = pick.kind === "champion_picked" || pick.kind === "lane_duel"; // D-033/D-036: half back
    return <span className={`status ${ban ? "void" : "won"}`}><span className="dot" />{ban ? "Half back" : "Right side"}</span>;
  }
  if (pick.status === "LOST") return <span className="status lost"><span className="dot" />Lost</span>;
  if (pick.status === "VOID") return <span className="status void"><span className="dot" />Void</span>;
  if (pick.call) return <CallStatus call={pick.call} />;
  if (pick.market_state === "HOLD") return <span className="status hold"><span className="dot" />Awaiting data</span>;
  if (pick.market_state === "OPEN") return <span className="status open"><span className="dot" />Open</span>;
  return <span className="status"><IconLock width={12} height={12} />Locked</span>;
}

export function EventStatus({ status, closeAt, countdownText }: { status: string; closeAt?: string | null; countdownText?: string | null }) {
  if (status === "LIVE") return <span className="status live"><span className="dot" />Live</span>;
  if (status === "COMPLETED") return <span className="status">Final</span>;
  if (status === "POSTPONED") return <span className="status hold">Postponed</span>;
  if (closeAt && countdownText) return <span className="when">Starts in {countdownText}</span>;
  if (closeAt) return <span className="state-note">Starting soon</span>;
  return null;
}

/** A failed on-demand price (champion, duel, kill line): what went wrong and one tap to try again. */
export function RetryNotice({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <div className="notice error retry" role="alert" style={{ marginTop: 10 }}>
      <span>{text}</span>
      <button type="button" className="btn small secondary" onClick={onRetry}>Try again</button>
    </div>
  );
}
