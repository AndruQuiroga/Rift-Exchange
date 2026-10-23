"use client";

import { useEffect } from "react";
import { rc } from "@/lib/format";
import { initialsOf, useToast } from "@/lib/toasts";

type Sse = { type: string; entity_id: string; payload?: Record<string, unknown> };

/** Site-wide toasts from your own live events: a friend reacting to your pick, a pick paying out. */
export function SiteToasts() {
  const toast = useToast();
  useEffect(() => {
    const on = (e: Event) => {
      const ev = (e as CustomEvent<Sse>).detail;
      const p = ev.payload ?? {};
      if (ev.type === "reaction.created") {
        const from = String(p.from ?? "A friend");
        toast({
          key: `reaction:${ev.entity_id}:${p.text}`, tone: "info", badge: initialsOf(from), badgeRound: true,
          kicker: "Reaction", text: `${from}: "${p.text}" on your ${p.pick ?? "pick"}`,
          action: p.event_id ? { label: "See", href: `/events/${p.event_id}` } : undefined,
        });
      }
      if (ev.type === "selection.settled" && typeof p.return_rc === "number") {
        const back = p.return_rc as number;
        const stake = typeof p.stake_rc === "number" ? (p.stake_rc as number) : 0;
        const result = String(p.result);
        toast({
          key: `settled:${ev.entity_id}:${p.revision}`,
          tone: result === "WON" ? "good" : result === "LOST" ? "rival" : "money",
          badge: back > 0 ? `+${rc(back)}` : "0",
          kicker: result === "WON" ? "Paid out" : result === "PARTIAL" ? "Half back" : result === "VOID" ? "Refunded" : "Settled",
          text: `${p.outcome ?? "Your pick"} · ${p.title ?? ""}${result === "LOST" ? ` · −${rc(stake)} RC` : ""}`,
          action: { label: "Picks", href: "/picks" },
        });
      }
    };
    window.addEventListener("rift:sse", on);
    return () => window.removeEventListener("rift:sse", on);
  }, [toast]);
  return null;
}
