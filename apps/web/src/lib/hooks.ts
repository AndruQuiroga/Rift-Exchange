"use client";

import { useEffect, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { fetcher } from "./api";
import type { Me, SeasonT } from "./types";

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
    for (const type of [
      "wallet.changed",
      "ticket.accepted",
      "market.odds_updated",
      "market.locked",
      "selection.settled",
      "leaderboard.changed",
      "event.updated",
    ]) {
      es.addEventListener(type, refresh);
    }
    return () => {
      es.close();
      if (timer) clearTimeout(timer);
    };
  }, [enabled, mutate]);
}
