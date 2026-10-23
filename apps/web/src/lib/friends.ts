"use client";

import { useMemo } from "react";
import useSWR from "swr";
import type { FriendsOnMatch, Pick } from "./types";

/**
 * Friends on one match (A-010): their picks once each market locks, and before that only how many they have.
 * Every component on the page reads the same SWR key, so it is fetched once.
 */
export function useFriendsOnMatch(eventId: string | null | undefined) {
  const { data } = useSWR<FriendsOnMatch>(eventId ? `/events/${eventId}/league` : null, { refreshInterval: 30000 });
  const byOutcome = useMemo(() => {
    const map = new Map<string, Pick[]>();
    for (const p of data?.picks ?? []) map.set(p.outcome_id, [...(map.get(p.outcome_id) ?? []), p]);
    return map;
  }, [data]);
  return { picks: data?.picks ?? [], pending: data?.pending ?? [], byOutcome };
}

export const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";
