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
