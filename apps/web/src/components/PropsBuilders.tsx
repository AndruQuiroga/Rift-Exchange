"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { api, ApiError } from "@/lib/api";
import { useNow, usePlaced } from "@/lib/hooks";
import { oddsSpoken } from "@/lib/format";
import { useSlip } from "@/lib/slip";
import type { EventT, MarketT } from "@/lib/types";
import { RetryNotice } from "./bits";
import { ChampIcon } from "./ChampionGrid";
import { Choice } from "./Choice";
import { Odds } from "./Odds";
import { DraftLock, LockTimer } from "./Timing";

type Side = "A" | "B";
/** BLIND: before the draft, no champions. DRAFT: blind closed, waiting for the game to load. LIVE: after the
 * draft with champions, until 3:00. UPCOMING: a later game. CLOSED: over (D-031). */
type Phase = "BLIND" | "DRAFT" | "LIVE" | "UPCOMING" | "CLOSED";
type WindowState = { phase?: Phase; open: boolean; state: "UPCOMING" | "OPEN" | "CLOSED"; close_at: string | null; opens_when: string | null };
const phaseOf = (d: WindowState): Phase => d.phase ?? (d.open ? "LIVE" : d.state === "UPCOMING" ? "DRAFT" : "CLOSED");

function WindowNote({ data, now, event }: { data: WindowState; now: number; event?: EventT }) {
  const phase = phaseOf(data);
  const open = data.open && !!data.close_at && Date.parse(data.close_at) > now;
  return (
    <div className={`phase-note ${phase.toLowerCase()}`} role="status">
      <span className="phase-tag">{phase === "BLIND" ? "Blind" : phase === "LIVE" ? "After draft" : phase === "DRAFT" ? "Drafting" : phase === "UPCOMING" ? "Later" : "Closed"}</span>
      <span className="phase-text">
        {phase === "BLIND" ? "Called before the draft, whatever champions they play."
          : phase === "LIVE" ? "Champions locked in. Priced from the live game."
          : phase === "DRAFT" ? "No picks during the draft. They reopen with champions when the game loads."
          : phase === "UPCOMING" ? (data.opens_when ?? "Opens when the previous game ends.")
          : "Early-game picks are closed."}
      </span>
      {open && phase === "BLIND" && event?.status === "SCHEDULED" ? <DraftLock scheduledAt={event.scheduled_at} />
        : open ? <LockTimer at={data.close_at} label={phase === "BLIND" ? "Blind closes in" : "Closes in"} /> : null}
    </div>
  );
}

/** Which market a builder button belongs to: blind and after-draft markets are separate (D-031). */
const inPhase = (m: MarketT, phase: Phase) => (phase === "BLIND" ? !!m.params.blind : !m.params.blind);
type DuelGrid = WindowState & {
  stats: { id: string; label: string }[];
  duels: { role: string; a: { player_id: string; name: string; champion?: string }; b: { player_id: string; name: string; champion?: string }; odds: Record<string, Record<Side, string | null>> }[];
};
type LineGrid = WindowState & { champions?: Partial<Record<Side, Record<string, { champion?: string }>>>; typical: string | null; lines: { line: string; over: string; under: string }[] };

const ROLE_LONG: Record<string, string> = { top: "TOP LANE", jungle: "JUNGLE", mid: "MID LANE", bottom: "BOT LANE", support: "SUPPORT" };

/** Tap a side, get (or create, once for everyone) the market behind it, and toggle it on the slip. */
function useOnDemand(event: EventT) {
  const slip = useSlip();
  const [created, setCreated] = useState<Record<string, string>>({});
  const [error, setError] = useState<{ text: string; retry: () => void } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const held = usePlaced();
  const label = `${event.team_a?.code ?? "TBD"} vs ${event.team_b?.code ?? "TBD"}`;
  async function tap(key: string, path: string, body: unknown, code: string) {
    const known = created[key];
    if (known && slip.isSelected(known)) {
      slip.undo(known); // still in its undo window
      slip.remove(known);
      return;
    }
    setError(null);
    setBusy(key);
    try {
      const market = await api<MarketT>(path, { method: "POST", json: body });
      const outcome = market.outcomes.find((o) => o.code === code);
      if (!outcome) return;
      setCreated((p) => ({ ...p, [key]: outcome.id }));
      slip.toggle(market, outcome, label);
    } catch (e) {
      const text = e instanceof ApiError ? e.message : "Couldn't get a price. Check your connection.";
      setError({ text, retry: () => tap(key, path, body, code) });
    } finally {
      setBusy(null);
    }
  }
  const selected = (key: string) => (created[key] ? slip.isSelected(created[key]) : false);
  const notice = error ? <RetryNotice text={error.text} onRetry={error.retry} /> : null;
  // An on-demand market someone already created comes back on the event; mark it if you hold a pick on it.
  const placed = (match: (m: MarketT) => boolean, code: string) => {
    const o = (event.markets ?? []).find(match)?.outcomes.find((x) => x.code === code);
    return !!o && held.has(o.id);
  };
  return { tap, selected, placed, isBusy: (key: string) => busy === key, notice };
}

