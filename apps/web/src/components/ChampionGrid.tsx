"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, ApiError } from "@/lib/api";
import { countdown, odds as fmtOdds, oddsSpoken } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import type { EventT, MarketT } from "@/lib/types";
import { RetryNotice } from "./bits";

type Scope = "picked" | "A" | "B" | "banned" | "first";
type Side = "A" | "B";
type GridChampion = {
  champion: string;
  label: string;
  role: string | null;
  odds: Partial<Record<Scope, string | null>>;
  roles?: Partial<Record<Side, Record<string, string>>>;
};
type Grid = {
  game_index: number;
  open: boolean;
  close_at: string | null;
  games_observed: number;
  scopes?: Scope[];
  burned: { champion: string; label: string }[];
  champions: GridChampion[];
};

const ROLES = [
  { id: "top", label: "Top", short: "TOP" },
  { id: "jungle", label: "Jungle", short: "JGL" },
  { id: "mid", label: "Mid", short: "MID" },
  { id: "bottom", label: "Bot", short: "BOT" },
  { id: "support", label: "Support", short: "SUP" },
];
const KIND_SCOPE: Record<string, Scope> = { champion_banned: "banned", champion_first_pick: "first" };

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

const keyOf = (game: number, champ: string, scope: Scope, role?: string) => `${game}:${champ}:${scope}${role ? `:${role}` : ""}`;

