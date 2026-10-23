"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { rc } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { teamColor } from "@/lib/teams";
import type { EventT, GameT, LiveEvent, LiveT, MarketT, Pick } from "@/lib/types";
import { TeamMark } from "./bits";
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

/** Watch: the game and what happened. Play: what you can pick right now. Remembered on this device. */
export function useLiveMode(): ["watch" | "play", (m: "watch" | "play") => void] {
  const [mode, setMode] = useState<"watch" | "play">("play");
  useEffect(() => {
    try {
      if (localStorage.getItem("rift.liveMode") === "watch") setMode("watch");
    } catch {}
  }, []);
  return [mode, (m) => {
    setMode(m);
    try {
      localStorage.setItem("rift.liveMode", m);
    } catch {}
  }];
}

/** What can be picked right now on this match: open markets, plus duels and kill lines in their windows. */
export function openNow(event: EventT, now: number): { count: number; closes: string | null; what: string[] } {
  const open = (event.markets ?? []).filter((m) => m.state === "OPEN" && Date.parse(m.close_at) > now);
  const what = new Set<string>();
  for (const m of open) what.add(m.category === "DRAFT" ? "draft calls" : m.kind.includes("winner") ? "winner" : m.category === "PLAYERS" ? "lane duels" : "props");
  const lanes = (event.games ?? []).some((g) => g.early === "OPEN" || (g.early === "UPCOMING" && g.window === "OPEN"));
  if (lanes) {
    what.add("lane duels");
    what.add("kill lines");
  }
  const closes = open.filter((m) => m.close_known !== false).map((m) => m.close_at).sort()[0] ?? null;
  return { count: open.length + (lanes ? 1 : 0), closes, what: [...what] };
}

export function ModeToggle({ mode, setMode, openCount }: { mode: "watch" | "play"; setMode: (m: "watch" | "play") => void; openCount: number }) {
  return (
    <div className="mode-toggle" role="group" aria-label="Live view">
      <button type="button" aria-pressed={mode === "watch"} onClick={() => setMode("watch")}>Watch</button>
      <button type="button" aria-pressed={mode === "play"} onClick={() => setMode("play")}>
        {openCount ? <span className="mt-dot" aria-hidden="true" /> : null}
        Play{openCount ? ` · ${openCount} open` : ""}
      </button>
    </div>
  );
}

