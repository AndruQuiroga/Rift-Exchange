"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { api, ApiError } from "@/lib/api";
import { rc } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useToast } from "@/lib/toasts";
import type { Pick } from "@/lib/types";
import { IconClose } from "./icons";

/** What taking a pick back returns now, or null (D-038, D-040). The server decides; before it says (an older
 * response) only a still-open market counts, for the whole stake. */
export const refundOf = (p: Pick, now: number): number | null =>
  p.status !== "OPEN" || p.call ? null
    : p.cancel_refund_rc !== undefined ? p.cancel_refund_rc
    : p.market_state === "OPEN" && (!p.close_at || Date.parse(p.close_at) > now) ? p.stake_rc : null;
export const cancellable = (p: Pick, now: number) => refundOf(p, now) !== null;

/** Take a pick back: tap Cancel, then confirm. All of it before the draft starts, 75% after (until 3:00). */
export function CancelPick({ pick, compact }: { pick: Pick; compact?: boolean }) {
  const now = useNow(5000);
  const { mutate } = useSWRConfig();
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refundNow = refundOf(pick, now);
  if (refundNow === null) return null;
  const refund: number = refundNow;
  const partial = refund < pick.stake_rc;

  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      await api(`/picks/${pick.id}/cancel`, { method: "POST" });
      toast({ tone: "money", badge: `+${rc(refund)}`, kicker: "Pick cancelled", text: `${pick.outcome_label}: ${rc(refund)} RC back` });
      mutate((k) => typeof k === "string");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't cancel that.");
      setConfirm(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className={`cancel-pick${compact ? " compact" : ""}${confirm ? " confirming" : ""}`}>
      {confirm ? (
        <span className="cp-confirm" role="group" aria-label={`Cancel your bet on ${pick.outcome_label}?`}>
          <span className="cp-q">
            Cancel this bet? <b className="num">{partial ? `${rc(refund)} of ${rc(pick.stake_rc)} RC back` : `All ${rc(refund)} RC back`}</b>
            {partial ? <small>75% once the draft has started</small> : null}
          </span>
          <span className="cp-btns">
            <button type="button" className="cp-no" disabled={busy} onClick={() => setConfirm(false)}>Keep bet</button>
            <button type="button" className="cp-yes" disabled={busy} onClick={cancel}>
              {busy ? <span className="spinner" aria-hidden="true" /> : null}Cancel bet
            </button>
          </span>
        </span>
      ) : (
        <button type="button" className="cp-open" onClick={() => setConfirm(true)} aria-label={`Cancel your bet on ${pick.outcome_label}`}>
          <IconClose width={12} height={12} aria-hidden="true" />{compact ? "Cancel" : "Cancel bet"}
        </button>
      )}
      {error ? <span className="loss cp-err">{error}</span> : null}
    </span>
  );
}
