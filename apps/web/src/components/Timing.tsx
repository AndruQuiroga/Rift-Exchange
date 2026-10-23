"use client";

import { useNow } from "@/lib/hooks";
import type { PickCall } from "@/lib/types";
import { IconLock } from "./icons";

/** "4:05" under an hour, "1h 12m" under a day, "2d 3h" beyond. */
export function clockText(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  if (s < 3600) return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const m = Math.floor(s / 60);
  if (m < 24 * 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${Math.floor(m / 1440)}d ${Math.floor((m % 1440) / 60)}h`;
}

/**
 * The one countdown for anything that locks: ticks every second, turns amber in the last two minutes and red
 * in the last thirty seconds, then reads "Locked". Every market, section and slip line uses it.
 */
export function LockTimer({ at, label = "Locks in", compact }: { at: string | null | undefined; label?: string; compact?: boolean }) {
  const now = useNow(1000);
  if (!at) return null;
  const ms = Date.parse(at) - now;
  if (ms <= 0) {
    return (
      <span className={`timer locked${compact ? " compact" : ""}`} role="status">
        <IconLock width={11} height={11} aria-hidden="true" /> Locked
      </span>
    );
  }
  const tone = ms < 30_000 ? " urgent" : ms < 120_000 ? " soon" : "";
  return (
    <span className={`timer num${tone}${compact ? " compact" : ""}`} role="timer" aria-label={`${label} ${clockText(ms)}`}>
      {compact ? null : <span className="t-label">{label}</span>}
      <b>{clockText(ms)}</b>
    </span>
  );
}

/** A market's close: the countdown once it is real, "3:00 into the game" while its game hasn't loaded. */
export function MarketClose({ at, known, label = "Locks in", compact }: { at: string | null | undefined; known?: boolean; label?: string; compact?: boolean }) {
  if (known === false) return <span className={`timer${compact ? " compact" : ""}`}>Closes <b>3:00 into the game</b></span>;
  return <LockTimer at={at} label={label} compact={compact} />;
}

/** When a known result pays: "pays in 3:12", "paying now", or after the game for a live call. */
export function PayoutNote({ payAt, final }: { payAt: string | null; final: boolean }) {
  const now = useNow(1000);
  if (!final) return <span className="payout">confirms after the game</span>;
  if (!payAt) return <span className="payout">pays once the data holds steady</span>;
  const ms = Date.parse(payAt) - now;
  return ms > 0
    ? <span className="payout num">pays in <b>{clockText(ms)}</b></span>
    : <span className="payout">paying now</span>;
}

/** An open pick whose result is already known: "Winning · pays in 3:12" with a little reveal. */
export function CallStatus({ call }: { call: PickCall }) {
  if (call.pending_refund) {
    return <span className="status hold called" title={call.reason}><span className="dot" />Not picked · checking bans</span>;
  }
  const tone = call.result === "WON" ? "won" : call.result === "LOST" ? "lost" : "void";
  const word = call.result === "WON" ? "Winning" : call.result === "LOST" ? "Losing" : call.result === "PARTIAL" ? "Half back" : "Void";
  return (
    <span className={`status ${tone} called`} title={call.reason}>
      <span className="dot" />
      {word}
      {call.result === "LOST" ? null : <> · <PayoutNote payAt={call.pays_at} final={call.final} /></>}
    </span>
  );
}
