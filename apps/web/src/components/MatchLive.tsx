"use client";

import { useRef, useState, type ReactNode } from "react";
import useSWR from "swr";
import { odds as fmtOdds, rc } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { teamColor } from "@/lib/teams";
import type { EventT, GameT, LiveEvent, LiveT, MarketT, Pick } from "@/lib/types";
import { TeamMark } from "./bits";
import { EventIcon, IconBaron, IconDragon, IconTower } from "./GameIcons";
import { clockText, LockTimer, MarketClose, PayoutNote } from "./Timing";

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const EVENT_LABEL: Record<LiveEvent["type"], string> = {
  first_blood: "First blood", first_tower: "First tower", dragon: "Dragon", baron: "Baron", inhibitor: "Inhibitor",
};

export function useLive(event: EventT) {
  return useSWR<LiveT>(event.status === "SCHEDULED" ? null : `/events/${event.id}/live`, {
    refreshInterval: (latest) => (latest?.status === "COMPLETED" ? 60000 : 5000),
  });
}

/** What can be picked right now on this match: open markets, plus duels and kill lines in their windows. */
export function openNow(event: EventT, now: number): { count: number; closes: string | null; provisional: boolean; draft: boolean; next: boolean } {
  const open = (event.markets ?? []).filter((m) => m.state === "OPEN" && Date.parse(m.close_at) > now);
  const lanes = (event.games ?? []).some((g) => g.lanes === "BLIND" || g.lanes === "LIVE");
  const known = open.filter((m) => m.close_known !== false).map((m) => m.close_at).sort();
  return { count: open.length + (lanes ? 1 : 0), closes: known[0] ?? null, provisional: open.some((m) => m.close_known === false),
           draft: open.some((m) => m.close_rule === "draft"), next: open.some((m) => m.close_rule === "next") };
}

/** The game clock, ticking between polls: the last reported time plus what has passed since it arrived. */
function useTickingClock(live: LiveT | undefined): number | null {
  const now = useNow(1000);
  const arrived = useRef<{ at: number; key: string | null }>({ at: Date.now(), key: null });
  const key = live?.as_of ?? null;
  if (arrived.current.key !== key) arrived.current = { at: Date.now(), key };
  if (live?.game_clock_s == null) return null;
  const running = live.game_state === "in_game";
  const drift = running ? Math.min(60, Math.max(0, Math.floor((now - arrived.current.at) / 1000))) : 0;
  return live.game_clock_s + drift;
}

