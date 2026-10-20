"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { MarketBlock } from "@/components/bits";
import { eventLabel, Matchup, SideButton } from "@/components/EventCard";
import { IconBack } from "@/components/icons";
import { countdown, kickoff, longDate, odds as fmtOdds } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import type { EventT, MarketT, OutcomeT } from "@/lib/types";

/** A compact priced choice (scoreline, games played, yes/no) that feeds the slip like any other price. */
function Choice({ market, outcome, label, className, children }: { market: MarketT; outcome: OutcomeT; label: string; className: string; children: React.ReactNode }) {
  const slip = useSlip();
  const selected = slip.isSelected(outcome.id);
  const won = market.result && !market.result.void && market.result.winning_codes.includes(outcome.code);
  const open = market.state === "OPEN" && outcome.odds !== null;
  return (
    <button
      type="button"
      className={`${className}${won ? " won" : ""}`}
      aria-pressed={selected}
      disabled={!open && !selected}
      onClick={() => slip.toggle(market, outcome, label)}
      aria-label={`${market.title}: ${outcome.label}, ${fmtOdds(outcome.odds)} times${selected ? ", in slip" : ""}`}
    >
      {children}
    </button>
  );
}

const BUILDERS: Record<string, { title: string; sub: string }> = {
  DRAFT: { title: "Draft", sub: "Which champions get played" },
  PROPS: { title: "Game props", sub: "Kills and other in-game lines" },
};

export default function EventPage() {
  const { id } = useParams<{ id: string }>();
  const { data: event, error } = useSWR<EventT>(`/events/${id}`);
  const now = useNow();

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
  const label = eventLabel(event);
  const byKind = (k: string) => markets.find((m) => m.kind === k);
  const winner = byKind("series_winner");
  const score = byKind("series_score");
  const games = byKind("total_games");
  const game1 = markets.find((m) => m.kind === "game_winner" && m.params.game_index === 1);
  const lockAt = winner?.close_at;
  const cd = lockAt ? countdown(lockAt, now) : null;
  const a = winner?.outcomes.find((o) => o.code === "A");
  const b = winner?.outcomes.find((o) => o.code === "B");
  const groups = Object.entries(BUILDERS)
    .map(([cat, copy]) => ({ cat, ...copy, markets: markets.filter((m) => m.category === cat) }))
    .filter((g) => g.markets.length);

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
                ? `Locks in ${cd}, or as soon as the match goes live.`
                : "Predictions are locked."}
        </div>
      </section>

      {markets.length === 0 ? (
        <div className="empty">
          <h3>No prices yet</h3>
          <p>Prices open automatically once both teams are known and the model has a price.</p>
        </div>
      ) : (
        <>
          {winner && a && b ? (
            <section className="card" aria-labelledby="result-h">
              <div className="card-head">
                <h2 id="result-h">Result</h2>
                <span className="sub">{score ? "Winner, or call the exact score" : "Who wins"}</span>
              </div>
              <div className="mrow-sides">
                <SideButton market={winner} outcome={a} team={event.team_a} label={label} />
                <SideButton market={winner} outcome={b} team={event.team_b} label={label} right />
              </div>
              {score ? (
                <div className={`scorelines${score.outcomes.length > 4 ? " six" : ""}`}>
                  {score.outcomes.map((o) => {
                    const cut = o.label.lastIndexOf(" ");
                    return (
                      <Choice key={o.id} market={score} outcome={o} label={label} className="sl">
                        <span className="t">{o.label.slice(0, cut)}</span>
                        <span className="s num">{o.label.slice(cut + 1)}</span>
                        <span className="p num">{fmtOdds(o.odds)}×</span>
                      </Choice>
                    );
                  })}
                </div>
              ) : null}
              {games ? (
                <div className="inline-q">
                  <span>Games played</span>
                  <span className="opts">
                    {games.outcomes.map((o) => (
                      <Choice key={o.id} market={games} outcome={o} label={label} className="mini">
                        {o.label.replace(" games", "")} <b className="num">{fmtOdds(o.odds)}×</b>
                      </Choice>
                    ))}
                  </span>
                </div>
              ) : null}
              {game1 ? (
                <div className="inline-q">
                  <span>Game 1 winner</span>
                  <span className="opts">
                    {game1.outcomes.map((o) => (
                      <Choice key={o.id} market={game1} outcome={o} label={label} className="mini">
                        {o.code === "A" ? event.team_a?.code : event.team_b?.code} <b className="num">{fmtOdds(o.odds)}×</b>
                      </Choice>
                    ))}
                  </span>
                </div>
              ) : null}
              <details className="rules">
                <summary>How these settle</summary>
                {[winner, score, games, game1].filter(Boolean).map((m) => (
                  <p key={m!.id} style={{ marginTop: 6 }}>
                    <b>{m!.title}.</b> {m!.rules}
                  </p>
                ))}
              </details>
            </section>
          ) : null}

          {groups.length ? (
            <div className="section">
              {groups.map((g) => (
                <details className="builder" key={g.cat}>
                  <summary>
                    <span>
                      <span className="t" style={{ display: "block" }}>{g.title}</span>
                      <span className="s">{g.sub} · {g.markets.length} open</span>
                    </span>
                    <span className="chev" aria-hidden="true">›</span>
                  </summary>
                  <div className="body">
                    {g.markets.map((m) => (
                      <MarketBlock key={m.id} market={m} eventLabel={label} />
                    ))}
                    <p className="fineprint" style={{ textAlign: "left" }}>
                      Experimental odds from pick rates and kill totals seen at this Worlds so far.
                    </p>
                  </div>
                </details>
              ))}
            </div>
          ) : null}
          <p className="fineprint" style={{ textAlign: "left", marginTop: 16 }}>
            Every pick is a single with its own price. Nothing is multiplied together.
          </p>
        </>
      )}
    </>
  );
}
