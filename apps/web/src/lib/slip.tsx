"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useSWRConfig } from "swr";
import { api, ApiError } from "./api";
import { rc } from "./format";
import type { MarketT, OutcomeT, Quote, Receipt } from "./types";

export type SlipLine = {
  outcomeId: string;
  marketId: string;
  marketTitle: string;
  outcomeLabel: string;
  eventLabel: string;
  odds: string;
  oddsVersion: number;
  stake: number | null;
  /** When its market stops taking picks, for the countdown on the line. */
  closeAt?: string;
  /** Through-draft and early-window markets close at 3:00 of game time, not at closeAt, once the game loads. */
  closesWithGame?: boolean;
  closeRule?: "game" | "draft" | null;
  /** Share of the full return paid for a right-side, wrong-exact result (Swiss record), if any. */
  consolation?: string;
};

/** The stake sizes offered everywhere; a custom amount stays one tap away on each pick. */
export const STAKES = [100, 250, 500, 1000];

/** A one-tap pick waiting out its undo window before it is placed. */
export type PendingPick = { line: SlipLine & { stake: number }; due: number };
export type QuickNotice = { tone: "success" | "info" | "error"; text: string };

const UNDO_MS = 5000;

type SlipCtx = {
  lines: SlipLine[];
  isSelected: (outcomeId: string) => boolean;
  /** Add or remove a pick. With one-tap picks on it is placed after a short undo window instead, unless `slip` is set. */
  toggle: (market: MarketT, outcome: OutcomeT, eventLabel: string, opts?: { slip?: boolean }) => void;
  remove: (outcomeId: string) => void;
  setStake: (outcomeId: string, stake: number | null) => void;
  setAllStakes: (fn: (line: SlipLine, index: number) => number | null) => void;
  updatePrices: (prices: { outcome_id: string; odds: string; odds_version: number }[]) => void;
  clear: () => void;
  sheetOpen: boolean;
  setSheetOpen: (open: boolean) => void;
  /** The stake every new pick starts with: the last amount chosen. */
  defaultStake: number;
  setDefaultStake: (stake: number) => void;
  quick: boolean;
  setQuick: (on: boolean) => void;
  pending: PendingPick[];
  undo: (outcomeId: string) => void;
  notice: QuickNotice | null;
  dismissNotice: () => void;
};

const Ctx = createContext<SlipCtx | null>(null);
const KEY = "rift.slip.v1";
const STAKE_KEY = "rift.stake.v1";
const QUICK_KEY = "rift.quick.v1";

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback; // an unsubmitted slip and preferences are conveniences only
  }
}
function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* ignore */
  }
}

function lineOf(market: MarketT, outcome: OutcomeT, eventLabel: string, stake: number | null): SlipLine {
  return {
    outcomeId: outcome.id,
    marketId: market.id,
    marketTitle: market.title,
    outcomeLabel: outcome.label,
    eventLabel,
    odds: outcome.odds!,
    oddsVersion: outcome.odds_version,
    stake,
    closeAt: market.close_at,
    closesWithGame: !!(market.params.through_draft || market.params.early),
    closeRule: market.close_rule ?? null,
    consolation: typeof market.params.consolation === "string" ? market.params.consolation : undefined,
  };
}

