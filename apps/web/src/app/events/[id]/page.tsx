"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { MarketBlock } from "@/components/bits";
import { ChampionGrid } from "@/components/ChampionGrid";
import { eventLabel, Matchup, SideButton } from "@/components/EventCard";
import { IconBack } from "@/components/icons";
import { LiveCard } from "@/components/LiveCard";
import { countdown, kickoff, longDate, odds as fmtOdds } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import type { EventT, GameT, MarketT, OutcomeT } from "@/lib/types";

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

function Rules({ markets }: { markets: (MarketT | undefined)[] }) {
  const ms = markets.filter(Boolean) as MarketT[];
  if (!ms.length) return null;
  return (
    <details className="rules">
      <summary>How these settle</summary>
      {ms.map((m) => (
        <p key={m.id} style={{ marginTop: 6 }}>
          <b>{m.title}.</b> {m.rules}
        </p>
      ))}
    </details>
  );
}

function Builder({ title, sub, children, open }: { title: string; sub: string; children: React.ReactNode; open?: boolean }) {
  return (
    <details className="builder" open={open}>
      <summary>
        <span>
          <span className="t" style={{ display: "block" }}>{title}</span>
          <span className="s">{sub}</span>
        </span>
        <span className="chev" aria-hidden="true">›</span>
      </summary>
      <div className="body">{children}</div>
    </details>
  );
}

function windowText(g: GameT, event: EventT): string {
  if (g.window === "OPEN") return "Open";
  if (g.window === "UPCOMING") return g.index === 1 ? "Open" : "Later";
  if (g.window === "NOT_NEEDED") return "Not needed";
  if (g.window === "DONE") return g.winner ? `${g.winner === "A" ? event.team_a?.code : event.team_b?.code} won` : "Done";
  return g.state === "inProgress" ? "Live" : "Locked";
}

/** Everything about one game: its winner, its kill line, its draft. Opens when the previous game ends. */
function GamePanel({ event, game, now }: { event: EventT; game: GameT; now: number }) {
  const label = eventLabel(event);
  const ofGame = (m: MarketT) => m.params.game_index === game.index;
  const winner = (event.markets ?? []).find((m) => m.kind === "game_winner" && ofGame(m));
  const kills = (event.markets ?? []).find((m) => m.kind === "total_kills_game" && ofGame(m));
  const a = winner?.outcomes.find((o) => o.code === "A");
  const b = winner?.outcomes.find((o) => o.code === "B");

  if (game.window === "UPCOMING" && game.index > 1) {
    return (
      <div className="upcoming">
        <div style={{ fontWeight: 700 }}>Game {game.index} opens {game.opens_when ? game.opens_when.toLowerCase() : "later"}</div>
        <p className="muted" style={{ fontSize: 13, marginTop: 6, lineHeight: 1.5 }}>
          You get about 8 minutes before its draft: winner, kill line and any champion, with everything already played greyed out.
        </p>
      </div>
    );
  }
  if (game.window === "NOT_NEEDED") {
    return (
      <div className="upcoming">
        <div style={{ fontWeight: 700 }}>Game {game.index} wasn&apos;t needed</div>
        <p className="muted" style={{ fontSize: 13, marginTop: 6 }}>Any picks on it are void and refunded.</p>
      </div>
    );
  }
  const lock = game.closes_at ? countdown(game.closes_at, now) : null;
  return (
    <>
      {winner && a && b ? (
        <section className="card" style={{ marginTop: 12 }}>
          <div className="card-head">
            <h2>Game {game.index}</h2>
            <span className="sub">{game.window === "OPEN" && lock ? `Locks in ${lock}` : windowText(game, event)}</span>
          </div>
          <div className="mrow-sides">
            <SideButton market={winner} outcome={a} team={event.team_a} label={label} />
            <SideButton market={winner} outcome={b} team={event.team_b} label={label} right />
          </div>
          {kills ? (
            <div className="inline-q">
              <span>Total kills</span>
              <span className="opts">
                {kills.outcomes.map((o) => (
                  <Choice key={o.id} market={kills} outcome={o} label={label} className="mini">
                    {o.label} <b className="num">{fmtOdds(o.odds)}×</b>
                  </Choice>
                ))}
              </span>
            </div>
          ) : null}
          <Rules markets={[winner, kills]} />
        </section>
      ) : null}
      <div style={{ marginTop: 8 }}>
        <Builder title="Draft" sub={`Any champion in Game ${game.index} · picked, or by team`}>
          <ChampionGrid event={event} game={game.index} />
        </Builder>
      </div>
    </>
  );
}

