"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState, type ReactNode } from "react";
import useSWR from "swr";
import { MarketBlock } from "@/components/bits";
import { ChampionRow } from "@/components/ChampionGrid";
import { eventLabel, Matchup } from "@/components/EventCard";
import { FriendsPicks } from "@/components/FriendsPicks";
import { NotifyButton } from "@/components/GameAlerts";
import { ChoiceRow, H2HHead, H2HRow, LockedRow, WinnerCards } from "@/components/H2H";
import { IconBack, IconLock } from "@/components/icons";
import { LiveCard } from "@/components/LiveCard";
import { KillLine, LaneDuels } from "@/components/PropsBuilders";
import { countdown, kickoff, longDate } from "@/lib/format";
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

function windowText(g: GameT, event: EventT): string {
  if (g.window === "OPEN") return "Open";
  if (g.window === "UPCOMING") return g.index === 1 ? "Open" : "Later";
  if (g.window === "NOT_NEEDED") return "Not needed";
  if (g.window === "DONE") return g.winner ? `${g.winner === "A" ? event.team_a?.code : event.team_b?.code} won` : "Done";
  return g.state === "inProgress" ? "Live" : "Locked";
}

function Section({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <section className="mp-section">
      <div className="mp-head">
        <h2>{title}</h2>
        {sub ? <span className="muted">{sub}</span> : null}
      </div>
      {children}
    </section>
  );
}

const OBJECTIVES = ["first_blood", "first_tower", "baron_before"];
// Team races in the early window, opened when the game loads (D-025).
const RACES = ["five_kills", "gold_lead_15", "first_dragon"];

