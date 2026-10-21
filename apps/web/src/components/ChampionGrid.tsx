"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { api, ApiError } from "@/lib/api";
import { countdown, oddsSpoken } from "@/lib/format";
import { useNow, usePlaced } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import type { EventT, MarketT } from "@/lib/types";
import { RetryNotice } from "./bits";
import { Odds } from "./Odds";

// "Picked by either team" is the one draft call offered; existing picks on other draft markets still settle.
type Scope = "picked";
type GridChampion = {
  champion: string;
  label: string;
  role: string | null;
  odds: Partial<Record<Scope, string | null>>;
};
type Grid = {
  game_index: number;
  open: boolean;
  close_at: string | null;
  games_observed: number;
  burned: { champion: string; label: string }[];
  champions: GridChampion[];
};

const ROLES = [
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

const keyOf = (game: number, champ: string, scope: Scope) => `${game}:${champ}:${scope}`;

/** The draft grid for one game, and tapping a champion: its market is created once, for everyone, on first tap. */
function useDraft(event: EventT, game: number) {
  const slip = useSlip();
  const held = usePlaced();
  const { mutate } = useSWRConfig();
  const { data: grid } = useSWR<Grid>(`/events/${event.id}/draft?game=${game}`);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<{ text: string; retry: () => void } | null>(null);
  const [created, setCreated] = useState<Record<string, string>>({});
  const label = `${event.team_a?.code ?? "TBD"} vs ${event.team_b?.code ?? "TBD"}`;

  // Markets made earlier (by anyone) come back with the event, so selection survives a reload.
  const known = useMemo(() => {
    const map: Record<string, string> = {};
    for (const m of event.markets ?? []) {
      if (m.kind !== "champion_picked" || typeof m.params.game_index !== "number" || m.params.side || m.params.role) continue;
      const yes = m.outcomes.find((o) => o.code === "YES");
      if (yes) map[keyOf(m.params.game_index, String(m.params.champion), "picked")] = yes.id;
    }
    return { ...map, ...created };
  }, [event.markets, created]);

  async function tap(c: GridChampion, scope: Scope) {
    const key = keyOf(game, c.champion, scope);
    const existing = known[key];
    if (existing && slip.isSelected(existing)) {
      slip.undo(existing); // still in its undo window
      slip.remove(existing);
      return;
    }
    setBusy(key);
    setError(null);
    try {
      const market = await api<MarketT>(`/events/${event.id}/draft`, { method: "POST", json: { game_index: game, champion: c.champion, scope } });
      const yes = market.outcomes.find((o) => o.code === "YES");
      if (!yes) return;
      setCreated((p) => ({ ...p, [key]: yes.id }));
      slip.toggle(market, yes, label);
      mutate(`/events/${event.id}`); // the featured cards and the full grid both read it
    } catch (e) {
      setError({ text: e instanceof ApiError ? e.message : `Couldn't get a price for ${c.label}.`, retry: () => tap(c, scope) });
    } finally {
      setBusy(null);
    }
  }
  const state = (c: GridChampion, scope: Scope) => {
    const id = known[keyOf(game, c.champion, scope)];
    return { selected: id ? slip.isSelected(id) : false, placed: !!id && held.has(id), busy: busy === keyOf(game, c.champion, scope) };
  };
  const notice = error ? <RetryNotice text={error.text} onRetry={error.retry} /> : null;
  return { grid, tap, state, notice };
}

/** A few champions worth a yes/no call: the ones closest to a coin flip, not the near-certain picks. */
function featuredOf(grid: Grid | undefined, n: number): GridChampion[] {
  const priced = (grid?.champions ?? []).filter((c) => c.odds.picked).map((c) => ({ c, o: Number(c.odds.picked) }));
  const lively = priced.filter((x) => x.o >= 1.5 && x.o <= 4.5).sort((a, b) => Math.abs(a.o - 2.2) - Math.abs(b.o - 2.2));
  const pool = lively.length >= n ? lively : priced.sort((a, b) => a.o - b.o);
  return pool.slice(0, n).map((x) => x.c);
}

/** One-tap draft calls for the match page: "Is this champion picked in Game N?" */
export function FeaturedDraft({ event, game }: { event: EventT; game: number }) {
  const { grid, tap, state, notice } = useDraft(event, game);
  if (!grid?.open) return null;
  const picks = featuredOf(grid, 3);
  if (!picks.length) return null;
  return (
    <>
      {picks.map((c) => {
        const s = state(c, "picked");
        return (
          <button
            key={c.champion}
            type="button"
            className="fcard"
            aria-pressed={s.selected}
            data-placed={s.placed || undefined}
            aria-busy={s.busy || undefined}
            disabled={s.busy}
            onClick={() => tap(c, "picked")}
            aria-label={`${c.label} picked in Game ${game}: yes, ${oddsSpoken(c.odds.picked ?? null)}`}
          >
            <ChampIcon id={c.champion} label={c.label} />
            <span className="q">
              <span className="t">{c.label} picked?</span>
              <span className="s">Game {game} draft · either team</span>
            </span>
            <span className="px num">{s.busy ? <span className="spinner" aria-hidden="true" /> : <>Yes <Odds value={c.odds.picked ?? null} /></>}</span>
          </button>
        );
      })}
      {notice}
    </>
  );
}

/** Every champion for one game: tap the ones you think get picked, by either team. */
export function ChampionGrid({ event, game }: { event: EventT; game: number }) {
  const now = useNow();
  const { grid, tap, state, notice } = useDraft(event, game);
  const scope: Scope = "picked";
  const [role, setRole] = useState("all");
  const [query, setQuery] = useState("");
  const [focusAt, setFocusAt] = useState(0);

  const q = query.trim().toLowerCase();
  const shown = (grid?.champions ?? []).filter((c) => (role === "all" || c.role === role) && (!q || c.label.toLowerCase().includes(q)) && c.odds[scope]);
  const lock = grid?.close_at ? countdown(grid.close_at, now) : null;

  // One tab stop for the whole grid; arrow keys, Home and End move between tiles.
  function gridKeys(e: React.KeyboardEvent<HTMLDivElement>) {
    const tiles = [...e.currentTarget.querySelectorAll<HTMLButtonElement>(".ctile")];
    const i = tiles.indexOf(document.activeElement as HTMLButtonElement);
    const cols = getComputedStyle(e.currentTarget).gridTemplateColumns.split(" ").length;
    const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols, Home: -i, End: tiles.length - 1 - i }[e.key];
    if (i < 0 || step === undefined) return;
    e.preventDefault();
    const next = Math.max(0, Math.min(tiles.length - 1, i + step));
    setFocusAt(next);
    tiles[next].focus();
  }

  return (
    <div>
      {grid && !grid.open ? (
        <div className="window-note">
          {game === 1 ? "Draft picks for this series are closed." : `Game ${game} opens when Game ${game - 1} ends — about 8 minutes before its draft.`}
        </div>
      ) : (
        <p className="muted" style={{ fontSize: 13, marginTop: 12 }}>
          {`Tap a champion you think gets picked in Game ${game}, by either team.`}
          {lock ? ` Locks in ${lock}.` : ""}
        </p>
      )}

      <label className="searchbox">
        <span className="sr-only">Search champions</span>
        <input placeholder={`Search ${grid?.champions.length ?? ""} champions`} value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      <div className="chips" style={{ marginTop: 8 }}>
        {[{ id: "all", label: "All" }, ...ROLES].map((r) => (
          <button key={r.id} className="chip" aria-pressed={role === r.id} onClick={() => setRole(r.id)}>
            {r.label}
          </button>
        ))}
      </div>

      {notice}

      {!grid ? (
        <div className="skeleton" style={{ marginTop: 12, height: 200 }} />
      ) : shown.length === 0 ? (
        <p className="muted" style={{ marginTop: 12, fontSize: 14 }}>No champions match.</p>
      ) : (
        <div className="cgrid" role="group" aria-label="Champions · arrow keys move between them" onKeyDown={gridKeys}>
          {shown.map((c, i) => {
            const s = state(c, scope);
            const px = c.odds[scope] ?? null;
            return (
              <button
                key={c.champion}
                className={`ctile${s.busy ? " busy" : ""}`}
                aria-pressed={s.selected}
                data-placed={s.placed || undefined}
                aria-busy={s.busy || undefined}
                disabled={!grid.open || s.busy}
                tabIndex={i === Math.min(focusAt, shown.length - 1) ? 0 : -1}
                onFocus={() => setFocusAt(i)}
                onClick={() => tap(c, scope)}
                aria-label={`${c.label} picked in Game ${game}, ${oddsSpoken(px)}`}
              >
                <ChampIcon id={c.champion} label={c.label} />
                <span className="nm">{c.label}</span>
                <span className="px num">{s.busy ? <span className="spinner" aria-hidden="true" /> : <Odds value={px} />}</span>
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
        Experimental prices from {grid?.games_observed ?? 0} verified Worlds games so far.
      </p>
    </div>
  );
}
