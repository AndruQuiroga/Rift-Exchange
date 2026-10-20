"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, ApiError } from "@/lib/api";
import { countdown, odds as fmtOdds } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import type { EventT, MarketT } from "@/lib/types";

type Scope = "picked" | "A" | "B";
type GridChampion = { champion: string; label: string; role: string | null; odds: Record<Scope, string | null> };
type Grid = {
  game_index: number;
  open: boolean;
  close_at: string | null;
  games_observed: number;
  burned: { champion: string; label: string }[];
  champions: GridChampion[];
};

const ROLES = [
  { id: "all", label: "All" },
  { id: "top", label: "Top" },
  { id: "jungle", label: "Jungle" },
  { id: "mid", label: "Mid" },
  { id: "bottom", label: "Bot" },
  { id: "support", label: "Support" },
];

// Champion art from Riot's public Data Dragon CDN; falls back to initials if it can't load.
let ddragon: Promise<string | null> | null = null;
function ddragonVersion(): Promise<string | null> {
  ddragon ??= fetch("https://ddragon.leagueoflegends.com/api/versions.json")
    .then((r) => (r.ok ? r.json() : null))
    .then((v: string[] | null) => v?.[0] ?? null)
    .catch(() => null);
  return ddragon;
}

export function ChampIcon({ id, label, small }: { id: string; label: string; small?: boolean }) {
  const [version, setVersion] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    ddragonVersion().then(setVersion);
  }, []);
  return (
    <span className={`cicon${small ? " sm" : ""}`} aria-hidden="true">
      {version && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element -- small CDN icons; no optimiser needed
        <img src={`https://ddragon.leagueoflegends.com/cdn/${version}/img/champion/${id}.png`} alt="" loading="lazy" onError={() => setFailed(true)} />
      ) : (
        label.replace(/[^A-Za-z]/g, "").slice(0, 2)
      )}
    </span>
  );
}

/** Tap any champion for a price; the market behind it is created once, for everyone, on first tap. */
export function ChampionGrid({ event, game: fixedGame }: { event: EventT; game?: number }) {
  const slip = useSlip();
  const now = useNow();
  const [pickedGame, setGame] = useState(1);
  const game = fixedGame ?? pickedGame;
  const [scope, setScope] = useState<Scope>("picked");
  const [role, setRole] = useState("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Record<string, string>>({});
  const { data: grid } = useSWR<Grid>(`/events/${event.id}/draft?game=${game}`);

  // Markets made earlier (by anyone) come back with the event, so selection survives a reload.
  const known = useMemo(() => {
    const map: Record<string, string> = { ...created };
    for (const m of event.markets ?? []) {
      if (m.kind !== "champion_picked" || typeof m.params.game_index !== "number") continue;
      const yes = m.outcomes.find((o) => o.code === "YES");
      if (yes) map[`${m.params.game_index}:${m.params.champion}:${(m.params.side as string) ?? "picked"}`] = yes.id;
    }
    return map;
  }, [event.markets, created]);

  const label = `${event.team_a?.code ?? "TBD"} vs ${event.team_b?.code ?? "TBD"}`;
  const q = query.trim().toLowerCase();
  const shown = (grid?.champions ?? []).filter(
    (c) => (role === "all" || c.role === role) && (!q || c.label.toLowerCase().includes(q)) && c.odds[scope],
  );
  const lock = grid?.close_at ? countdown(grid.close_at, now) : null;

  async function tap(c: GridChampion) {
    const key = `${game}:${c.champion}:${scope}`;
    const existing = known[key];
    if (existing && slip.isSelected(existing)) return slip.remove(existing);
    setBusy(key);
    setError(null);
    try {
      const market = await api<MarketT>(`/events/${event.id}/draft`, { method: "POST", json: { game_index: game, champion: c.champion, scope } });
      const yes = market.outcomes.find((o) => o.code === "YES");
      if (!yes) return;
      setCreated((p) => ({ ...p, [key]: yes.id }));
      slip.toggle(market, yes, label);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't get a price.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      {event.best_of > 1 && fixedGame === undefined ? (
        <div className="chips" role="tablist" aria-label="Game" style={{ marginTop: 12 }}>
          {Array.from({ length: event.best_of }, (_, i) => i + 1).map((g) => (
            <button key={g} role="tab" className="chip" aria-selected={g === game} onClick={() => setGame(g)}>
              Game {g}
            </button>
          ))}
        </div>
      ) : null}

      <div className="segmented" role="tablist" aria-label="What to call" style={{ marginTop: 12 }}>
        {(["picked", "A", "B"] as const).map((s) => (
          <button key={s} role="tab" aria-selected={scope === s} onClick={() => setScope(s)}>
            {s === "picked" ? "Picked" : `By ${s === "A" ? event.team_a?.code : event.team_b?.code}`}
          </button>
        ))}
      </div>

      {grid && !grid.open ? (
        <div className="window-note">
          {game === 1 ? "Draft picks for this series are closed." : `Game ${game} opens when Game ${game - 1} ends — about 8 minutes before its draft.`}
        </div>
      ) : lock ? (
        <div className="muted" style={{ fontSize: 13, marginTop: 10 }}>
          Game {game} picks lock in {lock}{game === 1 ? ", or as soon as the match goes live" : ""}.
        </div>
      ) : null}

      <label className="searchbox">
        <span className="sr-only">Search champions</span>
        <input placeholder={`Search ${grid?.champions.length ?? ""} champions`} value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      <div className="chips" style={{ marginTop: 8 }}>
        {ROLES.map((r) => (
          <button key={r.id} className="chip" aria-pressed={role === r.id} onClick={() => setRole(r.id)}>
            {r.label}
          </button>
        ))}
      </div>

      {error ? <div className="notice error" role="alert" style={{ marginTop: 10 }}>{error}</div> : null}

      {!grid ? (
        <div className="skeleton" style={{ marginTop: 12, height: 200 }} />
      ) : shown.length === 0 ? (
        <p className="muted" style={{ marginTop: 12, fontSize: 14 }}>No champions match.</p>
      ) : (
        <div className="cgrid">
          {shown.map((c) => {
            const key = `${game}:${c.champion}:${scope}`;
            const selected = known[key] ? slip.isSelected(known[key]) : false;
            return (
              <button
                key={c.champion}
                className="ctile"
                aria-pressed={selected}
                disabled={!grid.open || busy === key}
                onClick={() => tap(c)}
                aria-label={`${c.label} ${scope === "picked" ? "picked" : `picked by ${scope === "A" ? event.team_a?.code : event.team_b?.code}`} in Game ${game}, ${fmtOdds(c.odds[scope])} times`}
              >
                <ChampIcon id={c.champion} label={c.label} />
                <span className="nm">{c.label}</span>
                <span className="px num">{fmtOdds(c.odds[scope])}×</span>
              </button>
            );
          })}
        </div>
      )}

      {grid?.burned.length ? (
        <div style={{ marginTop: 16 }}>
          <div className="eyebrow">Already played this series · unavailable</div>
          <div className="burned">
            {grid.burned.map((b) => (
              <div key={b.champion}>
                <ChampIcon id={b.champion} label={b.label} small />
                <span style={{ maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{b.label}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <p className="fineprint" style={{ textAlign: "left" }}>
        Yes if the champion is picked in Game {game}. Experimental prices from {grid?.games_observed ?? 0} verified Worlds games so far.
      </p>
    </div>
  );
}
