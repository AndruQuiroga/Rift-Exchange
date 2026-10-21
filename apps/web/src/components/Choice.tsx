"use client";

import type { ReactNode } from "react";
import { oddsSpoken } from "@/lib/format";
import { usePlaced } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import type { MarketT, OutcomeT } from "@/lib/types";

/** A compact priced choice (scoreline, games played, yes/no) that feeds the slip like any other price. */
export function Choice({ market, outcome, label, className, children }: { market: MarketT; outcome: OutcomeT; label: string; className: string; children: ReactNode }) {
  const slip = useSlip();
  const selected = slip.isSelected(outcome.id);
  const placed = usePlaced().has(outcome.id);
  const won = market.result && !market.result.void && market.result.winning_codes.includes(outcome.code);
  const open = market.state === "OPEN" && outcome.odds !== null;
  return (
    <button
      type="button"
      className={`${className}${won ? " won" : ""}`}
      aria-pressed={selected}
      data-placed={placed || undefined}
      disabled={!open && !selected}
      onClick={() => slip.toggle(market, outcome, label)}
      aria-label={`${market.title}: ${outcome.label}, ${oddsSpoken(outcome.odds)}${selected ? ", in slip" : ""}${placed ? ", already placed" : ""}`}
    >
      {children}
    </button>
  );
}
