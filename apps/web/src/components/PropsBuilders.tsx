"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { api, ApiError } from "@/lib/api";
import { useNow, usePlaced } from "@/lib/hooks";
import { countdown, oddsSpoken } from "@/lib/format";
import { useSlip } from "@/lib/slip";
import type { EventT, MarketT } from "@/lib/types";
import { RetryNotice } from "./bits";
import { Choice } from "./Choice";
import { Odds } from "./Odds";

type Side = "A" | "B";
type WindowState = { open: boolean; state: "UPCOMING" | "OPEN" | "CLOSED"; close_at: string | null; opens_when: string | null };
function WindowNote({ data, now }: { data: WindowState; now: number }) {
  const seconds = data.close_at ? Math.max(0, Math.ceil((Date.parse(data.close_at) - now) / 1000)) : 0;
  const text = data.state === "UPCOMING" ? "Opens after draft, when champions are confirmed."
    : data.open && seconds > 0
      ? `Closes in ${seconds < 3600 ? `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}` : countdown(data.close_at!, now)}`
    : "Early-game picks closed.";
  return <p className="muted num" role="status" style={{ fontSize: 13, marginTop: 12 }}>{text}</p>;
}
type DuelGrid = WindowState & {
  stats: { id: string; label: string }[];
  duels: { role: string; a: { player_id: string; name: string; champion?: string }; b: { player_id: string; name: string; champion?: string }; odds: Record<string, Record<Side, string | null>> }[];
};
type LineGrid = WindowState & { champions?: Partial<Record<Side, Record<string, { champion?: string }>>>; typical: string | null; lines: { line: string; over: string; under: string }[] };

const ROLE_SHORT: Record<string, string> = { top: "TOP", jungle: "JGL", mid: "MID", bottom: "BOT", support: "SUP" };

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
  const [stat, setStat] = useState("kills");
  const { tap, selected, placed, isBusy, notice } = useOnDemand(event);
  if (!data) return <div className="skeleton" style={{ height: 160, marginTop: 12 }} />;
  if (!data.duels.length) return <WindowNote data={data} now={now} />;
  const open = data.open && !!data.close_at && Date.parse(data.close_at) > now;
  return (
    <div>
      <WindowNote data={data} now={now} />
      <div className="segmented" role="group" aria-label="Duel stat" style={{ marginTop: 12 }}>
        {data.stats.map((s) => (
          <button key={s.id} aria-pressed={stat === s.id} onClick={() => setStat(s.id)}>
            {s.id === "kills" ? "Kills" : s.id === "cs15" ? "CS @15" : "Damage"}
          </button>
        ))}
      </div>
      <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>{data.stats.find((s) => s.id === stat)?.label} in Game {game}</p>
      <div className="duels">
        {data.duels.map((d) => {
          const side = (s: Side) => {
            const key = `${game}:${d.role}:${stat}:${s}`;
            const px = d.odds[stat]?.[s];
            const mine = placed((m) => m.kind === "lane_duel" && m.params.game_index === game && m.params.role === d.role && m.params.stat === stat, s);
            return (
              <button
                className={`side${s === "B" ? " right" : ""}`}
                style={{ minHeight: 48 }}
                aria-pressed={selected(key)}
                data-placed={mine || undefined}
                disabled={!open || !px || isBusy(key)}
                aria-busy={isBusy(key) || undefined}
                onClick={() => tap(key, `/events/${event.id}/duels`, { game_index: game, role: d.role, stat }, s)}
                aria-label={`${(s === "A" ? d.a : d.b).name}, ${oddsSpoken(px ?? null)}`}
              >
                <span className="duel-name"><span className="code">{(s === "A" ? d.a : d.b).name}</span><small style={{ display: "block", color: "var(--muted)" }}>{(s === "A" ? d.a : d.b).champion ?? "Champion pending"}</small></span>
                <Price odds={px ?? null} busy={isBusy(key)} style={{ fontSize: 15 }} />
              </button>
            );
          };
          return (
            <div className="duel-row" key={d.role}>
              {side("A")}
              <span className="duel-role">{ROLE_SHORT[d.role]}</span>
              {side("B")}
            </div>
          );
        })}
      </div>
      {notice}
      <p className="fineprint" style={{ textAlign: "left" }}>Champions confirm when the game loads. Picks close at 3:00. Ties void.</p>
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
  if (!data.lines.length || index === null) return <><WindowNote data={data} now={now} />{data.open ? <p className="muted">No kill lines are priced yet.</p> : null}</>;
  const activeIndex = Math.min(index, data.lines.length - 1);
  const row = data.lines[activeIndex];
  const open = data.open && !!data.close_at && Date.parse(data.close_at) > now;
  return (
    <div style={{ marginTop: 12 }}>
      <WindowNote data={data} now={now} />
      {data.champions ? <div style={{ fontSize: 12, margin: "8px 0 12px" }}>
        {(["A", "B"] as const).map((side) => <p key={side} className="muted"><b>{side === "A" ? event.team_a?.code : event.team_b?.code}</b> · {Object.values(data.champions?.[side] ?? {}).map((p) => p.champion).filter(Boolean).join(" · ")}</p>)}
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
          const key = `${game}:${row.line}:${code}`;
          const px = code === "OVER" ? row.over : row.under;
          const mine = placed((m) => m.kind === "total_kills_game" && m.params.game_index === game && String(m.params.line) === String(row.line), code);
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