export default function EventPage() {
  const { id } = useParams<{ id: string }>();
  const { data: event, error } = useSWR<EventT>(`/events/${id}`);
  const now = useNow();
  const [tab, setTab] = useState<number | null>(null);

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
  const props = markets.filter((m) => m.category === "PROPS" && m.params.game_index === undefined);
  const lockAt = winner?.close_at;
  const cd = lockAt ? countdown(lockAt, now) : null;
  const a = winner?.outcomes.find((o) => o.code === "A");
  const b = winner?.outcomes.find((o) => o.code === "B");
  const gameList = event.best_of > 1 ? event.games ?? [] : [];
  // Default to the game that is open right now once the series itself has locked.
  const openGame = gameList.find((g) => g.window === "OPEN" && g.index > 1);
  const current = tab ?? (event.status === "LIVE" && openGame ? openGame.index : 0);
  const shownGame = gameList.find((g) => g.index === current);

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
            ? openGame
              ? `Live — Game ${openGame.index} picks are open now.`
              : "Live — series picks are closed."
            : event.status === "COMPLETED"
              ? "Final."
              : cd
                ? `Locks in ${cd}, or as soon as the match goes live.`
                : "Predictions are locked."}
        </div>
      </section>

      <LiveCard event={event} />

      {gameList.length ? (
        <div className="gametabs" role="tablist" aria-label="Series and games">
          <button role="tab" className="gametab" aria-selected={current === 0} onClick={() => setTab(0)}>
            <span className="t">Series</span>
            <span className={`w ${winner?.state === "OPEN" ? "OPEN" : "LOCKED"}`}>{winner?.state === "OPEN" ? "Open" : "Locked"}</span>
          </button>
          {gameList.map((g) => (
            <button key={g.index} role="tab" className="gametab" aria-selected={current === g.index} onClick={() => setTab(g.index)}>
              <span className="t">Game {g.index}</span>
              <span className={`w ${g.index === 1 && g.window === "UPCOMING" ? "OPEN" : g.window}`}>{windowText(g, event)}</span>
            </button>
          ))}
        </div>
      ) : null}

      {markets.length === 0 ? (
        <div className="empty" style={{ marginTop: 12 }}>
          <h3>No prices yet</h3>
          <p>Prices open automatically once both teams are known and the model has a price.</p>
        </div>
      ) : shownGame ? (
        <GamePanel event={event} game={shownGame} now={now} />
      ) : (
        <>
          {winner && a && b ? (
            <section className="card" aria-labelledby="result-h" style={{ marginTop: 12 }}>
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
              <Rules markets={[winner, score, games]} />
            </section>
          ) : null}

          {event.best_of > 1 ? (
            <p className="muted" style={{ fontSize: 13, marginTop: 12 }}>
              Game winners, kill lines and the draft are under each game. Later games open as the one before ends.
            </p>
          ) : event.team_a && event.team_b ? (
            <>
              {(event.games ?? [])[0] ? <GamePanel event={event} game={(event.games ?? [])[0]} now={now} /> : (
                <div style={{ marginTop: 8 }}>
                  <Builder title="Draft" sub="Any champion · picked, or by team">
                    <ChampionGrid event={event} game={1} />
                  </Builder>
                </div>
              )}
            </>
          ) : null}

          {props.length ? (
            <div style={{ marginTop: 8 }}>
              <Builder title="Game props" sub={`Kills and other in-game lines · ${props.length} open`}>
                {props.map((m) => (
                  <MarketBlock key={m.id} market={m} eventLabel={label} />
                ))}
              </Builder>
            </div>
          ) : null}
        </>
      )}
      <p className="fineprint" style={{ textAlign: "left", marginTop: 16 }}>
        Every pick is a single with its own price. Nothing is multiplied together.
      </p>
    </>
  );
}
