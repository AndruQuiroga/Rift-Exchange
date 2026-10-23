"use client";

import { useEffect, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { api, ApiError } from "@/lib/api";
import { initials, useFriendsOnMatch } from "@/lib/friends";
import { rc } from "@/lib/format";
import { useMe } from "@/lib/hooks";
import { initialsOf, useToast } from "@/lib/toasts";
import type { EventT, Pick, ReactionT, TableRow } from "@/lib/types";
import { LockTimer } from "./Timing";

const PHRASES: { id: string; text: string }[] = [
  { id: "called_it", text: "Called it" },
  { id: "sweating", text: "You're sweating" },
  { id: "bold_call", text: "Bold call" },
  { id: "gg", text: "GG" },
];

function Avatar({ name, you, size = 30 }: { name: string; you?: boolean; size?: number }) {
  return (
    <span className={`av${you ? " you" : ""}`} style={{ width: size, height: size, fontSize: Math.round(size / 2.8) }} aria-hidden="true">
      {you ? "You" : initials(name)}
    </span>
  );
}

/** Your own picks on this match (open and settled). */
function useMyPicks(eventId: string) {
  const { data } = useSWR<{ picks: Pick[] }>("/me/picks");
  return { loaded: !!data, mine: (data?.picks ?? []).filter((p) => p.event?.id === eventId) };
}

/** Friends on this match: who backs which side, the table, and each friend's picks with or against yours. */
export function RivalsPanel({ event }: { event: EventT }) {
  const { data: me } = useMe();
  const { picks, pending, table, reactions } = useFriendsOnMatch(event.id);
  const { mine } = useMyPicks(event.id);
  const myName = me?.user.display_name ?? "You";
  if (!picks.length && !pending.length) {
    return (
      <section className="rivals" aria-label="Friends on this match">
        <h2 className="rv-h">Rivals</h2>
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>No friends on this match yet. Picks show to each other when betting locks.</p>
      </section>
    );
  }
  const winner = (event.markets ?? []).find((m) => m.kind === "series_winner");
  const backers = (code: "A" | "B") => {
    const o = winner?.outcomes.find((x) => x.code === code);
    if (!o) return { names: [] as string[], stake: 0, you: false };
    const fr = picks.filter((p) => p.outcome_id === o.id);
    const you = mine.find((p) => p.outcome_id === o.id);
    return { names: [...new Set(fr.map((p) => p.user?.display_name ?? "A friend"))], stake: fr.reduce((n, p) => n + p.stake_rc, 0) + (you?.stake_rc ?? 0), you: !!you };
  };
  const a = backers("A"), b = backers("B");
  const stance = (p: Pick) => {
    const m = mine.find((x) => x.market_id === p.market_id);
    return !m ? null : m.outcome_id === p.outcome_id ? "with" : "against";
  };
  // Against you first, then with you, then the rest.
  const order = { against: 0, with: 1, none: 2 } as const;
  const sorted = [...picks].sort((x, y) => order[stance(x) ?? "none"] - order[stance(y) ?? "none"]);

  return (
    <section className="rivals" aria-label="Friends on this match">
      <h2 className="rv-h">Rivals</h2>

      {a.names.length || b.names.length || a.you || b.you ? (
        <div className="sides">
          <div>
            <span className="stack">{a.you ? <Avatar name={myName} you /> : null}{a.names.slice(0, 3).map((n) => <Avatar key={n} name={n} />)}</span>
            <span className="sd-k">Backing <b>{event.team_a?.code}</b>{a.stake ? ` · ${rc(a.stake)}` : ""}</span>
          </div>
          <span className="sd-vs">VS</span>
          <div className="right">
            <span className="stack">{b.names.slice(0, 3).map((n) => <Avatar key={n} name={n} />)}{b.you ? <Avatar name={myName} you /> : null}</span>
            <span className="sd-k">Backing <b>{event.team_b?.code}</b>{b.stake ? ` · ${rc(b.stake)}` : ""}</span>
          </div>
        </div>
      ) : null}

      {pending.map((r) => (
        <div className="fp-row" key={r.user.handle}>
          <Avatar name={r.user.display_name} size={26} />
          <span style={{ minWidth: 0, flex: 1 }}><b>{r.user.display_name}</b><span className="muted"> · {r.picks} hidden</span></span>
          <LockTimer at={r.reveals_at} label="Reveals in" compact />
        </div>
      ))}

      {table && table.length > 1 ? <MatchTable rows={table} /> : null}

      {sorted.length ? (
        <div className="fpicks">
          {sorted.map((p) => (
            <FriendPick key={p.id} event={event} pick={p} stance={stance(p)} myHandle={me?.user.handle ?? ""}
              reactions={(reactions ?? []).filter((r) => r.selection_id === p.id)} />
          ))}
        </div>
      ) : null}

      {reactions?.length ? (
        <div className="trash">
          {reactions.slice(0, 3).map((r) => (
            <div className="tt-row" key={r.id}>
              <b>{r.from.display_name}</b> <span className="muted">to</span> {r.to.display_name}: <b className="tt-phrase">{r.text}</b>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function MatchTable({ rows }: { rows: TableRow[] }) {
  const top = Math.max(1, ...rows.map((r) => Math.abs(r.net)));
  return (
    <div className="mtable">
      {rows.map((r) => (
        <div className={`mt-row${r.you ? " you" : ""}`} key={r.user.handle}>
          <span className="mt-rank num">{r.rank}</span>
          <Avatar name={r.user.display_name} you={r.you} size={24} />
          <span className="mt-bar"><span className={r.net >= 0 ? "up" : "down"} style={{ width: `${Math.max(4, (Math.abs(r.net) / top) * 100)}%` }} /></span>
          <span className={`mt-net num ${r.net >= 0 ? "win" : "loss"}`}>{r.net >= 0 ? "+" : "−"}{rc(Math.abs(r.net))}</span>
        </div>
      ))}
    </div>
  );
}

/** One friend's pick: what and how much, with you or against you, and a reaction once it has locked. */
function FriendPick({ event, pick, stance, myHandle, reactions }: {
  event: EventT; pick: Pick; stance: "with" | "against" | null; myHandle: string; reactions: ReactionT[];
}) {
  const { mutate } = useSWRConfig();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const name = pick.user?.display_name ?? "A friend";
  const sent = new Set(reactions.filter((r) => r.from.handle === myHandle).map((r) => r.phrase));

  async function react(phrase: string) {
    setBusy(true);
    setError(null);
    try {
      await api(`/picks/${pick.id}/reactions`, { method: "POST", json: { phrase } });
      mutate(`/events/${event.id}/league`);
      setOpen(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't send that.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`fpick${stance ? ` ${stance}` : ""}`}>
      <div className="fpick-row">
        <Avatar name={name} size={28} />
        <span className="fpick-main">
          <b>{pick.outcome_label}</b>
          <span className="muted">{name} · {pick.market_title} · {rc(pick.stake_rc)}</span>
        </span>
        {stance ? <span className={`stance ${stance}`}>{stance === "with" ? "With you" : "Against"}</span> : null}
        <button type="button" className="react-open" aria-expanded={open} aria-label={`React to ${name}`} onClick={() => setOpen(!open)}>
          {sent.size ? "Sent" : "React"}
        </button>
      </div>
      {open ? (
        <div className="fpick-react" role="group" aria-label={`React to ${name}`}>
          {PHRASES.map((ph) => (
            <button key={ph.id} type="button" className="react" aria-pressed={sent.has(ph.id)} disabled={busy || sent.has(ph.id)} onClick={() => react(ph.id)}>
              {ph.text}
            </button>
          ))}
          {error ? <span className="loss" style={{ fontSize: 12 }}>{error}</span> : null}
        </div>
      ) : null}
    </div>
  );
}

/** One toast for the rivalry: a friend revealed against you at lock. Nothing already true on page load. */
export function RivalToasts({ event }: { event: EventT }) {
  const toast = useToast();
  const { loaded, picks } = useFriendsOnMatch(event.id);
  const { loaded: mineLoaded, mine } = useMyPicks(event.id);
  const seen = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!loaded || !mineLoaded) return;
    if (seen.current === null) {
      seen.current = new Set(picks.map((p) => p.id));
      return;
    }
    for (const p of picks) {
      if (seen.current.has(p.id)) continue;
      seen.current.add(p.id);
      const m = mine.find((x) => x.market_id === p.market_id);
      if (!m || m.outcome_id === p.outcome_id) continue;
      const name = p.user?.display_name ?? "A friend";
      toast({ key: `revealed:${p.id}`, tone: "rival", badge: initialsOf(name), badgeRound: true, kicker: p.market_title,
              text: `${name} is against you: ${p.outcome_label}` });
    }
  }, [loaded, mineLoaded, picks, mine, toast]);
  return null;
}