/** The price on an on-demand button, or a spinner while its market is fetched. */
function Price({ odds, busy, style }: { odds: string | null; busy: boolean; style?: React.CSSProperties }) {
  return <span className="px num" style={style}>{busy ? <span className="spinner" aria-hidden="true" /> : <Odds value={odds} />}</span>;
}

export function LaneDuels({ event, game }: { event: EventT; game: number }) {
  const { data } = useSWR<DuelGrid>(`/events/${event.id}/duels?game=${game}`, { refreshInterval: 2000 });
  const now = useNow(1000);
  const [picked, setStat] = useState<string | null>(null);
  const { tap, selected, placed, isBusy, notice } = useOnDemand(event);
  if (!data) return <div className="skeleton" style={{ height: 160, marginTop: 12 }} />;
  if (!data.duels.length) return <WindowNote data={data} now={now} event={event} />;
  const open = data.open && !!data.close_at && Date.parse(data.close_at) > now;
  const phase = phaseOf(data);
  const stat = picked ?? data.stats[0]?.id ?? "gold15";
  return (
    <div>
      <WindowNote data={data} now={now} event={event} />
      {data.stats.length > 1 ? (
        <div className="segmented" role="group" aria-label="Duel stat" style={{ marginTop: 12 }}>
          {data.stats.map((s) => (
            <button key={s.id} aria-pressed={stat === s.id} onClick={() => setStat(s.id)}>
              {s.label}
            </button>
          ))}
        </div>
      ) : null}
      <p className="muted" style={{ fontSize: 13 }}>
        {stat === "gold15" ? "Which laner has more gold at 15:00. A gap under 700 gold is a tie and void." : `${data.stats.find((s) => s.id === stat)?.label} in Game ${game}`}
      </p>
      <div className="duel-grid">
        {data.duels.map((d) => {
          const side = (s: Side) => {
            const key = `${game}:${phase}:${d.role}:${stat}:${s}`;
            const px = d.odds[stat]?.[s];
            const p = s === "A" ? d.a : d.b;
            const mine = placed((m) => m.kind === "lane_duel" && m.params.game_index === game && m.params.role === d.role && m.params.stat === stat && inPhase(m, phase), s);
            return (
              <button
                className="duel-side"
                aria-pressed={selected(key)}
                data-placed={mine || undefined}
                disabled={!open || !px || isBusy(key)}
                aria-busy={isBusy(key) || undefined}
                onClick={() => tap(key, `/events/${event.id}/duels`, { game_index: game, role: d.role, stat }, s)}
                aria-label={`${p.name}${p.champion ? ` on ${p.champion}` : ""}, ${oddsSpoken(px ?? null)}`}
              >
                {p.champion ? <ChampIcon id={p.champion} label={p.champion} /> : <span className="cicon pending" aria-hidden="true">{phase === "DRAFT" ? "…" : "?"}</span>}
                <span className="ds-name">{p.name}</span>
                <small className="ds-champ">{p.champion ?? (phase === "BLIND" ? "Any champion" : phase === "DRAFT" ? "Drafting…" : "Champion pending")}</small>
                <Price odds={px ?? null} busy={isBusy(key)} />
                {mine ? <span className="pk-tag">Placed</span> : null}
              </button>
            );
          };
          return (
            <div className="duel-card" key={d.role}>
              <div className="dcard-head"><span>{ROLE_LONG[d.role]}</span><span className="muted">{event.team_a?.code} vs {event.team_b?.code}</span></div>
              <div className="dcard-sides">
                {side("A")}
                {side("B")}
              </div>
            </div>
          );
        })}
      </div>
      {notice}
      <p className="fineprint" style={{ textAlign: "left" }}>
        {phase === "BLIND"
          ? "Blind duels stand whatever champions are picked; void if either player doesn't play."
          : "Champions confirm when the game loads. Picks close at 3:00."}
      </p>
    </div>
  );
}

