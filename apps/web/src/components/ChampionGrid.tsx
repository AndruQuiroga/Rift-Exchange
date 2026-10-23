"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { api, ApiError } from "@/lib/api";
import { countdown, oddsSpoken } from "@/lib/format";
import { useNow, usePlaced } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import type { EventT, MarketT } from "@/lib/types";
import { RetryNotice } from "./bits";
import { IconCheck, IconLock } from "./icons";
import { Sheet } from "./MorePicks";
import { Odds } from "./Odds";
import { LockTimer } from "./Timing";

// "Picked by either team" is the one draft call offered; existing picks on other draft markets still settle.
type Scope = "picked";
type GridChampion = {
  champion: string;
  label: string;
  role: string | null;
  odds: Partial<Record<Scope, string | null>>;
  /** Once the game has loaded: whether it was actually picked (D-032). */
  picked?: boolean | null;
};
type Grid = {
  game_index: number;
  open: boolean;
  close_at: string | null;
  games_observed: number;
  burned: { champion: string; label: string }[];
  champions: GridChampion[];
  drafted?: { champion: string; label: string; role: string | null }[];
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

/** "Who gets picked?": a carousel of champion cards. Filter by role, swipe or use the arrows; your calls
 * come first, then the likeliest picks. Every priced champion is in it; search lives in "All champions". */
export function ChampionRow({ event, game }: { event: EventT; game: number }) {
  const { grid, tap, state, notice } = useDraft(event, game);
  const [all, setAll] = useState(false);
  const [role, setRole] = useState("all");
  const [at, setAt] = useState(0);
  const track = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setAll(false), []);
  if (!grid) return <div className="skeleton" style={{ height: 196 }} />;
  const locked = !grid.open;
  const known = grid.champions.some((c) => c.picked != null);
  if (locked && game > 1 && !grid.close_at && !known) {
    return <p className="muted" style={{ fontSize: 13 }}>Game {game} draft picks open when Game {game - 1} ends.</p>;
  }
  const priced = grid.champions.filter((c) => c.odds.picked && (role === "all" || c.role === role));
  const mine = priced.filter((c) => state(c, "picked").selected || state(c, "picked").placed);
  // Locked with the draft known: your calls, then what was actually picked, then the rest.
  const hit = (c: GridChampion) => (c.picked ? 0 : 1);
  const rest = priced.filter((c) => !mine.includes(c)).sort((x, y) => (known ? hit(x) - hit(y) : 0) || Number(x.odds.picked) - Number(y.odds.picked));
  const cards = [...mine, ...rest];

  // Step one card at a time; the counter follows whichever card sits at the start after a swipe.
  const step = (dir: 1 | -1) => {
    const el = track.current;
    const card = el?.querySelector<HTMLElement>(".champ-card");
    if (!el || !card) return;
    el.scrollBy({ left: dir * (card.offsetWidth + 10), behavior: "smooth" });
  };
  const onScroll = () => {
    const el = track.current;
    const card = el?.querySelector<HTMLElement>(".champ-card");
    if (el && card) setAt(Math.round(el.scrollLeft / (card.offsetWidth + 10)));
  };
  const pickRole = (r: string) => {
    setRole(r);
    setAt(0);
    track.current?.scrollTo({ left: 0 });
  };

  return (
    <>
      {locked ? (
        <div className="lock-banner" role="status">
          <IconLock width={14} height={14} aria-hidden="true" />
          <span>
            <b>Draft locked.</b>{" "}
            {known ? "The draft is in: picked champions are marked." : "Picks closed before the draft started. Your calls stand."}
          </span>
        </div>
      ) : (
        <div className="champ-lock"><LockTimer at={grid.close_at} label="Draft picks lock in" /></div>
      )}
      <div className="chips champ-roles" role="group" aria-label="Role">
        {[{ id: "all", label: "All" }, ...ROLES].map((r) => (
          <button key={r.id} className="chip" aria-pressed={role === r.id} onClick={() => pickRole(r.id)}>
            {r.label}
          </button>
        ))}
      </div>
      <div className="champ-carousel">
        <button type="button" className="champ-arrow" aria-label="Previous champions" disabled={at <= 0} onClick={() => step(-1)}>‹</button>
        <div className={`champ-row${locked ? " locked" : ""}`} ref={track} onScroll={onScroll} role="group" aria-label={`Champions picked in Game ${game}`}>
          {cards.map((c) => {
            const s = state(c, "picked");
            const verdict = c.picked === true ? "hit" : c.picked === false ? "miss" : "";
            return (
              <button
                key={c.champion}
                type="button"
                className={`champ-card${verdict ? ` ${verdict}` : ""}`}
                aria-pressed={s.selected}
                data-held={s.placed || undefined}
                aria-busy={s.busy || undefined}
                disabled={s.busy || locked}
                onClick={() => tap(c, "picked")}
                aria-label={`${c.label} picked in Game ${game}, ${locked ? (c.picked === true ? "picked" : c.picked === false ? "not picked" : "locked") : oddsSpoken(c.odds.picked ?? null)}${s.selected ? ", in slip" : ""}${s.placed ? ", already placed" : ""}`}
              >
                <ChampIcon id={c.champion} label={c.label} />
                <span className="nm">{c.label}</span>
                <span className="px num">
                  {s.busy ? <span className="spinner" aria-hidden="true" /> : s.selected ? <><IconCheck width={13} height={13} aria-hidden="true" /> <Odds value={c.odds.picked ?? null} /></> : <Odds value={c.odds.picked ?? null} />}
                </span>
                {s.placed && !s.selected ? <span className="pk-tag">Placed</span> : null}
                {verdict ? <span className={`verdict ${verdict}`}>{verdict === "hit" ? "Picked" : "Not picked"}</span> : null}
              </button>
            );
          })}
          {cards.length === 0 ? <p className="muted" style={{ fontSize: 13, padding: "12px 0" }}>No priced champions for this role yet.</p> : null}
        </div>
        <button type="button" className="champ-arrow" aria-label="Next champions" disabled={at >= cards.length - 2} onClick={() => step(1)}>›</button>
      </div>
      <div className="champ-foot">
        <span className="muted num">{cards.length ? `${Math.min(at + 1, cards.length)} of ${cards.length}` : ""}{mine.length ? ` · ${mine.length} called` : ""}</span>
        <button type="button" className="all-champs" onClick={() => setAll(true)}>
          Search all {grid.champions.length}
        </button>
      </div>
      {notice}
      {all ? (
        <Sheet title={`Game ${game} draft`} tabs={[{ id: "draft", label: "Draft", body: <ChampionGrid event={event} game={game} /> }]} tab="draft" setTab={() => {}} onClose={close} />
      ) : null}
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