/** The scoreboard: each team's half in its colour, kills big, the clock between, gold as a tug of war. */
export function LiveHero({ event, live, hidden, onReveal }: { event: EventT; live: LiveT | undefined; hidden: boolean; onReveal: () => void }) {
  const final = event.status === "COMPLETED";
  const kills = live?.kills ?? [0, 0];
  const lead = live?.gold ? live.gold[0] - live.gold[1] : 0;
  const share = live?.gold ? Math.max(8, Math.min(92, 50 + (lead / 12000) * 50)) : 50;
  const code = (t: "A" | "B" | null) => (t === "A" ? event.team_a?.code : t === "B" ? event.team_b?.code : "—");
  const half = (side: "A" | "B") => {
    const team = side === "A" ? event.team_a : event.team_b;
    const big = final ? event.score[side === "A" ? 0 : 1] : kills[side === "A" ? 0 : 1];
    return (
      <div className={`lh-half ${side === "B" ? "right" : ""}`} style={{ "--team": teamColor(team) } as React.CSSProperties}>
        <div className="lh-team"><TeamMark team={team} /><span className="lh-code">{team?.code ?? "TBD"}</span></div>
        <span className="lh-big num">{hidden ? "–" : big}</span>
        <span className="lh-sub">{final ? (event.winner === side ? "Winner" : " ") : hidden ? " " : `kills · ${live?.towers?.[side === "A" ? 0 : 1] ?? 0} towers`}</span>
      </div>
    );
  };
  return (
    <section className={`live-hero${final ? " final" : ""}`} aria-label="Scoreboard">
      <div className="lh-top">
        {half("A")}
        <div className="lh-mid">
          {final ? <span className="lh-final">FINAL</span> : <span className="lh-live"><span className="dot" />LIVE</span>}
          <span className="lh-clock num">{final ? `${event.score[0]}–${event.score[1]}` : hidden || live?.game_clock_s == null ? "··" : clock(live.game_clock_s)}</span>
          <span className="lh-game">{final ? `Bo${event.best_of}` : live?.game_index ? `Game ${live.game_index}` : "Between games"}</span>
        </div>
        {half("B")}
      </div>
      {hidden ? (
        <button type="button" className="lh-spoiler" onClick={onReveal}>Score hidden for anyone watching on delay. <b>Tap to show</b></button>
      ) : !final && live?.gold ? (
        <div className="lh-bottom">
          <div className="lh-goldline">
            <b>{lead === 0 ? "Gold even" : `${lead > 0 ? event.team_a?.code : event.team_b?.code} +${(Math.abs(lead) / 1000).toFixed(1)}k gold`}</b>
            <span className="muted">{live.dragons ? `${live.dragons[0].length} – ${live.dragons[1].length} dragons` : ""}</span>
          </div>
          <div className="lh-tug" aria-hidden="true" style={{ "--a": teamColor(event.team_a), "--b": teamColor(event.team_b) } as React.CSSProperties}>
            <span style={{ width: `${share}%` }} />
          </div>
          {live.events.length ? (
            <div className="lh-ticker">
              {live.events.slice(-5).reverse().map((e, i) => (
                <span className="lh-chip num" key={i}>{clock(e.at_s)} · {EVENT_LABEL[e.type]}{e.detail ? ` ${e.detail}` : ""} <b>{code(e.team)}</b></span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/** How your picks on this match stand right now, in one line. */
export function YourGame({ live }: { live: LiveT | undefined }) {
  const picks = live?.my_picks ?? [];
  if (!picks.length) return null;
  let back = 0, decided = 0, riding = 0, winning = 0, losing = 0;
  for (const p of picks) {
    const r = p.status !== "OPEN" ? p.status : p.call?.result;
    if (!r) {
      riding += p.stake_rc;
      continue;
    }
    decided += p.stake_rc;
    if (r === "WON") { back += p.status === "OPEN" ? p.potential_return_rc : p.return_rc; winning++; }
    else if (r === "VOID") back += p.stake_rc;
    else if (r === "PARTIAL") back += p.status === "OPEN" ? Math.round(p.stake_rc / 2) : p.return_rc;
    else losing++;
  }
  const net = back - decided;
  return (
    <section className={`your-game${net < 0 ? " down" : ""}`} aria-label="Your game">
      <div>
        <span className="yg-k">Your {picks.length} pick{picks.length === 1 ? "" : "s"} · {rc(riding)} RC still riding</span>
        <span className="yg-v num">{net >= 0 ? "+" : "−"}{rc(Math.abs(net))} RC</span>
        <span className="yg-s">decided so far</span>
      </div>
      <div className="yg-bars" aria-label={`${winning} winning, ${losing} losing, ${picks.length - winning - losing} undecided`}>
        {picks.map((p) => {
          const r = p.status !== "OPEN" ? p.status : p.call?.result;
          return <span key={p.id} className={r === "WON" ? "w" : r === "LOST" ? "l" : r ? "m" : ""} />;
        })}
      </div>
    </section>
  );
}

/** The one line that says whether anything can be picked right now. */
export function OpenNowBar({ event, onPlay }: { event: EventT; onPlay?: () => void }) {
  const now = useNow(1000);
  const o = openNow(event, now);
  if (!o.count) {
    return <div className="open-bar closed" role="status"><span className="ob-dot" />Nothing open right now<span className="ob-what">results land below as they happen</span></div>;
  }
  const body = (
    <>
      <span className="ob-dot" />
      <span><b>OPEN NOW</b><span className="ob-what"> · {o.what.join(", ")}</span></span>
      {o.closes ? <LockTimer at={o.closes} label="Closes in" /> : <MarketClose at={null} known={false} />}
    </>
  );
  return onPlay
    ? <button type="button" className="open-bar" onClick={onPlay}>{body}</button>
    : <div className="open-bar" role="status">{body}</div>;
}

const marketOf = (event: EventT, p: Pick) => (event.markets ?? []).find((m) => m.id === p.market_id);

/** Locked picks of yours the game is still deciding, with how far along they are. */
export function DecidingLive({ event, live }: { event: EventT; live: LiveT | undefined }) {
  const picks = (live?.my_picks ?? []).filter((p) => p.status === "OPEN" && !p.call && p.market_state !== "OPEN");
  if (!picks.length) return null;
  const clockS = live?.game_clock_s ?? null;
  return (
    <section className="band" aria-label="Deciding live">
      <h2 className="band-h muted">LOCKED · DECIDING LIVE</h2>
      {picks.map((p) => {
        const m = marketOf(event, p);
        const kind = m?.kind ?? "";
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
            <div className="dc-top"><b>{p.market_title}</b><span className="muted">You: {p.outcome_label} · {rc(p.stake_rc)}</span></div>
            {pct != null ? <div className="dc-bar"><span style={{ width: `${pct}%` }} /></div> : null}
            <div className="dc-foot muted"><span>{left}</span><span>{right || "waiting on the game"}</span></div>
          </div>
        );
      })}
    </section>
  );
}

/** Everything already decided on this game or series, as chips: green yours, amber half back, grey not yours. */
export function DecidedChips({ event, game, placed }: { event: EventT; game: GameT | null; placed: Map<string, number> }) {
  const rows = (event.markets ?? []).filter((m) =>
    (m.result || m.call) && (!game || m.params.game_index === game.index || (event.best_of === 1 && m.params.game_index === undefined)));
  if (!rows.length) return null;
  return (
    <section className="band" aria-label="Decided">
      <h2 className="band-h muted">DECIDED</h2>
      <div className="chips-wrap">
        {rows.map((m) => <DecidedChip key={m.id} market={m} placed={placed} />)}
      </div>
      <p className="fineprint" style={{ textAlign: "left", margin: 0 }}>Results show the moment they happen. Credits land once the data holds steady for 5 minutes.</p>
    </section>
  );
}

function DecidedChip({ market, placed }: { market: MarketT; placed: Map<string, number> }) {
  const r = market.result ?? market.call!;
  const winners = market.outcomes.filter((o) => r.winning_codes.includes(o.code)).map((o) => o.label).join(", ");
  const mine = market.outcomes.filter((o) => placed.has(o.id));
  const partial = market.call?.partial_codes ?? [];
  const verdict = !mine.length ? "none" : r.void ? "void" : mine.some((o) => r.winning_codes.includes(o.code)) ? "won"
    : mine.some((o) => partial.includes(o.code)) ? "half" : market.call?.pending_refund ? "pending" : "lost";
  const word = { none: "Not yours", void: "Void", won: "Won", half: "Half back", pending: "Ban check", lost: "Lost" }[verdict];
  const short = market.title.replace(/^Game \d+ /, "").replace(/ in Game \d+$/, "").replace(/^./, (c) => c.toUpperCase());
  const label = market.kind === "champion_picked" ? `${short}: ${r.winning_codes.includes("YES") ? "yes" : "no"}` : `${short} · ${winners || "—"}`;
  return (
    <span className={`dchip ${verdict} reveal`} title={market.call && !market.result ? market.call.reason : market.result?.reason}>
      <b>{word}</b> {label}
      {!market.result && market.call && verdict === "won" ? <> · <PayoutNote payAt={market.call.pays_at} final={market.call.final} /></> : null}
    </span>
  );
}

/** Watch mode: the game as a feed, your results woven in. */
export function Feed({ event, live, placed }: { event: EventT; live: LiveT | undefined; placed: Map<string, number> }) {
  const code = (t: "A" | "B" | null) => (t === "A" ? event.team_a?.code : t === "B" ? event.team_b?.code : "—");
  const items = [...(live?.events ?? [])].reverse();
  const decided = (event.markets ?? []).filter((m) => (m.result || m.call) && m.outcomes.some((o) => placed.has(o.id)));
  if (!items.length && !decided.length) return <p className="muted" style={{ fontSize: 14 }}>The feed fills in as the game plays.</p>;
  return (
    <section className="band" aria-label="Feed">
      <h2 className="band-h muted">FEED</h2>
      {decided.map((m) => {
        const r = m.result ?? m.call!;
        const won = !r.void && m.outcomes.some((o) => placed.has(o.id) && r.winning_codes.includes(o.code));
        return (
          <div className={`feed-row reveal${won ? " good" : ""}`} key={m.id}>
            <span className="fr-t">{won ? "WIN" : "PICK"}</span>
            <span>{m.title}: <b>{m.outcomes.filter((o) => r.winning_codes.includes(o.code)).map((o) => o.label).join(", ") || (r.void ? "void" : "—")}</b>{won ? <span className="win"> · your pick won</span> : null}</span>
          </div>
        );
      })}
      {items.map((e, i) => (
        <div className="feed-row reveal" key={i}>
          <span className="fr-t num">{clock(e.at_s)}</span>
          <span>{EVENT_LABEL[e.type]}{e.detail ? ` (${e.detail})` : ""} · <b>{code(e.team)}</b></span>
        </div>
      ))}
    </section>
  );
}