export function KillLine({ event, game }: { event: EventT; game: number }) {
  const { data } = useSWR<LineGrid>(`/events/${event.id}/kill-lines?game=${game}`, { refreshInterval: 2000 });
  const now = useNow(1000);
  const [index, setIndex] = useState<number | null>(null);
  const { tap, selected, placed, isBusy, notice } = useOnDemand(event);
  useEffect(() => {
    if (data && data.lines.length && index === null) {
      const typical = data.lines.findIndex((l) => l.line === data.typical);
      setIndex(typical >= 0 ? typical : Math.floor(data.lines.length / 2));
    }
  }, [data, index]);
  if (!data) return <div className="skeleton" style={{ height: 140, marginTop: 12 }} />;
  if (!data.lines.length || index === null) return <><WindowNote data={data} now={now} event={event} />{data.open ? <p className="muted">No kill lines are priced yet.</p> : null}</>;
  const activeIndex = Math.min(index, data.lines.length - 1);
  const row = data.lines[activeIndex];
  const open = data.open && !!data.close_at && Date.parse(data.close_at) > now;
  const phase = phaseOf(data);
  return (
    <div style={{ marginTop: 12 }}>
      <WindowNote data={data} now={now} event={event} />
      {data.champions && Object.keys(data.champions).length ? <div className="line-champs">
        {(["A", "B"] as const).map((side) => (
          <div key={side}>
            <b>{side === "A" ? event.team_a?.code : event.team_b?.code}</b>
            {Object.values(data.champions?.[side] ?? {}).map((p) => p.champion).filter((c): c is string => !!c).map((c) => <ChampIcon key={c} id={c} label={c} small />)}
          </div>
        ))}
      </div> : null}
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "center", gap: 6 }}>
        <span className="display num" style={{ fontSize: 40, fontWeight: 800, lineHeight: 1 }}>{row.line}</span>
        <span className="muted" style={{ fontSize: 13 }}>total kills · Game {game}</span>
      </div>
      <input
        type="range"
        className="line-slider"
        min={0}
        max={data.lines.length - 1}
        value={activeIndex}
        onChange={(e) => setIndex(Number(e.target.value))}
        aria-label="Kill line"
        aria-valuetext={`${row.line} kills`}
      />
      <div className="muted num" style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
        <span>{data.lines[0].line}</span>
        {data.typical ? <span>Typical {data.typical}</span> : null}
        <span>{data.lines[data.lines.length - 1].line}</span>
      </div>
      <div className="mrow-sides" style={{ marginTop: 10 }}>
        {(["OVER", "UNDER"] as const).map((code) => {
          const key = `${game}:${phase}:${row.line}:${code}`;
          const px = code === "OVER" ? row.over : row.under;
          const mine = placed((m) => m.kind === "total_kills_game" && m.params.game_index === game && String(m.params.line) === String(row.line) && inPhase(m, phase), code);
          return (
            <button
              key={code}
              className="side"
              style={{ justifyContent: "space-between" }}
              aria-pressed={selected(key)}
              data-placed={mine || undefined}
              disabled={!open || isBusy(key)}
              aria-busy={isBusy(key) || undefined}
              onClick={() => tap(key, `/events/${event.id}/kill-lines`, { game_index: game, line: row.line }, code)}
            >
              <span className="code">{code === "OVER" ? "Over" : "Under"} {row.line}</span>
              <Price odds={px} busy={isBusy(key)} />
              {mine ? <span className="pk-tag">Placed</span> : null}
            </button>
          );
        })}
      </div>
      {notice}
    </div>
  );
}

const OBJECTIVE_ORDER = ["first_blood", "first_dragon_type", "first_tower", "baron_before", "dragon_soul"];

export function Objectives({ event, game }: { event: EventT; game: number }) {
  const markets = OBJECTIVE_ORDER.map((k) => (event.markets ?? []).find((m) => m.kind === k && m.params.game_index === game)).filter(Boolean) as MarketT[];
  const label = `${event.team_a?.code ?? "TBD"} vs ${event.team_b?.code ?? "TBD"}`;
  if (!markets.length) return <p className="muted" style={{ fontSize: 14, marginTop: 12 }}>Objective markets open with the game.</p>;
  return (
    <div className="objectives">
      {markets.map((m) => (
        <div className="objective" key={m.id}>
          <div className="t">{m.title.replace(`Game ${game} `, "")}</div>
          <div className="opts">
            {m.outcomes.map((o) => (
              <Choice key={o.id} market={m} outcome={o} label={label} className="mini">
                {o.code === "A" ? event.team_a?.code : o.code === "B" ? event.team_b?.code : o.label} <b className="num"><Odds value={o.odds} /></b>
              </Choice>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