/** Events on a track, the newest on its own line (replaced as the next arrives); hover or tap for all. */
function EventTimeline({ event, events, clockS }: { event: EventT; events: LiveEvent[]; clockS: number }) {
  const [open, setOpen] = useState(false);
  if (!events.length) return null;
  const end = Math.max(clockS, ...events.map((e) => e.at_s), 60);
  const color = (t: "A" | "B" | null) => (t === "A" ? teamColor(event.team_a) : t === "B" ? teamColor(event.team_b) : "#87919c");
  const code = (t: "A" | "B" | null) => (t === "A" ? event.team_a?.code : t === "B" ? event.team_b?.code : "—");
  const latest = events[events.length - 1];
  return (
    <div className={`lh-events${open ? " open" : ""}`}>
      <div className="lh-track" aria-hidden="true">
        <span className="lh-now" style={{ left: `${(clockS / end) * 100}%` }} />
        {events.map((e, i) => (
          <span key={i} className="lh-dot" style={{ left: `${(e.at_s / end) * 100}%`, background: color(e.team) }}
            title={`${clock(e.at_s)} · ${EVENT_LABEL[e.type]}${e.detail ? ` ${e.detail}` : ""} · ${code(e.team)}`} />
        ))}
      </div>
      <button type="button" className="lh-latest" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span key={`${latest.type}:${latest.at_s}`} className="lh-latest-in">
          <EventIcon type={latest.type} detail={latest.detail} />
          <span className="num">{clock(latest.at_s)}</span> {EVENT_LABEL[latest.type]}{latest.detail ? ` ${latest.detail}` : ""} · <b>{code(latest.team)}</b>
        </span>
        {events.length > 1 ? <span className="lh-more">+{events.length - 1}</span> : null}
      </button>
      <ol className="lh-evlist">
        {[...events].reverse().map((e, i) => (
          <li key={i}>
            <EventIcon type={e.type} detail={e.detail} />
            <span className="num">{clock(e.at_s)}</span>
            <span>{EVENT_LABEL[e.type]}{e.detail ? ` ${e.detail}` : ""}</span>
            <b style={{ color: color(e.team) }}>{code(e.team)}</b>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** The scoreboard: each team's half in its colour with its own objectives, the clock between, gold as a tug of war. */
export function LiveHero({ event, live, hidden, onReveal }: { event: EventT; live: LiveT | undefined; hidden: boolean; onReveal: () => void }) {
  const clockS = useTickingClock(live);
  const kills = live?.kills ?? [0, 0];
  // The game is over the moment its last frame or result is in, before the series is officially closed.
  const current = (event.games ?? []).find((g) => g.index === live?.game_index);
  const over = live?.game_state === "finished" || current?.window === "DONE" || !!current?.ended_at;
  const winnerSide = over ? current?.winner ?? null : null;
  const lead = live?.gold ? live.gold[0] - live.gold[1] : 0;
  const share = live?.gold ? Math.max(8, Math.min(92, 50 + (lead / 12000) * 50)) : 50;
  const barons = (side: "A" | "B") => (live?.events ?? []).filter((e) => e.type === "baron" && e.team === side).length;
  const half = (side: "A" | "B") => {
    const i = side === "A" ? 0 : 1;
    const team = side === "A" ? event.team_a : event.team_b;
    const dragons = live?.dragons?.[i] ?? [];
    return (
      <div className={`lh-half ${side === "B" ? "right" : ""}${winnerSide === side ? " won" : winnerSide ? " lost" : ""}`} style={{ "--team": teamColor(team) } as React.CSSProperties}>
        <div className="lh-team"><TeamMark team={team} /><span className="lh-code">{team?.code ?? "TBD"}</span>{winnerSide === side ? <span className="lh-win">WIN</span> : null}</div>
        <span className="lh-big num">{hidden ? "–" : kills[i]}</span>
        {hidden ? <span className="lh-objs" /> : (
          <span className="lh-objs" aria-label={`${live?.towers?.[i] ?? 0} towers, ${dragons.length} dragons, ${barons(side)} barons`}>
            <span className="lh-obj"><IconTower /> {live?.towers?.[i] ?? 0}</span>
            <span className="lh-obj">{dragons.length ? dragons.map((d, k) => <IconDragon key={k} type={d} />) : <><IconDragon type={null} className="dim" /> 0</>}</span>
            {barons(side) ? <span className="lh-obj"><IconBaron /> {barons(side)}</span> : null}
          </span>
        )}
      </div>
    );
  };
  return (
    <section className="live-hero" aria-label="Scoreboard">
      <div className="lh-top">
        {half("A")}
        <div className="lh-mid">
          {over ? <span className="lh-over-pill">GAME OVER</span> : <span className="lh-live"><span className="dot" />LIVE</span>}
          <span className="lh-clock num">{hidden || clockS == null ? "··" : clock(clockS)}</span>
          <span className="lh-game">{live?.game_index ? `Game ${live.game_index}` : "Between games"}</span>
        </div>
        {half("B")}
      </div>
      {over && !hidden && winnerSide ? (
        <div className="lh-over reveal">{winnerSide === "A" ? event.team_a?.code : event.team_b?.code} win Game {live?.game_index}
          {event.best_of > 1 ? <span className="muted"> · series {event.score[0]}–{event.score[1]}</span> : null}</div>
      ) : null}
      {hidden ? (
        <button type="button" className="lh-spoiler" onClick={onReveal}>Score hidden for anyone watching on delay. <b>Tap to show</b></button>
      ) : live?.gold ? (
        <div className="lh-bottom">
          <div className="lh-tugrow">
            <span className={`lh-lead${lead > 0 ? " on" : ""}`}>{lead > 0 ? `+${(lead / 1000).toFixed(1)}k` : ""}</span>
            <div className="lh-tug" aria-label={lead === 0 ? "Gold even" : `${lead > 0 ? event.team_a?.code : event.team_b?.code} ahead by ${rc(Math.abs(lead))} gold`}
              style={{ "--a": teamColor(event.team_a), "--b": teamColor(event.team_b) } as React.CSSProperties}>
              <span style={{ width: `${share}%` }} />
            </div>
            <span className={`lh-lead right${lead < 0 ? " on" : ""}`}>{lead < 0 ? `+${(-lead / 1000).toFixed(1)}k` : ""}</span>
          </div>
          <EventTimeline event={event} events={live.events} clockS={clockS ?? 0} />
        </div>
      ) : null}
    </section>
  );
}

/** How your picks on this match stand right now, in one line. */
export function YourGame({ live }: { live: LiveT | undefined }) {
  const picks = live?.my_picks ?? [];
  if (!picks.length) return null;
  let back = 0, decided = 0, riding = 0, ridingReturn = 0;
  for (const p of picks) {
    const r = p.status !== "OPEN" ? p.status : p.call?.result;
    if (!r) {
      riding += p.stake_rc;
      ridingReturn += p.potential_return_rc;
      continue;
    }
    decided += p.stake_rc;
    if (r === "WON") back += p.status === "OPEN" ? p.potential_return_rc : p.return_rc;
    else if (r === "VOID") back += p.stake_rc;
    else if (r === "PARTIAL") back += p.status === "OPEN" ? Math.round(p.stake_rc / 2) : p.return_rc;
  }
  const net = back - decided;
  // If every pick still riding wins: what is back so far plus their full returns, minus everything staked.
  const potential = back + ridingReturn - decided - riding;
  return (
    <section className={`your-game${net < 0 ? " down" : ""}`} aria-label="Your game">
      <div>
        <span className="yg-k">Your {picks.length} pick{picks.length === 1 ? "" : "s"} · {rc(riding)} RC still riding</span>
        <span className="yg-v num">{net >= 0 ? "+" : "−"}{rc(Math.abs(net))} RC</span>
        <span className="yg-s">
          decided so far{riding ? <> · <b className="num">{potential >= 0 ? "up to +" : "at best −"}{rc(Math.abs(potential))} RC</b> if the rest win</> : null}
        </span>
      </div>
      <div className="yg-bars" aria-hidden="true">
        {picks.map((p) => {
          const r = p.status !== "OPEN" ? p.status : p.call?.result;
          return <span key={p.id} className={r === "WON" ? "w" : r === "LOST" ? "l" : r ? "m" : ""} />;
        })}
      </div>
    </section>
  );
}

const marketOf = (event: EventT, p: Pick) => (event.markets ?? []).find((m) => m.id === p.market_id);

/** Locked picks of yours the game is still deciding. */
export function inPlay(live: LiveT | undefined) {
  return (live?.my_picks ?? []).filter((p) => p.status === "OPEN" && !p.call && p.market_state !== "OPEN");
}

export function decided(event: EventT, game: GameT | null) {
  return (event.markets ?? []).filter((m) =>
    (m.result || m.call) && (!game || m.params.game_index === game.index || (event.best_of === 1 && m.params.game_index === undefined)));
}

/** The three states of a live match as one row you can jump from: open, in play, decided. */
export function MatchSummary({ event, live, game }: { event: EventT; live: LiveT | undefined; game: GameT | null }) {
  const now = useNow(1000);
  const o = openNow(event, now);
  const items = [
    { id: "open", label: "Open now", n: o.count, tone: "open" },
    { id: "inplay", label: "In play", n: inPlay(live).length, tone: "play" },
    { id: "decided", label: "Decided", n: decided(event, game).length, tone: "done" },
  ];
  return (
    <nav className="msum" aria-label="On this match">
      {items.map((it) => (
        <a key={it.id} href={`#${it.id}`} className={`msum-i ${it.tone}${it.n ? "" : " zero"}`}>
          <span className="msum-n num">{it.n}</span>
          <span className="msum-l">{it.label}</span>
        </a>
      ))}
    </nav>
  );
}

/** A group of the page with one consistent header: what it is, how many, and when it changes. */
export function Group({ id, tone, title, count, aside, children, empty }: {
  id: string; tone: "open" | "next" | "play" | "done"; title: string; count: number; aside?: ReactNode; children: ReactNode; empty?: string;
}) {
  return (
    <section id={id} className={`group ${tone}`} aria-label={title}>
      <header className="group-h">
        <span className="group-t"><span className="group-dot" aria-hidden="true" />{title}<span className="group-n num">{count}</span></span>
        {aside}
      </header>
      {count ? children : <p className="group-empty">{empty}</p>}
    </section>
  );
}

export function OpenAside({ event }: { event: EventT }) {
  const now = useNow(1000);
  const o = openNow(event, now);
  if (!o.count) return null;
  if (o.draft) return <MarketClose at={null} rule="draft" scheduledAt={event.scheduled_at} />;
  if (o.closes === null && o.next) return <MarketClose at={null} rule="next" />;
  return o.closes ? <LockTimer at={o.closes} label="Closes in" /> : o.provisional ? <MarketClose at={null} known={false} /> : <span className="muted" style={{ fontSize: 12 }}>until 3:00</span>;
}

/** Your locked picks the game is still deciding, with how far along they are. */
export function InPlay({ event, live }: { event: EventT; live: LiveT | undefined }) {
  const picks = inPlay(live);
  const clockS = live?.game_clock_s ?? null;
  return (
    <div className="inplay">
      {picks.map((p) => {
        const kind = marketOf(event, p)?.kind ?? "";
        let pct: number | null = null, left = "", right = "";
        if ((kind === "lane_duel" || kind === "gold_lead_15") && clockS != null) {
          pct = Math.min(100, (clockS / 900) * 100);
          right = clockS < 900 ? `decides in ${clockText((900 - clockS) * 1000)}` : "15:00 reached";
        } else if (kind === "baron_before" && clockS != null) {
          pct = Math.min(100, (clockS / 1500) * 100);
          right = clockS < 1500 ? `${clockText((1500 - clockS) * 1000)} to go` : "25:00 reached";
          left = "No baron yet";
        } else if (p.live?.line && p.live.current != null) {
          pct = Math.min(100, (p.live.current / (Number(p.live.line) + 0.5)) * 100);
          left = `${p.live.current} kills so far`;
          right = `line ${p.live.line}`;
        }
        return (
          <div className="deciding" key={p.id}>
            <div className="dc-top">
              <b>{p.outcome_label}</b>
              <span className="dc-money num">{rc(p.stake_rc)} @ {fmtOdds(p.odds)} → <b className="win">{rc(p.potential_return_rc)}</b></span>
            </div>
            <span className="dc-mkt muted">{p.market_title}</span>
            {pct != null ? <div className="dc-bar"><span style={{ width: `${pct}%` }} /></div> : null}
            {left || right ? <div className="dc-foot muted"><span>{left}</span><span>{right}</span></div> : null}
          </div>
        );
      })}
    </div>
  );
}

/** Everything decided on this game: yours first, then the rest. */
export function Decided({ event, game, placed }: { event: EventT; game: GameT | null; placed: Map<string, number> }) {
  const rows = decided(event, game);
  const mine = (m: MarketT) => m.outcomes.some((o) => placed.has(o.id));
  return (
    <div className="decided">
      {[...rows.filter(mine), ...rows.filter((m) => !mine(m))].map((m) => <DecidedRow key={m.id} market={m} placed={placed} />)}
    </div>
  );
}

function DecidedRow({ market, placed }: { market: MarketT; placed: Map<string, number> }) {
  const r = market.result ?? market.call!;
  const winners = market.outcomes.filter((o) => r.winning_codes.includes(o.code)).map((o) => o.label).join(", ");
  const mine = market.outcomes.filter((o) => placed.has(o.id));
  const partial = market.call?.partial_codes ?? [];
  const verdict = !mine.length ? "none" : r.void ? "void" : mine.some((o) => r.winning_codes.includes(o.code)) ? "won"
    : mine.some((o) => partial.includes(o.code)) ? "half" : market.call?.pending_refund ? "pending" : "lost";
  const word = { none: "", void: "Void", won: "Won", half: "Half back", pending: "Ban check", lost: "Lost" }[verdict];
  const short = market.title.replace(/^Game \d+ /, "").replace(/ in Game \d+$/, "").replace(/^./, (c) => c.toUpperCase());
  const value = market.kind === "champion_picked" ? (r.winning_codes.includes("YES") ? "Yes" : "No") : r.void ? "Void" : partial.length && !winners ? "Tie" : winners || "—";
  return (
    <div className={`drow ${verdict} reveal`} title={market.call && !market.result ? market.call.reason : market.result?.reason}>
      <span className="drow-t">{short}</span>
      <span className="drow-v">{value}</span>
      {word ? (
        <span className="drow-you">
          {word}
          {!market.result && market.call && (verdict === "won" || verdict === "half") ? <> · <PayoutNote payAt={market.call.pays_at} final={market.call.final} /></> : null}
        </span>
      ) : <span className="drow-you none" />}
    </div>
  );
}
