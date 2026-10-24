"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { api, ApiError } from "@/lib/api";
import { rc } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useToast } from "@/lib/toasts";
import type { Pick } from "@/lib/types";

/** Whether a pick can still be taken back: yours, open, and its market not locked yet (D-038). */
export const cancellable = (p: Pick, now: number) =>
  p.status === "OPEN" && p.market_state === "OPEN" && (!p.close_at || Date.parse(p.close_at) > now) && !p.call;

/** Take a pick back before its market locks: tap Cancel, then confirm. The whole stake returns. */
export function CancelPick({ pick, compact }: { pick: Pick; compact?: boolean }) {
  const now = useNow(5000);
  const { mutate } = useSWRConfig();
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!cancellable(pick, now)) return null;

  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      await api(`/picks/${pick.id}/cancel`, { method: "POST" });
      toast({ tone: "money", badge: `+${rc(pick.stake_rc)}`, kicker: "Pick cancelled", text: `${pick.outcome_label}: ${rc(pick.stake_rc)} RC back` });
      mutate((k) => typeof k === "string");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't cancel that.");
      setConfirm(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className={`cancel-pick${compact ? " compact" : ""}`}>
      {confirm ? (
        <>
          <button type="button" className="cp-yes" disabled={busy} onClick={cancel}>
            {busy ? <span className="spinner" aria-hidden="true" /> : null}Cancel · {rc(pick.stake_rc)} RC back
          </button>
          <button type="button" className="cp-no" disabled={busy} onClick={() => setConfirm(false)}>Keep</button>
        </>
      ) : (
        <button type="button" className="cp-open" onClick={() => setConfirm(true)} aria-label={`Cancel your pick on ${pick.outcome_label}`}>
          Cancel
        </button>
      )}
      {error ? <span className="loss" style={{ fontSize: 12 }}>{error}</span> : null}
    </span>
  );
}
