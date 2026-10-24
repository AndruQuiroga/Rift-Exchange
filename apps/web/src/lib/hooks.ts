"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { fetcher } from "./api";
import type { Me, Pick, SeasonT } from "./types";

export function useMe() {
  return useSWR<Me>("/me", fetcher, { shouldRetryOnError: false });
}

export function useSeason() {
  return useSWR<SeasonT>("/season/current", fetcher);
}

export function useNow(intervalMs = 30000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

/** SSE events are invalidation hints only: refetch canonical data over REST (docs/spec/09 §SSE). */
export function useLiveUpdates(enabled: boolean) {
  const { mutate } = useSWRConfig();
  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const es = new EventSource("/api/v1/stream");
    let timer: ReturnType<typeof setTimeout> | null = null;
    const refresh = () => {
      if (timer) return;
      timer = setTimeout(() => {
        timer = null;
        mutate((key) => typeof key === "string" && key !== "/season/current");
      }, 400);
    };
    // Also re-broadcast each event on window ("rift:sse"), so toasts can react without a second connection.
    const relay = (e: MessageEvent) => {
      refresh();
      try {
        window.dispatchEvent(new CustomEvent("rift:sse", { detail: JSON.parse(e.data) }));
      } catch {}
    };
    for (const type of [
      "wallet.changed",
      "ticket.accepted",
      "market.odds_updated",
      "market.locked",
      "selection.settled",
      "leaderboard.changed",
      "event.updated",
      "reaction.created",
    ]) {
      es.addEventListener(type, relay as EventListener);
    }
    return () => {
      es.close();
      if (timer) clearTimeout(timer);
    };
  }, [enabled, mutate]);
}

/** Outcomes you already hold an open pick on (outcome id -> RC staked), to mark them on every builder. */
/** Every open bet on one outcome taken together: you can add to a pick, and each top-up keeps its own odds. */
export type Holding = { stake: number; ret: number; picks: Pick[] };
/** The blended price of a holding: what it returns per RC staked. */
export const blended = (h: Holding) =>
  h.picks.length === 1 && h.ret === h.picks[0].potential_return_rc ? h.picks[0].odds : h.stake ? (h.ret / h.stake).toFixed(2) : "0";

export function useHoldings(): Map<string, Holding> {
  const { data } = useSWR<{ picks: Pick[] }>("/me/picks?state=open", fetcher);
  return useMemo(() => {
    const out = new Map<string, Holding>();
    for (const p of data?.picks ?? []) {
      const h = out.get(p.outcome_id) ?? { stake: 0, ret: 0, picks: [] };
      out.set(p.outcome_id, { stake: h.stake + p.stake_rc, ret: h.ret + p.potential_return_rc, picks: [...h.picks, p] });
    }
    return out;
  }, [data]);
}

export function usePlaced(): Map<string, number> {
  const { data } = useSWR<{ picks: Pick[] }>("/me/picks?state=open", fetcher);
  return useMemo(() => {
    const out = new Map<string, number>();
    for (const p of data?.picks ?? []) out.set(p.outcome_id, (out.get(p.outcome_id) ?? 0) + p.stake_rc);
    return out;
  }, [data]);
}
