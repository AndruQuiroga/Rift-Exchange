export type StakeLimit = { marketId: string; cap: number; placed: number; remaining: number };

/** Accept both the complete list and older servers that report only the first affected market. */
export function stakeLimits(details: Record<string, unknown>): StakeLimit[] {
  const rows = Array.isArray(details.violations) ? details.violations : [details];
  return rows.flatMap((row) => {
    if (!row || typeof row !== "object") return [];
    const { market_id, cap_rc, placed_rc, max_stake_rc } = row;
    if (typeof market_id !== "string" || !Number.isSafeInteger(cap_rc) || cap_rc < 0
      || !Number.isSafeInteger(max_stake_rc) || max_stake_rc < 0 || max_stake_rc > cap_rc) return [];
    return [{ marketId: market_id, cap: cap_rc,
      placed: Number.isSafeInteger(placed_rc) && placed_rc >= 0 ? placed_rc : cap_rc - max_stake_rc,
      remaining: max_stake_rc }];
  });
}