/** Everything about one game, head to head: winner, who gets picked, objectives, then lanes and kills. */
function GamePanel({ event, game, now }: { event: EventT; game: GameT; now: number }) {
  const markets = event.markets ?? [];
  const ofGame = (m: MarketT) => m.params.game_index === game.index;
  // A best-of-one has no separate game winner: the series winner is the game winner.
  const winner = markets.find((m) => m.kind === "game_winner" && ofGame(m)) ??
    (event.best_of === 1 ? markets.find((m) => m.kind === "series_winner") : undefined);

  if (game.window === "UPCOMING" && game.index > 1) {
    return (
      <div className="upcoming">
        <div style={{ fontWeight: 700 }}>Game {game.index} opens {game.opens_when ? game.opens_when.toLowerCase() : "later"}</div>
        <p className="muted" style={{ fontSize: 13, marginTop: 6, lineHeight: 1.5 }}>
          Winner and draft picks open between games. Lane duels and kill lines open after draft, until 3:00.
        </p>
        <NotifyButton event={event.id} game={game.index} label={eventLabel(event)} />
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
  const pregame = game.window === "OPEN" || (game.index === 1 && game.window === "UPCOMING");
  const objectives = OBJECTIVES.map((k) => markets.find((m) => m.kind === k && ofGame(m))).filter((m): m is MarketT => !!m && m.state === "OPEN");
  const early = game.early ?? "UPCOMING";
  const races = RACES.map((k) => markets.find((m) => m.kind === k && ofGame(m))).filter((m): m is MarketT => !!m && m.state === "OPEN");
  const name = (m: MarketT) => m.title.replace(`Game ${game.index} `, "").replace(/^./, (c) => c.toUpperCase());

  return (
    <>
      {winner ? (
        <section className="mp-section first">
          <div className="mp-head">
            <h2>{event.best_of === 1 ? "Who wins?" : `Game ${game.index} winner`}</h2>
            <span className="muted">
              {winner.state !== "OPEN"
                ? windowText(game, event)
                : winner.params.through_draft && early !== "OPEN"
                  ? "Open until 3:00 of the game"
                  : `Locks in ${countdown(winner.close_at, now)}`}
            </span>
          </div>
          <WinnerCards event={event} market={winner} caption="Winner" />
          <Rules markets={[winner]} summary={`Settles on who wins Game ${game.index}; void if it isn't played.`} />
        </section>
      ) : null}

      <H2HHead event={event} />

      {pregame ? (
        <Section title="Who gets picked?" sub={`Game ${game.index} · either team`}>
          <ChampionRow event={event} game={game.index} />
        </Section>
      ) : null}

      {objectives.length ? (
        <Section title="Objectives" sub={`Game ${game.index}`}>
          {objectives.map((m) =>
            m.outcomes.every((o) => o.code === "A" || o.code === "B") ? (
              <H2HRow key={m.id} event={event} market={m} label={name(m)} />
            ) : (
              <ChoiceRow key={m.id} event={event} market={m} label={name(m)} />
            ),
          )}
          <Rules markets={objectives} summary="Settles from the game's live data; void if the game isn't played." />
        </Section>
      ) : null}

      <Section title="Lanes & kills" sub={early === "OPEN" ? "Open until 3:00" : undefined}>
        {early === "OPEN" ? (
          <>
            {races.map((m) => <H2HRow key={m.id} event={event} market={m} label={name(m)} />)}
            <div className="mp-sub">Kill line</div>
            <KillLine event={event} game={game.index} />
            <div className="mp-sub">Lane duels · gold at 15:00</div>
            <LaneDuels event={event} game={game.index} />
            <Rules markets={races} summary="Team races settle from the game's live data; void if the game isn't played." />
          </>
        ) : early === "UPCOMING" && game.window !== "DONE" ? (
          <>
            {/* Greyed out until the game loads, so the page shows what is coming. */}
            <p className="muted" style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
              <IconLock width={13} height={13} aria-hidden="true" /> Opens when the game loads, until 3:00.
            </p>
            {["First to 5 kills", "Gold lead at 15:00", "First dragon"].map((l) => (
              <LockedRow key={l} label={l} left={event.team_a?.code ?? "TBD"} right={event.team_b?.code ?? "TBD"} />
            ))}
            <div className="mp-sub">Kill line</div>
            <LockedRow label="Total kills" left="Under" right="Over" />
            <div className="mp-sub">Lane duels · gold at 15:00</div>
            <LaneDuels event={event} game={game.index} />
            <NotifyButton event={event.id} game={game.index} label={eventLabel(event)} />
          </>
        ) : (
          <p className="muted" style={{ fontSize: 13 }}>{game.window === "DONE" ? `Game ${game.index} is over.` : "Early-game picks are closed."}</p>
        )}
      </Section>
    </>
  );
}

/** The series as a whole (best-of-three and up): winner, exact score, games played. */
function SeriesPanel({ event }: { event: EventT }) {
  const markets = event.markets ?? [];
  const label = eventLabel(event);
  const winner = markets.find((m) => m.kind === "series_winner");
  const score = markets.find((m) => m.kind === "series_score");
  const props = markets.filter((m) => m.category === "PROPS" && m.params.game_index === undefined);
  // Scores are coded from the first team's side ("2-1"); a row pairs it with the mirror win ("1-2").
  const scoreRows = (score?.outcomes ?? [])
    .filter((o) => Number(o.code.split("-")[0]) > Number(o.code.split("-")[1]))
    .map((o) => ({ left: o, right: score!.outcomes.find((x) => x.code === o.code.split("-").reverse().join("-")), label: o.code.replace("-", "–") }));
  return (
    <>
      {winner ? (
        <section className="mp-section first">
          <div className="mp-head">
            <h2>Series winner</h2>
            <span className="muted">Bo{event.best_of}</span>
          </div>
          <WinnerCards event={event} market={winner} caption="Series winner" />
          <Rules markets={[winner, score]} summary="Settles on the official series result; void if it isn't completed." />
        </section>
      ) : null}
      <H2HHead event={event} />
      {score ? (
        <Section title="Exact score">
          {scoreRows.map((r) => (
            <H2HRow key={r.label} event={event} market={score} label={r.label} left={r.left} right={r.right} />
          ))}
        </Section>
      ) : null}
      {props.length ? (
        <Section title="Series props">
          {props.map((m) => <MarketBlock key={m.id} market={m} eventLabel={label} />)}
        </Section>
      ) : null}
      <p className="muted" style={{ fontSize: 13, marginTop: 12 }}>
        Pick a game above for its winner, draft, objectives and lanes.
      </p>
    </>
  );
}

export default function EventPage() {
  const { id } = useParams<{ id: string }>();
  const { data: event, error } = useSWR<EventT>(`/events/${id}`);
  const now = useNow();
  const [tab, setTab] = useState<number | null>(null);
  const touch = useRef<{ x: number; y: number } | null>(null);

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
  const winner = markets.find((m) => m.kind === "series_winner");
  const cd = winner?.close_at ? countdown(winner.close_at, now) : null;
  const gameList = event.best_of > 1 ? event.games ?? [] : [];
  // Default to the game that is open right now once the series itself has locked.
  const openGame = gameList.find((g) => g.window === "OPEN" && g.index > 1);
  const current = tab ?? (event.status === "LIVE" && openGame ? openGame.index : 0);
  const shownGame = event.best_of === 1 ? (event.games ?? [])[0] : gameList.find((g) => g.index === current);
  const priced = markets.length > 0 && event.team_a && event.team_b;
  // Phones: swipe left or right to move between Series and each game. Swipes that start on something
  // that scrolls sideways itself (the champion row, the kill-line slider) stay with it.
  const tabs = [0, ...gameList.map((g) => g.index)];
  function onTouchStart(e: React.TouchEvent) {
    const target = e.target as HTMLElement;
    touch.current = target.closest(".champ-row, input, .swiss-board") ? null : { x: e.touches[0].clientX, y: e.touches[0].clientY };
  }
  function onTouchEnd(e: React.TouchEvent) {
    const start = touch.current;
    touch.current = null;
    if (!start || tabs.length < 2) return;
    const dx = e.changedTouches[0].clientX - start.x;
    const dy = e.changedTouches[0].clientY - start.y;
    if (Math.abs(dx) < 60 || Math.abs(dx) < 1.5 * Math.abs(dy)) return;
    const at = tabs.indexOf(current);
    const next = tabs[Math.max(0, Math.min(tabs.length - 1, at + (dx < 0 ? 1 : -1)))];
    if (next !== current) {
      setTab(next);
      window.scrollTo({ top: 0 });
    }
  }

  return (
    <>
      <div className="mp-top">
        <Link href="/" className="link" style={{ display: "inline-flex", alignItems: "center", gap: 6, minHeight: 44 }}>
          <IconBack width={16} height={16} /> Today
        </Link>
        <span className="muted num" style={{ fontSize: 12 }}>
          {event.status === "LIVE" ? (openGame ? `Live · Game ${openGame.index} open` : "Live") : event.status === "COMPLETED" ? "Final" : cd ? null : "Locked"}
        </span>
      </div>
      <div className="eyebrow" style={{ marginTop: 4 }}>
        {event.stage} · Bo{event.best_of} · {longDate(event.local_date)} · <span className="num">{kickoff(event.scheduled_at)}</span>
      </div>
      {!priced || event.status !== "SCHEDULED" ? (
        <section className="scoreboard" aria-label="Match" style={{ marginTop: 10 }}>
          <Matchup event={event} large />
        </section>
      ) : null}

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

      <div onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
      {!priced ? (
        <div className="empty" style={{ marginTop: 12 }}>
          <h3>No prices yet</h3>
          <p>Prices open automatically once both teams are known and the model has a price.</p>
        </div>
      ) : shownGame ? (
        <GamePanel event={event} game={shownGame} now={now} />
      ) : (
        <SeriesPanel event={event} />
      )}
      </div>
      <FriendsPicks event={event} />
      <p className="fineprint" style={{ textAlign: "left", marginTop: 16 }}>
        Every pick is a single with its own price. Nothing is multiplied together.
      </p>
    </>
  );
}
