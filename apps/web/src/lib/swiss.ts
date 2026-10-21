import type { EventT, Team } from "./types";

/** Where a Swiss Board call stands, given the team's record so far ("2-1"). */
export type SwissChance = { tone: "win" | "live" | "loss"; text: string };

export function swissChance(called: string, now: string): SwissChance {
  const [cw, cl] = called.split("-").map(Number);
  const [w, l] = now.split("-").map(Number);
  const advances = cw === 3;
  if (w === 3 || l === 3) {
    if (w === cw && l === cl) return { tone: "win", text: "Exact" };
    if ((w === 3) === advances) return { tone: "win", text: "Right side" };
    return { tone: "loss", text: "Missed" };
  }
  // Until the team finishes, the right side is always still possible; the exact record may not be.
  if (w <= cw && l <= cl) return { tone: "live", text: "Exact still possible" };
  return { tone: "live", text: advances ? "Right side if it advances" : "Right side if it goes out" };
}

export const dash = (record: string) => record.replace("-", "–");

/** Matches per Swiss round for sixteen teams: 8, 8, 8, then 6 and 3 as teams finish. */
export const ROUND_SIZES = [8, 8, 8, 6, 3];

export type SwissPool = { record: string; matches: EventT[] };
export type SwissRound = { index: number; pools: SwissPool[]; toDraw: number; done: boolean };
export type SwissFinish = { team: Team; record: string };

/**
 * The live Swiss board from the stage's matches: each round split into pools by the record both teams
 * carried into it. Matches not drawn yet fill the rounds in schedule order.
 */
export function swissRounds(events: EventT[]): { rounds: SwissRound[]; advanced: SwissFinish[]; out: SwissFinish[] } {
  const sorted = [...events].sort((a, b) => Date.parse(a.scheduled_at) - Date.parse(b.scheduled_at));
  const record = new Map<string, [number, number]>();
  const played = new Map<string, number>();
  const teams = new Map<string, Team>();
  const pools: Map<string, EventT[]>[] = ROUND_SIZES.map(() => new Map());
  let undrawn = 0;
  for (const e of sorted) {
    if (!e.team_a || !e.team_b) {
      undrawn++;
      continue;
    }
    const [a, b] = [e.team_a, e.team_b];
    teams.set(a.id, a).set(b.id, b);
    const round = Math.min(Math.max(played.get(a.id) ?? 0, played.get(b.id) ?? 0), ROUND_SIZES.length - 1);
    const [w, l] = record.get(a.id) ?? [0, 0];
    const key = `${w}-${l}`;
    pools[round].set(key, [...(pools[round].get(key) ?? []), e]);
    played.set(a.id, (played.get(a.id) ?? 0) + 1).set(b.id, (played.get(b.id) ?? 0) + 1);
    if (e.status === "COMPLETED" && e.winner) {
      const [win, loss] = e.winner === "A" ? [a, b] : [b, a];
      const rw = record.get(win.id) ?? [0, 0];
      const rl = record.get(loss.id) ?? [0, 0];
      record.set(win.id, [rw[0] + 1, rw[1]]).set(loss.id, [rl[0], rl[1] + 1]);
    }
  }
  const rounds = ROUND_SIZES.map((size, i) => {
    const list = [...pools[i].entries()]
      .map(([rec, matches]) => ({ record: rec, matches }))
      .sort((x, y) => Number(y.record[0]) - Number(x.record[0]) || Number(x.record[2]) - Number(y.record[2]));
    const drawn = list.reduce((s, p) => s + p.matches.length, 0);
    const toDraw = Math.min(Math.max(size - drawn, 0), undrawn);
    undrawn -= toDraw;
    const done = drawn === size && list.every((p) => p.matches.every((m) => m.status === "COMPLETED"));
    return { index: i + 1, pools: list, toDraw, done };
  });
  const finish = (pred: (w: number, l: number) => boolean) =>
    [...record.entries()]
      .filter(([, [w, l]]) => pred(w, l))
      .map(([id, [w, l]]) => ({ team: teams.get(id)!, record: `${w}-${l}` }))
      .sort((x, y) => Number(y.record[0]) - Number(x.record[0]) || Number(x.record[2]) - Number(y.record[2]));
  return { rounds, advanced: finish((w) => w === 3), out: finish((_, l) => l === 3) };
}
