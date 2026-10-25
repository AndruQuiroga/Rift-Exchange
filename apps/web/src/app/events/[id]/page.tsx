"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import useSWR from "swr";
import { MarketBlock } from "@/components/bits";
import { eventLabel, Matchup } from "@/components/EventCard";
import { NotifyButton } from "@/components/GameAlerts";
import { ChoiceRow, H2HHead, H2HRow, LockedRow, WinnerCards } from "@/components/H2H";
import { IconBack, IconLock } from "@/components/icons";
import { Decided, decided, Group, InPlay, inPlay, LiveHero, MatchSummary, OpenAside, openNow, useLive, YourGame } from "@/components/MatchLive";
import { PostGame } from "@/components/PostGame";
import { KillLine, LaneDuels } from "@/components/PropsBuilders";
import { DeciderToasts, ResultsSoFar } from "@/components/Results";
import { RivalsPanel, RivalToasts } from "@/components/Rivals";
import { LockTimer } from "@/components/Timing";
import { countdown, kickoff, longDate } from "@/lib/format";
import { useNow, usePlaced } from "@/lib/hooks";
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

function Section({ title, sub, children }: { title: string; sub?: ReactNode; children: ReactNode }) {
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

/** OPEN (with its countdown) or LOCKED: every section says whether you can pick right now. */
function Open({ at, label }: { at?: string | null; label?: string }) {
  return (
    <span className="state-badges">
      <span className="state-open"><span className="dot" aria-hidden="true" />OPEN</span>
      {label ? <span className="muted">{label}</span> : at ? <LockTimer at={at} compact /> : null}
    </span>
  );
}
const Locked = ({ label }: { label?: string }) => (
  <span className="state-badges"><span className="state-locked"><IconLock width={10} height={10} aria-hidden="true" />LOCKED</span>{label ? <span className="muted">{label}</span> : null}</span>
);

type LanePhase = NonNullable<GameT["lanes"]>;
const phaseOf = (game: GameT): LanePhase =>
  game.lanes ?? (game.early === "OPEN" ? "LIVE" : game.early === "UPCOMING" ? "BLIND" : "CLOSED");

/** The same badge on every section of a game (D-040): which window is open, its price, and when it closes. */
function PhaseBadge({ phase, closeAt }: { phase: LanePhase; closeAt?: string | null }) {
  if (phase === "BLIND") return <Open label="Blind · full odds · closes when the draft starts" />;
  if (phase === "LIVE") {
    return (
      <span className="state-badges">
        <span className="state-open"><span className="dot" aria-hidden="true" />OPEN</span>
        <span className="muted">After draft · lower odds</span>
        {closeAt ? <LockTimer at={closeAt} compact /> : <span className="muted">until 3:00</span>}
      </span>
    );
  }
  if (phase === "DRAFT") return <Locked label="Drafting · reopens at game start" />;
  if (phase === "UPCOMING") return <Locked label="Opens when the previous game starts" />;
  return <Locked label="Closed at 3:00" />;
}

/** The three windows every game market goes through, with the one you are in lit (D-040). */
function PhaseStrip({ phase }: { phase: LanePhase }) {
  const steps: { id: LanePhase; t: string; s: string }[] = [
    { id: "BLIND", t: "Blind", s: "Full odds, before the draft" },
    { id: "DRAFT", t: "Draft", s: "Locked" },
    { id: "LIVE", t: "Game start → 3:00", s: "Lower odds, champions known" },
  ];
  return (
    <div className="phase-strip" role="group" aria-label="Betting windows for this game">
      <ol>
        {steps.map((st) => (
          <li key={st.id} className={st.id === phase ? "now" : undefined} aria-current={st.id === phase ? "step" : undefined}>
            <b>{st.t}</b>
            <span>{st.s}</span>
          </li>
        ))}
      </ol>
      <p>One bet per market, blind or after the draft. Cancel until 3:00: all back before the draft, 75% after it starts.</p>
    </div>
  );
}

const OBJECTIVE_ROWS: [string, string][] = [
  ["first_blood", "First blood"], ["first_tower", "First tower"], ["first_dragon", "First dragon"],
  ["soul_team", "Dragon soul"], ["first_baron", "First Baron"], ["baron_before", "Baron before 25:00"],
  ["game_length", "Game length"],
];
const LANE_ROWS: [string, string][] = [["five_kills", "First to 5 kills"], ["gold_lead_15", "Gold lead at 15:00"]];

/** A market's blind and after-draft copies in one game (D-040), and the one its row shows in this window. */
function pairOf(markets: MarketT[], game: number, kind: string, phase: LanePhase) {
  const of = markets.filter((m) => m.kind === kind && m.params.game_index === game);
  const blind = of.find((m) => m.params.blind);
  const live = of.find((m) => m.params.early);
  const shown = phase === "LIVE" || phase === "CLOSED" ? live ?? blind : blind ?? live;
  return { blind, live, shown };
}

/** One market, one row, whichever window it is in. Not priced yet: greyed out, so the page still says it's coming. */
function TimelineRow({ event, game, kind, label, phase }: { event: EventT; game: number; kind: string; label: string; phase: LanePhase }) {
  const { blind, live, shown } = pairOf(event.markets ?? [], game, kind, phase);
  if (!shown) {
    const [l, r] = kind === "baron_before" ? ["Yes", "No"] : kind === "game_length" ? ["Over", "Under"]
      : [event.team_a?.code ?? "TBD", event.team_b?.code ?? "TBD"];
    return <LockedRow label={label} left={l} right={r} />;
  }
  const behind = shown === live ? blind : undefined;
  if (shown.outcomes.every((o) => o.code === "A" || o.code === "B" || o.code === "NONE")) {
    return <H2HRow event={event} market={shown} label={label} blind={behind} />;
  }
  const line = kind === "game_length" ? shown.outcomes[0]?.label.replace(/^Over /, "") : null;
  return <ChoiceRow event={event} market={shown} label={line ? `${label} · ${line}` : label} blind={behind}
    short={(o) => (kind === "game_length" ? o.label.split(" ")[0] : o.label)} />;
}

/** Objectives and Lanes & kills for one game: the phase strip, then every market once, in its current window. */
function GameMarkets({ event, game }: { event: EventT; game: GameT }) {
  const phase = phaseOf(game);
  const markets = event.markets ?? [];
  const liveClose = markets.filter((m) => m.params.game_index === game.index && m.params.early && m.state === "OPEN")
    .map((m) => m.close_at).sort()[0];
  const badge = <PhaseBadge phase={phase} closeAt={phase === "LIVE" ? liveClose : null} />;
  const shown = [...OBJECTIVE_ROWS, ...LANE_ROWS].map(([k]) => pairOf(markets, game.index, k, phase).shown)
    .filter((m): m is MarketT => !!m);
  if (phase === "CLOSED" || game.window === "DONE") {
    return (
      <Section title="Objectives, lanes & kills" sub={<Locked label={game.window === "DONE" ? `Game ${game.index} is over` : "Closed at 3:00"} />}>
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>Your picks are in play; results land as the game decides them.</p>
      </Section>
    );
  }
  return (
    <>
      <PhaseStrip phase={phase} />
      <Section title="Objectives" sub={badge}>
        {OBJECTIVE_ROWS.map(([k, l]) => <TimelineRow key={k} event={event} game={game.index} kind={k} label={l} phase={phase} />)}
      </Section>
      <Section title="Lanes & kills" sub={badge}>
        {LANE_ROWS.map(([k, l]) => <TimelineRow key={k} event={event} game={game.index} kind={k} label={l} phase={phase} />)}
        <div className="mp-sub">Kill line</div>
        <KillLine event={event} game={game.index} />
        <div className="mp-sub">Lane duels · gold at 15:00</div>
        <LaneDuels event={event} game={game.index} />
        {phase === "BLIND" || phase === "UPCOMING" ? <NotifyButton event={event.id} game={game.index} label={eventLabel(event)} /> : null}
      </Section>
      <Rules markets={shown} summary="Settles from the game's live data; void if the game isn't played." />
    </>
  );
}

/** What is closed now but coming back for this game, so a live page is never blank between windows. */
const upNext = (game: GameT) => game.lanes === "DRAFT" || (game.window === "UPCOMING" && game.index > 1);

function UpNext({ event, game }: { event: EventT; game: GameT }) {
  if (game.window === "UPCOMING" && game.index > 1) {
    return (
      <p className="muted" style={{ fontSize: 14, margin: 0 }}>
        Game {game.index} opens when Game {game.index - 1} starts: its winner and blind picks at full odds until its
        draft starts, then everything again at lower odds from game start to 3:00. If the series ends first, its picks are refunded.
      </p>
    );
  }
  return <GameMarkets event={event} game={game} />;
}

/** Everything about one game, head to head. live: only what is open right now (a live match's Open now). */
function GamePanel({ event, game, live = false }: { event: EventT; game: GameT; live?: boolean }) {
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
          Its winner and blind picks open at full odds as soon as Game {game.index - 1} starts, and close when its own
          draft starts. Objectives, lanes and kills reopen at lower odds from game start to 3:00. If the series ends
          before it, its picks are refunded.
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
  const phase = phaseOf(game);
  const winnerOpen = winner?.state === "OPEN";
  const marketsOpen = phase === "BLIND" || phase === "LIVE";
  if (live && !winnerOpen && !marketsOpen) return null;

  return (
    <>
      {live ? null : <ResultsSoFar event={event} game={game.index} />}
      {winner && (!live || winnerOpen) ? (
        <section className="mp-section first">
          <div className="mp-head">
            <h2>{event.best_of === 1 ? "Who wins?" : `Game ${game.index} winner`}</h2>
            {winner.state !== "OPEN"
              ? <Locked label={windowText(game, event)} />
              : <Open label="Closes when the draft starts" />}
          </div>
          <WinnerCards event={event} market={winner} caption="Winner" />
          <Rules markets={[winner]} summary={`Settles on who wins Game ${game.index}; void if it isn't played.`} />
        </section>
      ) : null}

      <H2HHead event={event} />
      {live && !marketsOpen ? null : <GameMarkets event={event} game={game} />}
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
  // Live: poll as well as listen, so results and calls land within seconds of the data.
  const { data: event, error } = useSWR<EventT>(`/events/${id}`, {
    refreshInterval: (latest) => (latest?.status === "LIVE" ? 10000 : 0),
  });
  const now = useNow();
  const [tab, setTab] = useState<number | null>(null);
  const touch = useRef<{ x: number; y: number } | null>(null);
  const { data: live } = useLive(event ?? ({ status: "SCHEDULED" } as EventT));
  const hidden = useHideScore();
  const placed = usePlaced();

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
  // Default to the game that is open right now once the series itself has locked, unless one is being played
  // (D-043: the next game opens while the current one runs; its tab says Open).
  const openGame = gameList.find((g) => g.window === "OPEN" && g.index > 1);
  const playing = gameList.some((g) => g.state === "inProgress");
  const current = tab ?? (event.status === "LIVE" && openGame && !playing ? openGame.index : 0);
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

  const isLive = event.status === "LIVE";
  const isFinal = event.status === "COMPLETED";
  const liveView = isLive && !!priced;
  const opened = openNow(event, now);
  const gameTabs = gameList.length ? (
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
      ) : null;
  const panels = (
    <>
      <div onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
        {!priced ? (
          <div className="empty" style={{ marginTop: 12 }}>
            <h3>No prices yet</h3>
            <p>Prices open automatically once both teams are known and the model has a price.</p>
          </div>
        ) : shownGame ? (
          <GamePanel event={event} game={shownGame} live={liveView} />
        ) : (
          <SeriesPanel event={event} />
        )}
      </div>
    </>
  );

  return (
    // Rivals appear once the match starts; before that the page is the markets alone, full width.
    <div className={`match-layout${liveView || isFinal ? " is-live" : ""}${event.status === "SCHEDULED" ? " no-rivals" : ""}`}>
      <div className="m-hero">
        <div className="mp-top">
          <Link href="/" className="link" style={{ display: "inline-flex", alignItems: "center", gap: 6, minHeight: 44 }}>
            <IconBack width={16} height={16} /> Today
          </Link>
          <span className="muted num" style={{ fontSize: 12 }}>
            {isFinal ? "Final" : event.status === "LIVE" ? "Live" : cd ? null : "Locked"}
          </span>
        </div>
        <div className="eyebrow" style={{ marginTop: 4 }}>
          {event.stage} · Bo{event.best_of} · {longDate(event.local_date)} · <span className="num">{kickoff(event.scheduled_at)}</span>
        </div>
        {isFinal ? (
          <PostGame event={event} />
        ) : isLive ? (
          <LiveHero event={event} live={live} hidden={hidden.on && !hidden.peek} onReveal={hidden.reveal} />
        ) : !priced ? (
          <section className="scoreboard" aria-label="Match" style={{ marginTop: 10 }}>
            <Matchup event={event} large />
          </section>
        ) : null}
        {isLive ? (
          <div className="hero-row">
            <YourGame live={live} />
            <button type="button" className="link-btn" aria-pressed={hidden.on} onClick={hidden.toggle}>{hidden.on ? "Score hidden" : "Hide score"}</button>
          </div>
        ) : null}
      </div>

      {event.status === "SCHEDULED" ? null : <aside className="m-rivals"><RivalsPanel event={event} /></aside>}

      <div className="m-markets">
        {gameTabs}
        {liveView ? (
          <>
            <MatchSummary event={event} live={live} game={shownGame ?? null} />
            <Group id="open" tone="open" title="Open now" count={opened.count} aside={<OpenAside event={event} />}
              empty="Nothing to pick right now. Results land below as they happen.">
              {panels}
            </Group>
            {shownGame && upNext(shownGame) ? (
              <Group id="next" tone="next" title="Up next" count={1}>
                <UpNext event={event} game={shownGame} />
              </Group>
            ) : null}
            <Group id="inplay" tone="play" title="In play" count={inPlay(live).length} empty="None of your picks are waiting on the game.">
              <InPlay event={event} live={live} />
            </Group>
            <Group id="decided" tone="done" title="Decided" count={decided(event, shownGame ?? null).length} empty="Nothing decided yet.">
              <Decided event={event} game={shownGame ?? null} placed={placed} />
            </Group>
          </>
        ) : panels}
        <p className="fineprint" style={{ textAlign: "left", marginTop: 16 }}>
          Every pick is a single with its own price. Nothing is multiplied together.
        </p>
      </div>
      <DeciderToasts event={event} />
      <RivalToasts event={event} />
    </div>
  );
}

/** "Hide score" for anyone watching on delay: remembered on this device, off by default. */
function useHideScore() {
  const [on, setOn] = useState(false);
  const [peek, setPeek] = useState(false);
  useEffect(() => {
    try {
      setOn(localStorage.getItem("rift.hideLiveScore") === "1");
    } catch {}
  }, []);
  return {
    on, peek,
    reveal: () => setPeek(true),
    toggle: () => {
      setOn(!on);
      setPeek(false);
      try {
        localStorage.setItem("rift.hideLiveScore", on ? "0" : "1");
      } catch {}
    },
  };
}
