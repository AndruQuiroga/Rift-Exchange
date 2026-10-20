"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { MarketBlock } from "@/components/bits";
import { eventLabel, Matchup } from "@/components/EventCard";
import { IconBack } from "@/components/icons";
import { countdown, kickoff, longDate } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import type { EventT } from "@/lib/types";

const TABS = [
  { key: "WINNER", label: "Results" },
  { key: "DRAFT", label: "Draft" },
  { key: "PROPS", label: "Game props" },
] as const;

export default function EventPage() {
  const { id } = useParams<{ id: string }>();
  const { data: event, error } = useSWR<EventT>(`/events/${id}`);
  const now = useNow();
  const [tab, setTab] = useState<string>("WINNER");

  if (error) {
    return (
      <div className="empty" style={{ marginTop: 24 }}>
        <h3>Match not found</h3>
        <p>
          <Link className="link" href="/">Back to today</Link>
        </p>
      </div>
    );
  }
  if (!event) return <div className="skeleton" style={{ marginTop: 24, height: 320 }} />;

  const markets = event.markets ?? [];
  const tabs = TABS.filter((t) => markets.some((m) => m.category === t.key));
  const current = tabs.some((t) => t.key === tab) ? tab : tabs[0]?.key;
  const lockAt = markets.find((m) => m.kind === "series_winner")?.close_at;
  const cd = lockAt ? countdown(lockAt, now) : null;

  return (
    <>
      <div style={{ paddingTop: 14 }}>
        <Link href="/" className="link" style={{ display: "inline-flex", alignItems: "center", gap: 6, minHeight: 44 }}>
          <IconBack width={16} height={16} /> Today
        </Link>
      </div>
      <section className="scoreboard" aria-label="Match">
        <div className="eyebrow" style={{ marginBottom: 14 }}>
          {event.stage} · Bo{event.best_of} · {longDate(event.local_date)} · <span className="num">{kickoff(event.scheduled_at)}</span>
        </div>
        <Matchup event={event} large />
        <div style={{ marginTop: 14, fontSize: 14 }} className="muted">
          {event.status === "LIVE"
            ? "Live now — predictions are closed for this series."
            : event.status === "COMPLETED"
              ? "Final."
              : cd
                ? `Predictions lock in ${cd}, at the scheduled start.`
                : "Predictions are locked."}
        </div>
      </section>

      {tabs.length > 1 ? (
        <div className="chips" role="tablist" aria-label="Market categories" style={{ marginBottom: 6 }}>
          {tabs.map((t) => (
            <button key={t.key} role="tab" className="chip" aria-selected={t.key === current} onClick={() => setTab(t.key)}>
              {t.label} <span className="count num">{markets.filter((m) => m.category === t.key).length}</span>
            </button>
          ))}
        </div>
      ) : null}

      {markets.length === 0 ? (
        <div className="empty">
          <h3>No markets yet</h3>
          <p>Markets open automatically once both teams are known and the model has a price.</p>
        </div>
      ) : (
        <div className="event" style={{ padding: "0 14px" }}>
          {markets
            .filter((m) => m.category === current)
            .map((m) => (
              <MarketBlock key={m.id} market={m} eventLabel={eventLabel(event)} />
            ))}
        </div>
      )}
      {current === "DRAFT" || current === "PROPS" ? (
        <p className="fineprint" style={{ textAlign: "left" }}>
          Draft and game-prop odds are experimental: they use pick rates and kill totals observed at this Worlds so far.
        </p>
      ) : null}
    </>
  );
}
