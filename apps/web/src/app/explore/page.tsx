"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import useSWR from "swr";
import { MarketBlock } from "@/components/bits";
import { EventCard } from "@/components/EventCard";
import { useNow, useSeason } from "@/lib/hooks";
import type { EventT, MarketT } from "@/lib/types";

export default function ExplorePage() {
  return (
    <Suspense>
      <Explore />
    </Suspense>
  );
}

function Explore() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = params.get("tab") === "FUTURES" ? "FUTURES" : "MATCHES";
  const [query, setQuery] = useState("");
  const now = useNow();
  const { data: season } = useSeason();
  const { data: futures } = useSWR<{ markets: MarketT[] }>("/markets?category=FUTURES");
  const { data: all } = useSWR<{ events: EventT[] }>("/events");

  const upcoming = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (all?.events ?? [])
      .filter((e) => e.local_date >= (season?.first_match_day ?? ""))
      .filter((e) => e.status !== "COMPLETED" && e.team_a && e.team_b)
      .filter((e) => !q || [e.team_a, e.team_b].some((t) => t && (t.code.toLowerCase().includes(q) || t.name.toLowerCase().includes(q))));
  }, [all, query, season]);

  const winner = futures?.markets.find((m) => m.kind === "tournament_winner");
  const board = (futures?.markets ?? []).filter((m) => m.kind === "swiss_record");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Explore</h1>
          <p>Every open market, by match or by tournament.</p>
        </div>
      </div>
      <div className="segmented" role="group" aria-label="Explore">
        {(["MATCHES", "FUTURES"] as const).map((t) => (
          <button key={t} aria-pressed={tab === t} onClick={() => router.replace(t === "FUTURES" ? "/explore?tab=FUTURES" : "/explore")}>
            {t === "MATCHES" ? "Upcoming matches" : "Futures"}
          </button>
        ))}
      </div>

      {tab === "MATCHES" ? (
        <section className="section">
          <div className="field" style={{ marginTop: 0, marginBottom: 14 }}>
            <label htmlFor="q">Find a team</label>
            <input id="q" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="T1, Gen.G, G2…" autoComplete="off" />
          </div>
          {upcoming.length ? (
            upcoming.map((e) => <EventCard key={e.id} event={e} now={now} />)
          ) : (
            <div className="empty">
              <h3>No upcoming matchups{query ? " for that team" : ""}</h3>
              <p>New Swiss rounds appear here as soon as each draw is published.</p>
            </div>
          )}
        </section>
      ) : (
        <section className="section">
          {winner ? (
            <div className="event" style={{ padding: "0 14px" }}>
              <MarketBlock market={winner} eventLabel="Worlds 2026" />
            </div>
          ) : null}
          {board.length ? (
            <Link className="banner" href="/swiss" style={{ marginTop: 14 }}>
              <span>
                <span className="t" style={{ display: "block" }}>Record calls</span>
                <span className="s">{board.some((m) => m.state === "OPEN") ? "Free to play · call each team's Swiss record" : "Locked · see how your calls are doing"}</span>
              </span>
              <span className="go">Open →</span>
            </Link>
          ) : null}
          {!winner && !board.length ? (
            <div className="empty">
              <h3>Futures not priced yet</h3>
              <p>They open once the Swiss field is set.</p>
            </div>
          ) : null}
        </section>
      )}
    </>
  );
}