export function SlipProvider({ children }: { children: ReactNode }) {
  const { mutate } = useSWRConfig();
  const [lines, setLines] = useState<SlipLine[]>([]);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [defaultStake, setDefault] = useState(STAKES[0]);
  const [quick, setQuickState] = useState(false);
  const [pending, setPending] = useState<PendingPick[]>([]);
  const [notice, setNotice] = useState<QuickNotice | null>(null);
  // Saving waits for the first load: otherwise the empty starting slip is written over the saved one
  // (React runs mount effects twice in development, so a load can land after that save).
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLines(load<SlipLine[]>(KEY, []));
    const s = load<number>(STAKE_KEY, STAKES[0]);
    setDefault(Number.isInteger(s) && s > 0 ? s : STAKES[0]);
    setQuickState(load<boolean>(QUICK_KEY, false) === true);
    setLoaded(true);
  }, []);
  useEffect(() => {
    if (loaded) save(KEY, lines);
  }, [lines, loaded]);

  const setDefaultStake = useCallback((stake: number) => {
    if (!Number.isInteger(stake) || stake <= 0) return;
    setDefault(stake);
    save(STAKE_KEY, stake);
  }, []);
  const setQuick = useCallback((on: boolean) => {
    setQuickState(on);
    save(QUICK_KEY, on);
  }, []);

  // Move a pick into the slip, replacing any sibling from the same market.
  const addLine = useCallback((line: SlipLine) => {
    setLines((prev) => {
      const sibling = prev.find((l) => l.marketId === line.marketId);
      if (sibling) return prev.map((l) => (l.marketId === line.marketId ? { ...line, stake: line.stake ?? sibling.stake } : l));
      return [...prev, line];
    });
  }, []);

  const toggle = useCallback(
    (market: MarketT, outcome: OutcomeT, eventLabel: string, opts?: { slip?: boolean }) => {
      if (!outcome.odds) return;
      if (pending.some((p) => p.line.outcomeId === outcome.id)) {
        setPending((p) => p.filter((x) => x.line.outcomeId !== outcome.id));
        return;
      }
      if (lines.some((l) => l.outcomeId === outcome.id)) {
        setLines((prev) => prev.filter((l) => l.outcomeId !== outcome.id));
        return;
      }
      if (quick && !opts?.slip) {
        const line = { ...lineOf(market, outcome, eventLabel, defaultStake), stake: defaultStake };
        setNotice(null);
        setPending((p) => [...p.filter((x) => x.line.marketId !== market.id), { line, due: Date.now() + UNDO_MS }]);
        return;
      }
      addLine(lineOf(market, outcome, eventLabel, defaultStake));
    },
    [pending, lines, quick, defaultStake, addLine],
  );

  // A one-tap pick is quoted and placed as its own ticket. Anything unexpected sends it to the slip to review.
  const placeNow = useCallback(
    async (p: PendingPick) => {
      const { line } = p;
      const toSlip = (text: string, odds?: { odds: string; odds_version: number }) => {
        addLine(odds ? { ...line, odds: odds.odds, oddsVersion: odds.odds_version } : line);
        setNotice({ tone: "info", text });
      };
      let quote: Quote;
      try {
        quote = await api<Quote>("/quotes", { method: "POST", json: { items: [{ outcome_id: line.outcomeId, stake_rc: line.stake }] } });
      } catch (e) {
        return toSlip(`${line.outcomeLabel} is in your slip: ${e instanceof ApiError ? e.message : "couldn't get a price."}`);
      }
      const item = quote.items[0];
      if (!item || item.odds !== line.odds) {
        return toSlip(`The price on ${line.outcomeLabel} moved. It's in your slip to review.`, item);
      }
      const key = crypto.randomUUID();
      const placed = (r: Receipt) => {
        setNotice({ tone: "success", text: `Placed ${rc(r.total_stake_rc)} RC on ${line.outcomeLabel}.` });
        mutate((k) => typeof k === "string");
      };
      try {
        placed(
          await api<Receipt>("/tickets", {
            method: "POST",
            headers: { "Idempotency-Key": key },
            json: { quote_id: quote.quote_id, confirm_odds_versions: { [item.outcome_id]: item.odds_version } },
          }),
        );
      } catch (e) {
        if (e instanceof ApiError && (e.code === "NETWORK" || e.status >= 500)) {
          try {
            return placed(await api<Receipt>(`/tickets/by-key/${encodeURIComponent(key)}`));
          } catch (lookup) {
            if (!(lookup instanceof ApiError && lookup.status === 404)) {
              return setNotice({ tone: "error", text: `Couldn't confirm ${line.outcomeLabel}. Check My Picks before trying again.` });
            }
          }
        }
        toSlip(`${line.outcomeLabel} wasn't placed${e instanceof ApiError ? `: ${e.message}` : "."} It's in your slip.`);
      }
    },
    [addLine, mutate],
  );

  useEffect(() => {
    if (!pending.length) return;
    const next = Math.min(...pending.map((p) => p.due));
    const t = setTimeout(() => {
      const now = Date.now();
      const due = pending.filter((p) => p.due <= now);
      setPending((cur) => cur.filter((p) => p.due > now));
      due.forEach((p) => void placeNow(p));
    }, Math.max(0, next - Date.now()));
    return () => clearTimeout(t);
  }, [pending, placeNow]);

  const value = useMemo<SlipCtx>(
    () => ({
      lines,
      isSelected: (id) => lines.some((l) => l.outcomeId === id) || pending.some((p) => p.line.outcomeId === id),
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
      defaultStake,
      setDefaultStake,
      quick,
      setQuick,
      pending,
      undo: (id) => setPending((p) => p.filter((x) => x.line.outcomeId !== id)),
      notice,
      dismissNotice: () => setNotice(null),
    }),
    [lines, pending, toggle, sheetOpen, defaultStake, setDefaultStake, quick, setQuick, notice],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSlip(): SlipCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSlip outside SlipProvider");
  return ctx;
}
