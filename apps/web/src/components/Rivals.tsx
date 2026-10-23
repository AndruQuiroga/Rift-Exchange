"use client";

import { useEffect, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { api, ApiError } from "@/lib/api";
import { initials, useFriendsOnMatch } from "@/lib/friends";
import { odds as fmtOdds, potentialReturn, rc } from "@/lib/format";
import { useMe, useNow } from "@/lib/hooks";
import { initialsOf, useToast } from "@/lib/toasts";
import type { EventT, MarketT, Pick, ReactionT } from "@/lib/types";
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

/** Your own picks on this match (open and settled), with their prices. */
function useMyPicksOn(eventId: string) {
  const { data } = useSWR<{ picks: Pick[] }>("/me/picks");
  return (data?.picks ?? []).filter((p) => p.event?.id === eventId);
}

function useMyPicksLoaded() {
  return !!useSWR<{ picks: Pick[] }>("/me/picks").data;
}

/** Friends on this match, adversarially: sides, the live table, head to heads with reactions, trash talk. */
export function RivalsPanel({ event }: { event: EventT }) {
  const { data: me } = useMe();
  const { picks, pending, table, reactions } = useFriendsOnMatch(event.id);
  const mine = useMyPicksOn(event.id);
  const markets = new Map((event.markets ?? []).map((m) => [m.id, m]));
  const myName = me?.user.display_name ?? "You";
  if (!picks.length && !pending.length && !(table ?? []).some((r) => !r.you)) {
    return (
      <section className="rivals empty-rivals" aria-label="Friends on this match">
        <h2 className="rv-h">Rivals</h2>
        <p className="muted" style={{ fontSize: 13 }}>No friends on this match yet. Your picks show up for them when betting locks.</p>
      </section>
    );
  }

  // Head to head: a market where you and a friend hold different sides; squad: the same side.
  const h2h: { market: MarketT; me: Pick; them: Pick }[] = [];
  const squad: { market: MarketT; me: Pick; them: Pick[] }[] = [];
  for (const m of mine) {
    const market = markets.get(m.market_id);
    if (!market) continue;
    const others = picks.filter((p) => p.market_id === m.market_id);
    for (const o of others.filter((p) => p.outcome_id !== m.outcome_id)) h2h.push({ market, me: m, them: o });
    const same = others.filter((p) => p.outcome_id === m.outcome_id);
    if (same.length) squad.push({ market, me: m, them: same });
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

      {pending.length ? (
        <div className="rv-pending">
          {pending.map((r) => (
            <div className="fp-row" key={r.user.handle}>
              <Avatar name={r.user.display_name} />
              <span style={{ minWidth: 0, flex: 1 }}><b>{r.user.display_name}</b><span className="muted"> · {r.picks} hidden pick{r.picks === 1 ? "" : "s"}</span></span>
              <LockTimer at={r.reveals_at} label="Reveals in" />
            </div>
          ))}
        </div>
      ) : null}

      {table && table.length > 1 ? <MatchTable rows={table} /> : null}

      {h2h.map(({ market, me: m, them }) => (
        <HeadToHead key={`${market.id}:${them.id}`} event={event} market={market} me={m} them={them} myName={myName} myHandle={me?.user.handle ?? ""}
          reactions={(reactions ?? []).filter((r) => r.selection_id === them.id || r.selection_id === m.id)} />
      ))}

      {squad.map(({ market, me: m, them }) => (
        <div className="squad reveal" key={market.id}>
          <div className="sq-top"><span className="rv-tag good">SQUAD PICK</span><span className="muted">{market.title}</span></div>
          <div className="sq-body">
            <span className="stack"><Avatar name={myName} you size={32} />{them.map((p) => <Avatar key={p.id} name={p.user?.display_name ?? "?"} size={32} />)}</span>
            <span>You and {them.map((p) => p.user?.display_name).join(", ")} took <b>{m.outcome_label}</b>.</span>
          </div>
        </div>
      ))}

      <OtherPicks picks={picks.filter((p) => !mine.some((m) => m.market_id === p.market_id))} />

      {reactions?.length ? (
        <div className="trash">
          <h3 className="rv-sub">Trash talk</h3>
          {reactions.slice(0, 8).map((r) => (
            <div className="tt-row reveal" key={r.id}>
              <b>{r.from.display_name}</b> → {r.to.display_name}: <b className="tt-phrase">{r.text}</b> <span className="muted">on {r.pick}</span>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function MatchTable({ rows }: { rows: NonNullable<ReturnType<typeof useFriendsOnMatch>["table"]> }) {
  const top = Math.max(1, ...rows.map((r) => Math.abs(r.net)));
  return (
    <div className="mtable">
      <div className="mt-head"><span>If it ended now</span><span className="muted">decided picks</span></div>
      {rows.map((r) => (
        <div className={`mt-row${r.you ? " you" : ""}`} key={r.user.handle}>
          <span className="mt-rank num">{r.rank}</span>
          <Avatar name={r.user.display_name} you={r.you} size={26} />
          <span className="mt-bar"><span className={r.net >= 0 ? "up" : "down"} style={{ width: `${Math.max(4, (Math.abs(r.net) / top) * 100)}%` }} /></span>
          <span className={`mt-net num ${r.net >= 0 ? "win" : "loss"}`}>{r.net >= 0 ? "+" : "−"}{rc(Math.abs(r.net))}</span>
        </div>
      ))}
    </div>
  );
}

function HeadToHead({ event, market, me, them, myName, myHandle, reactions }: {
  event: EventT; market: MarketT; me: Pick; them: Pick; myName: string; myHandle: string; reactions: ReactionT[];
}) {
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const theirName = them.user?.display_name ?? "A friend";
  const mineBack = potentialReturn(me.stake_rc, me.odds) - me.stake_rc;
  const theirsBack = potentialReturn(them.stake_rc, them.odds) - them.stake_rc;
  const r = market.result ?? market.call;
  const decided = r && !r.void ? (market.outcomes.find((o) => o.id === me.outcome_id && r.winning_codes.includes(o.code)) ? "me" : market.outcomes.find((o) => o.id === them.outcome_id && r.winning_codes.includes(o.code)) ? "them" : null) : null;
  const sent = new Set(reactions.filter((x) => x.selection_id === them.id && x.from.handle === myHandle).map((x) => x.phrase));
  const incoming = reactions.filter((x) => x.selection_id === me.id);

  async function react(phrase: string) {
    setBusy(phrase);
    setError(null);
    try {
      await api(`/picks/${them.id}/reactions`, { method: "POST", json: { phrase } });
      mutate(`/events/${event.id}/league`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't send that.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={`h2h-card reveal${decided ? ` ${decided === "me" ? "won" : "lost"}` : ""}`}>
      <div className="hh-top">
        <span className="rv-tag rival">HEAD TO HEAD</span>
        <span className="muted">{market.title}</span>
      </div>
      <div className="hh-vs">
        <div>
          <Avatar name={myName} you size={40} />
          <span className="hh-pick">{me.outcome_label}</span>
          <span className="muted num">{rc(me.stake_rc)} @ {fmtOdds(me.odds)}</span>
        </div>
        <span className="hh-x">VS</span>
        <div className="right">
          <Avatar name={theirName} size={40} />
          <span className="hh-pick">{them.outcome_label}</span>
          <span className="muted num">{rc(them.stake_rc)} @ {fmtOdds(them.odds)}</span>
        </div>
      </div>
      {decided ? (
        <div className={`hh-result ${decided === "me" ? "win" : "loss"}`}>
          {decided === "me" ? `You win this one: +${rc(mineBack)} · ${theirName} −${rc(them.stake_rc)}` : `${theirName} takes it: +${rc(theirsBack)} · you −${rc(me.stake_rc)}`}
        </div>
      ) : (
        <div className="hh-scen">
          <div className="me"><span>{me.outcome_label}</span><b className="num">You +{rc(mineBack)} · {theirName.split(" ")[0]} −{rc(them.stake_rc)}</b></div>
          <div className="them"><span>{them.outcome_label}</span><b className="num">{theirName.split(" ")[0]} +{rc(theirsBack)} · You −{rc(me.stake_rc)}</b></div>
        </div>
      )}
      {incoming.length ? (
        <div className="hh-said">{incoming.map((x) => <span key={x.id}><b>{x.from.display_name}:</b> &ldquo;{x.text}&rdquo;</span>)}</div>
      ) : null}
      <div className="hh-react" role="group" aria-label={`React to ${theirName}`}>
        {PHRASES.map((p) => (
          <button key={p.id} type="button" className="react" aria-pressed={sent.has(p.id)} disabled={busy !== null || sent.has(p.id)} onClick={() => react(p.id)}>
            {busy === p.id ? <span className="spinner" aria-hidden="true" /> : null}{p.text}
          </button>
        ))}
      </div>
      {error ? <p className="loss" style={{ fontSize: 12, margin: 0 }}>{error}</p> : null}
    </div>
  );
}

function OtherPicks({ picks }: { picks: Pick[] }) {
  if (!picks.length) return null;
  return (
    <details className="other-picks">
      <summary>{picks.length} other friend pick{picks.length === 1 ? "" : "s"} on this match</summary>
      {picks.map((p) => (
        <div className="op-row" key={p.id}>
          <Avatar name={p.user?.display_name ?? "?"} size={24} />
          <span style={{ minWidth: 0, flex: 1 }}><b>{p.outcome_label}</b> <span className="muted">· {p.market_title}</span></span>
          <span className="muted num">{rc(p.stake_rc)}</span>
        </div>
      ))}
    </details>
  );
}

/** Toasts for the rivalry: a friend revealed against you at lock, passing someone in the match table, and a
 * nudge when picks close in 30 seconds. Nothing toasts for what was already true when the page opened. */
export function RivalToasts({ event }: { event: EventT }) {
  const toast = useToast();
  const now = useNow(1000);
  const { loaded, picks, table } = useFriendsOnMatch(event.id);
  const mine = useMyPicksOn(event.id);
  const mineLoaded = useMyPicksLoaded();
  const seenPicks = useRef<Set<string> | null>(null);
  const lastRank = useRef<number | null>(null);

  useEffect(() => {
    if (!loaded || !mineLoaded) return; // what is already revealed when the page opens is not news
    if (seenPicks.current === null) {
      seenPicks.current = new Set(picks.map((p) => p.id));
      return;
    }
    for (const p of picks) {
      if (seenPicks.current.has(p.id)) continue;
      seenPicks.current.add(p.id);
      const m = mine.find((x) => x.market_id === p.market_id);
      if (!m) continue;
      const name = p.user?.display_name ?? "A friend";
      const against = m.outcome_id !== p.outcome_id;
      toast({
        key: `revealed:${p.id}`, tone: against ? "rival" : "good", badge: initialsOf(name), badgeRound: true,
        kicker: "Picks just locked",
        text: against ? `${name} is against you: ${rc(p.stake_rc)} RC on ${p.outcome_label}` : `${name} is with you on ${p.outcome_label}`,
      });
    }
  }, [loaded, mineLoaded, picks, mine, toast]);

  useEffect(() => {
    const me = table?.find((r) => r.you);
    if (!me || !table || table.length < 2) return;
    if (lastRank.current !== null && me.rank < lastRank.current) {
      const passed = table.find((r) => r.rank === me.rank + 1);
      toast({
        key: `rank:${event.id}:${me.rank}`, tone: "good", badge: "You", badgeRound: true, kicker: "Match table",
        text: passed ? `You just passed ${passed.user.display_name} for ${me.rank === 1 ? "first" : `#${me.rank}`}` : `You moved up to #${me.rank}`,
      });
    }
    lastRank.current = me.rank;
  }, [table, event.id, toast]);

  const soon = (event.markets ?? []).filter((m) => m.state === "OPEN" && Date.parse(m.close_at) - now > 0 && Date.parse(m.close_at) - now <= 30_000);
  useEffect(() => {
    for (const m of soon) {
      toast({
        key: `closing:${m.id}:${m.close_at}`, tone: "money", badge: "0:30", kicker: "Closing soon",
        text: `${m.title} locks in 30 seconds`,
      });
    }
  }, [soon.map((m) => m.id).join(), toast]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}
