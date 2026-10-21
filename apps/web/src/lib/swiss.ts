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

/** One box on the board: a pool of matches on the same record, or the teams that finished on a record. */
export type SwissCell = { kind: "pool" | "finish"; record: string; slots: number };

/** The official Swiss layout: a column per round, finished teams beside the round that decides them. */
export const SWISS_COLUMNS: { title: string; cells: SwissCell[] }[] = [
  { title: "Round 1", cells: [{ kind: "pool", record: "0-0", slots: 8 }] },
  { title: "Round 2", cells: [{ kind: "pool", record: "1-0", slots: 4 }, { kind: "pool", record: "0-1", slots: 4 }] },
  { title: "Round 3", cells: [{ kind: "pool", record: "2-0", slots: 2 }, { kind: "pool", record: "1-1", slots: 4 }, { kind: "pool", record: "0-2", slots: 2 }] },
  {
    title: "Round 4",
    cells: [
      { kind: "finish", record: "3-0", slots: 2 },
      { kind: "pool", record: "2-1", slots: 3 },
      { kind: "pool", record: "1-2", slots: 3 },
      { kind: "finish", record: "0-3", slots: 2 },
    ],
  },
  { title: "Round 5", cells: [{ kind: "finish", record: "3-1", slots: 3 }, { kind: "pool", record: "2-2", slots: 3 }, { kind: "finish", record: "1-3", slots: 3 }] },
  { title: "Final", cells: [{ kind: "finish", record: "3-2", slots: 3 }, { kind: "finish", record: "2-3", slots: 3 }] },
];

/** Drawn Swiss matches by the record both teams carried into them, and teams by the record they finished on. */
export function swissBoard(events: EventT[]): { pools: Map<string, EventT[]>; finished: Map<string, Team[]>; current: number } {
  const sorted = [...events].sort((a, b) => Date.parse(a.scheduled_at) - Date.parse(b.scheduled_at));
  const record = new Map<string, [number, number]>();
  const teams = new Map<string, Team>();
  const pools = new Map<string, EventT[]>();
  for (const e of sorted) {
    if (!e.team_a || !e.team_b) continue; // not drawn yet: its slot stays TBD
    const [a, b] = [e.team_a, e.team_b];
    teams.set(a.id, a).set(b.id, b);
    const [w, l] = record.get(a.id) ?? [0, 0];
    pools.set(`${w}-${l}`, [...(pools.get(`${w}-${l}`) ?? []), e]);
    if (e.status === "COMPLETED" && e.winner) {
      const [win, loss] = e.winner === "A" ? [a, b] : [b, a];
      const rw = record.get(win.id) ?? [0, 0];
      const rl = record.get(loss.id) ?? [0, 0];
      record.set(win.id, [rw[0] + 1, rw[1]]).set(loss.id, [rl[0], rl[1] + 1]);
    }
  }
  const finished = new Map<string, Team[]>();
  for (const [id, [w, l]] of record) {
    if (w === 3 || l === 3) finished.set(`${w}-${l}`, [...(finished.get(`${w}-${l}`) ?? []), teams.get(id)!]);
  }
  // The round being played: the first whose pools aren't all drawn and finished.
  const current = SWISS_COLUMNS.findIndex(({ cells }) =>
    cells.some((c) => c.kind === "pool" && ((pools.get(c.record)?.length ?? 0) < c.slots || pools.get(c.record)!.some((e) => e.status !== "COMPLETED"))),
  );
  return { pools, finished, current: current < 0 ? SWISS_COLUMNS.length - 1 : current };
}
