"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { MarketBlock } from "@/components/bits";
import { Choice } from "@/components/Choice";
import { ChampionGrid } from "@/components/ChampionGrid";
import { eventLabel, Matchup, SideButton } from "@/components/EventCard";
import { IconBack } from "@/components/icons";
import { LiveCard } from "@/components/LiveCard";
import { KillLine, LaneDuels, Objectives } from "@/components/PropsBuilders";
import { countdown, kickoff, longDate, odds as fmtOdds } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import type { EventT, GameT, MarketT } from "@/lib/types";

/** One plain sentence on how these settle; each market's full rules one tap away. */
function Rules({ markets, summary }: { markets: (MarketT | undefined)[]; summary: string }) {
  const ms = markets.filter(Boolean) as MarketT[];
  if (!ms.length) return null;
  return (
    <div className="rules">
      <p className="muted">{summary}</p>
      <details>
        <summary>Full rules</summary>
        {ms.map((m) => (
          <p key={m.id} style={{ marginTop: 6 }}>
            <b>{m.title}.</b> {m.rules}
          </p>
        ))}
      </details>
    </div>
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
  const a = winner?.outcomes.find((o) => o.code === "A");
  const b = winner?.outcomes.find((o) => o.code === "B");

  if (game.window === "UPCOMING" && game.index > 1) {
    return (
      <div className="upcoming">
        <div style={{ fontWeight: 700 }}>Game {game.index} opens {game.opens_when ? game.opens_when.toLowerCase() : "later"}</div>
        <p className="muted" style={{ fontSize: 13, marginTop: 6, lineHeight: 1.5 }}>
          Winner and draft picks open between games. Lane duels and kill lines open after draft, until 3:00 or first blood.
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
  const pregame = game.window === "OPEN" || (game.index === 1 && game.window === "UPCOMING");
  const objectives = (event.markets ?? []).filter((m) => ofGame(m) && m.category === "OBJECTIVES");
  const early = game.early ?? "UPCOMING";
  const later =
    early === "UPCOMING" && game.window !== "DONE"
      ? "Lane duels and the kill line open when the game loads, until 3:00 or first blood."
      : !pregame && early !== "OPEN"
        ? game.window === "DONE" ? `Game ${game.index} is over.` : `Game ${game.index} picks are closed.`
        : null;
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
          <Rules markets={[winner]} summary={`Settles on who wins Game ${game.index}; void if it isn't played.`} />
        </section>
      ) : null}
      {/* Only the builders that take picks right now; the rest are one line saying when they open. */}
      <div style={{ marginTop: 8 }}>
        {pregame ? (
          <Builder title="Draft" sub={`Any champion in Game ${game.index} · picked, or by team`}>
            <ChampionGrid event={event} game={game.index} />
          </Builder>
        ) : null}
        {objectives.some((m) => m.state === "OPEN") ? (
          <Builder title="Objectives" sub="First blood, tower, dragon · Baron, soul">
            <Objectives event={event} game={game.index} />
            <Rules markets={objectives} summary="Settles from the game's live data; void if the game isn't played." />
          </Builder>
        ) : null}
        {early === "OPEN" ? (
          <>
            <Builder title="Lane duels" sub="Kills, CS at 15:00, damage · until 3:00 or first blood" open>
              <LaneDuels event={event} game={game.index} />
            </Builder>
            <Builder title="Kill line" sub="Total kills · until 3:00 or first blood">
              <KillLine event={event} game={game.index} />
            </Builder>
          </>
        ) : null}
        {later ? <p className="muted" style={{ fontSize: 13, marginTop: 10 }}>{later}</p> : null}
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
        <div className="gametabs" role="group" aria-label="Series and games">
          <button className="gametab" aria-pressed={current === 0} onClick={() => setTab(0)}>
            <span className="t">Series</span>
            <span className={`w ${winner?.state === "OPEN" ? "OPEN" : "LOCKED"}`}>{winner?.state === "OPEN" ? "Open" : "Locked"}</span>
          </button>
          {gameList.map((g) => (
            <button key={g.index} className="gametab" aria-pressed={current === g.index} onClick={() => setTab(g.index)}>
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
                        <span className="p num">{fmtOdds(o.odds)}</span>
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
                        {o.label.replace(" games", "")} <b className="num">{fmtOdds(o.odds)}</b>
                      </Choice>
                    ))}
                  </span>
                </div>
              ) : null}
              <Rules markets={[winner, score, games]} summary="Settles on the official series result; void if it isn't completed." />
            </section>
          ) : null}

          {event.best_of > 1 ? (
            <p className="muted" style={{ fontSize: 13, marginTop: 12 }}>
              Choose a game for its markets. Winner and draft picks close before play; duels and kill lines open once champions are confirmed.
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
