"use client";

import { useEffect, useRef } from "react";
import { rc } from "@/lib/format";
import { initialsOf, useToast } from "@/lib/toasts";

type Sse = { type: string; entity_id: string; payload?: Record<string, unknown> };

/** Site-wide toasts from your own live events: a friend reacting to your pick, and payouts, rolled up so a
 * match settling eight picks at once is one toast, not eight. */
export function SiteToasts() {
  const toast = useToast();
  const batch = useRef<{ back: number; staked: number; n: number; timer: ReturnType<typeof setTimeout> | null }>({ back: 0, staked: 0, n: 0, timer: null });

  useEffect(() => {
    const flush = () => {
      const b = batch.current;
      if (b.n && b.back > 0) {
        const net = b.back - b.staked;
        toast({
          tone: net >= 0 ? "good" : "money", badge: `+${rc(b.back)}`, kicker: `${b.n} pick${b.n === 1 ? "" : "s"} settled`,
          text: `${rc(b.back)} RC landed${net !== 0 ? ` (${net > 0 ? "+" : "−"}${rc(Math.abs(net))} net)` : ""}`,
          action: { label: "Picks", href: "/picks" },
        });
      }
      batch.current = { back: 0, staked: 0, n: 0, timer: null };
    };
    const on = (e: Event) => {
      const ev = (e as CustomEvent<Sse>).detail;
      const p = ev.payload ?? {};
      if (ev.type === "reaction.created") {
        const from = String(p.from ?? "A friend");
        toast({
          key: `reaction:${ev.entity_id}:${p.text}`, tone: "info", badge: initialsOf(from), badgeRound: true,
          kicker: `${from} reacted`, text: `"${p.text}" on your ${p.pick ?? "pick"}`,
        });
      }
      if (ev.type === "selection.settled" && typeof p.return_rc === "number") {
        const b = batch.current;
        b.back += p.return_rc as number;
        b.staked += typeof p.stake_rc === "number" ? (p.stake_rc as number) : 0;
        b.n += 1;
        if (b.timer) clearTimeout(b.timer);
        b.timer = setTimeout(flush, 1500);
      }
    };
    window.addEventListener("rift:sse", on);
    return () => {
      window.removeEventListener("rift:sse", on);
      if (batch.current.timer) clearTimeout(batch.current.timer);
    };
  }, [toast]);
  return null;
}