/** Tap any champion for a price; the market behind it is created once, for everyone, on first tap. */
export function ChampionGrid({ event, game: fixedGame }: { event: EventT; game?: number }) {
  const slip = useSlip();
  const now = useNow();
  const [pickedGame, setGame] = useState(1);
  const game = fixedGame ?? pickedGame;
  const [mode, setMode] = useState<"grid" | "select">("grid");
  const [scope, setScope] = useState<Scope>("picked");
  const [slot, setSlot] = useState<{ side: Side; role: string }>({ side: "A", role: "top" });
  const [role, setRole] = useState("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<{ text: string; retry: GridChampion } | null>(null);
  const [focusAt, setFocusAt] = useState(0);
  const [created, setCreated] = useState<Record<string, { outcomeId: string; label: string; odds: string | null }>>({});
  const { data: grid } = useSWR<Grid>(`/events/${event.id}/draft?game=${game}`);

  // Markets made earlier (by anyone) come back with the event, so selection survives a reload.
  const known = useMemo(() => {
    const map: Record<string, { outcomeId: string; label: string; odds: string | null }> = {};
    for (const m of event.markets ?? []) {
      if (!m.kind.startsWith("champion_") || typeof m.params.game_index !== "number") continue;
      const yes = m.outcomes.find((o) => o.code === "YES");
      const scope: Scope = KIND_SCOPE[m.kind] ?? ((m.params.side as Side | undefined) ?? "picked");
      if (yes) map[keyOf(m.params.game_index, String(m.params.champion), scope, m.params.role as string | undefined)] = { outcomeId: yes.id, label: String(m.params.champion), odds: yes.odds };
    }
    return { ...map, ...created };
  }, [event.markets, created]);

  const label = `${event.team_a?.code ?? "TBD"} vs ${event.team_b?.code ?? "TBD"}`;
  const code = (s: Side) => (s === "A" ? event.team_a?.code : event.team_b?.code) ?? s;
  const scopes = grid?.scopes ?? (["picked", "A", "B"] as Scope[]);
  const canSelect = (grid?.champions ?? []).some((c) => c.roles && (c.roles.A || c.roles.B));
  const q = query.trim().toLowerCase();
  const priceOf = (c: GridChampion) => (mode === "select" ? c.roles?.[slot.side]?.[slot.role] ?? null : c.odds[scope] ?? null);
  const shown = (grid?.champions ?? []).filter(
    (c) => (mode === "select" || role === "all" || c.role === role) && (!q || c.label.toLowerCase().includes(q)) && priceOf(c),
  );
  const lock = grid?.close_at ? countdown(grid.close_at, now) : null;
  const byLabel = Object.fromEntries((grid?.champions ?? []).map((c) => [c.champion, c.label]));

  // What sits in each champ select slot: the selected role pick on the slip for that side and role.
  const filled = (side: Side, r: string) =>
    Object.entries(known).find(([k, v]) => k.startsWith(`${game}:`) && k.endsWith(`:${side}:${r}`) && slip.isSelected(v.outcomeId));
  // A champion can only be in one slot of a game: champion -> the other slot that holds it ("GEN mid").
  const takenBy = new Map<string, string>();
  if (mode === "select") {
    for (const sd of ["A", "B"] as const) {
      for (const x of ROLES) {
        const f = filled(sd, x.id);
        if (f && !(sd === slot.side && x.id === slot.role)) takenBy.set(f[1].label, `${code(sd)} ${x.short}`);
      }
    }
  }

  async function tap(c: GridChampion) {
    if (takenBy.has(c.champion)) return;
    const s: Scope = mode === "select" ? slot.side : scope;
    const r = mode === "select" ? slot.role : undefined;
    const key = keyOf(game, c.champion, s, r);
    const existing = known[key];
    if (existing && slip.isSelected(existing.outcomeId)) return slip.remove(existing.outcomeId);
    setBusy(key);
    setError(null);
    try {
      const body = { game_index: game, champion: c.champion, scope: s, ...(r ? { role: r } : {}) };
      const market = await api<MarketT>(`/events/${event.id}/draft`, { method: "POST", json: body });
      const yes = market.outcomes.find((o) => o.code === "YES");
      if (!yes) return;
      if (mode === "select") {
        const prev = filled(slot.side, slot.role);
        if (prev) slip.remove(prev[1].outcomeId); // one champion per slot
      }
      setCreated((p) => ({ ...p, [key]: { outcomeId: yes.id, label: c.champion, odds: yes.odds } }));
      slip.toggle(market, yes, label);
      if (mode === "select") {
        const order = (["A", "B"] as const).flatMap((sd) => ROLES.map((x) => ({ side: sd, role: x.id })));
        const next = order.find((o) => !(o.side === slot.side && o.role === slot.role) && !filled(o.side, o.role));
        if (next) setSlot(next);
      }
    } catch (e) {
      setError({ text: e instanceof ApiError ? e.message : `Couldn't get a price for ${c.label}.`, retry: c });
    } finally {
      setBusy(null);
    }
  }

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

  const scopeLabel = (s: Scope) =>
    s === "picked" ? "Picked" : s === "banned" ? "Banned" : s === "first" ? "First pick" : `By ${code(s)}`;

  return (
    <div>
      {event.best_of > 1 && fixedGame === undefined ? (
        <div className="chips" role="group" aria-label="Game" style={{ marginTop: 12 }}>
          {Array.from({ length: event.best_of }, (_, i) => i + 1).map((g) => (
            <button key={g} className="chip" aria-pressed={g === game} onClick={() => setGame(g)}>
              Game {g}
            </button>
          ))}
        </div>
      ) : null}

      {canSelect ? (
        <div className="segmented" role="group" aria-label="Mode" style={{ marginTop: 12 }}>
          <button aria-pressed={mode === "grid"} onClick={() => setMode("grid")}>Any champion</button>
          <button aria-pressed={mode === "select"} onClick={() => setMode("select")}>Champ select</button>
        </div>
      ) : null}

      {mode === "grid" ? (
        <div className="chips" role="group" aria-label="What to call" style={{ marginTop: 10 }}>
          {scopes.map((s) => (
            <button key={s} className="chip" aria-pressed={scope === s} onClick={() => setScope(s)}>
              {scopeLabel(s)}
            </button>
          ))}
        </div>
      ) : (
        <div className="slots">
          {(["A", "B"] as const).map((side) => (
            <div key={side}>
              <div className="eyebrow" style={{ marginBottom: 6 }}>{code(side)}</div>
              {ROLES.map((r) => {
                const f = filled(side, r.id);
                const active = slot.side === side && slot.role === r.id;
                return (
                  <button key={r.id} className={`slot${f ? " filled" : ""}`} aria-pressed={active} onClick={() => setSlot({ side, role: r.id })}>
                    <span className="r">{r.short}</span>
                    <span className="c">{f ? byLabel[f[1].label] ?? f[1].label : "Empty"}</span>
                    {f ? <span className="px num">{fmtOdds(f[1].odds)}</span> : null}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}

      {grid && !grid.open ? (
        <div className="window-note">
          {game === 1 ? "Draft picks for this series are closed." : `Game ${game} opens when Game ${game - 1} ends — about 8 minutes before its draft.`}
        </div>
      ) : (
        <div className="muted" style={{ fontSize: 13, marginTop: 10 }}>
          {mode === "select"
            ? `Tap a slot, then a champion: "${code(slot.side)} play it ${slot.role}". Each filled slot is its own pick.`
            : lock
              ? `Game ${game} picks lock in ${lock}${game === 1 ? ", or as soon as the match goes live" : ""}.`
              : null}
        </div>
      )}

      <label className="searchbox">
        <span className="sr-only">Search champions</span>
        <input placeholder={`Search ${grid?.champions.length ?? ""} champions`} value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      {mode === "grid" ? (
        <div className="chips" style={{ marginTop: 8 }}>
          {[{ id: "all", label: "All" }, ...ROLES].map((r) => (
            <button key={r.id} className="chip" aria-pressed={role === r.id} onClick={() => setRole(r.id)}>
              {r.label}
            </button>
          ))}
        </div>
      ) : null}

      {error ? <RetryNotice text={error.text} onRetry={() => tap(error.retry)} /> : null}

      {!grid ? (
        <div className="skeleton" style={{ marginTop: 12, height: 200 }} />
      ) : shown.length === 0 ? (
        <p className="muted" style={{ marginTop: 12, fontSize: 14 }}>No champions match.</p>
      ) : (
        <div className="cgrid" role="group" aria-label="Champions · arrow keys move between them" onKeyDown={gridKeys}>
          {shown.map((c, i) => {
            const s: Scope = mode === "select" ? slot.side : scope;
            const key = keyOf(game, c.champion, s, mode === "select" ? slot.role : undefined);
            const k = known[key];
            const px = priceOf(c);
            const taken = takenBy.get(c.champion);
            const loading = busy === key;
            return (
              <button
                key={c.champion}
                className={`ctile${loading ? " busy" : ""}`}
                aria-pressed={k ? slip.isSelected(k.outcomeId) : false}
                aria-busy={loading || undefined}
                disabled={!grid.open || loading || !!taken}
                tabIndex={i === Math.min(focusAt, shown.length - 1) ? 0 : -1}
                onFocus={() => setFocusAt(i)}
                onClick={() => tap(c)}
                aria-label={taken
                  ? `${c.label}, already in ${taken}`
                  : `${c.label}, ${mode === "select" ? `${code(slot.side)} ${slot.role}` : scopeLabel(scope)}, Game ${game}, ${oddsSpoken(px)}`}
              >
                <ChampIcon id={c.champion} label={c.label} />
                <span className="nm">{c.label}</span>
                <span className="px num">{taken ? `In ${taken}` : loading ? <span className="spinner" aria-hidden="true" /> : fmtOdds(px)}</span>
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
