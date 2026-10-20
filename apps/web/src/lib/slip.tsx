"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { MarketT, OutcomeT } from "./types";

export type SlipLine = {
  outcomeId: string;
  marketId: string;
  marketTitle: string;
  outcomeLabel: string;
  eventLabel: string;
  odds: string;
  oddsVersion: number;
  stake: number | null;
};

type SlipCtx = {
  lines: SlipLine[];
  isSelected: (outcomeId: string) => boolean;
  toggle: (market: MarketT, outcome: OutcomeT, eventLabel: string) => void;
  remove: (outcomeId: string) => void;
  setStake: (outcomeId: string, stake: number | null) => void;
  setAllStakes: (fn: (line: SlipLine, index: number) => number | null) => void;
  updatePrices: (prices: { outcome_id: string; odds: string; odds_version: number }[]) => void;
  clear: () => void;
  sheetOpen: boolean;
  setSheetOpen: (open: boolean) => void;
};

const Ctx = createContext<SlipCtx | null>(null);
const KEY = "rift.slip.v1";

export function SlipProvider({ children }: { children: ReactNode }) {
  const [lines, setLines] = useState<SlipLine[]>([]);
  const [sheetOpen, setSheetOpen] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) setLines(JSON.parse(raw));
    } catch {
      /* unsubmitted slip is a convenience only */
    }
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(lines));
    } catch {
      /* ignore */
    }
  }, [lines]);

  const toggle = useCallback((market: MarketT, outcome: OutcomeT, eventLabel: string) => {
    if (!outcome.odds) return;
    setLines((prev) => {
      if (prev.some((l) => l.outcomeId === outcome.id)) return prev.filter((l) => l.outcomeId !== outcome.id);
      const line: SlipLine = {
        outcomeId: outcome.id,
        marketId: market.id,
        marketTitle: market.title,
        outcomeLabel: outcome.label,
        eventLabel,
        odds: outcome.odds!,
        oddsVersion: outcome.odds_version,
        stake: null,
      };
      // One outcome per market on a slip: tapping a sibling replaces the earlier choice, keeping its stake.
      const sibling = prev.find((l) => l.marketId === market.id);
      if (sibling) return prev.map((l) => (l.marketId === market.id ? { ...line, stake: sibling.stake } : l));
      return [...prev, line];
    });
  }, []);

  const value = useMemo<SlipCtx>(
    () => ({
      lines,
      isSelected: (id) => lines.some((l) => l.outcomeId === id),
      toggle,
      remove: (id) => setLines((p) => p.filter((l) => l.outcomeId !== id)),
      setStake: (id, stake) => setLines((p) => p.map((l) => (l.outcomeId === id ? { ...l, stake } : l))),
      setAllStakes: (fn) => setLines((p) => p.map((l, i) => ({ ...l, stake: fn(l, i) }))),
      updatePrices: (prices) =>
        setLines((p) =>
          p.map((l) => {
            const n = prices.find((x) => x.outcome_id === l.outcomeId);
            return n ? { ...l, odds: n.odds, oddsVersion: n.odds_version } : l;
          }),
        ),
      clear: () => setLines([]),
      sheetOpen,
      setSheetOpen,
    }),
    [lines, toggle, sheetOpen],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSlip(): SlipCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSlip outside SlipProvider");
  return ctx;
}
