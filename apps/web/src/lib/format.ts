const rcFmt = new Intl.NumberFormat("en-US");

export const rc = (n: number) => rcFmt.format(n);

export const odds = (o: string | null) => (o ? Number(o).toFixed(2) : "—");

/** Mirrors the server's ROUND_HALF_UP whole-RC return. Display only; the server quote is authoritative. */
export function potentialReturn(stake: number, o: string): number {
  const cents = Math.round(Number(o) * 100);
  return Math.floor((stake * cents + 50) / 100);
}

/** Right side, wrong exact result: stake × odds × share, ROUND_HALF_UP like the server. */
export function partialReturn(stake: number, o: string, share: string): number {
  const cents = Math.round(Number(o) * 100);
  const bp = Math.round(Number(share) * 10000);
  return Math.floor((stake * cents * bp + 500000) / 1000000);
}

export function kickoff(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function dayLabel(isoDate: string): { dow: string; date: string } {
  const d = new Date(isoDate + "T12:00:00");
  return {
    dow: d.toLocaleDateString([], { weekday: "short" }),
    date: d.toLocaleDateString([], { month: "short", day: "numeric" }),
  };
}

export function longDate(isoDate: string): string {
  return new Date(isoDate + "T12:00:00").toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
}

export function countdown(iso: string, now: number): string | null {
  const ms = new Date(iso).getTime() - now;
  if (ms <= 0) return null;
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

export function venueToday(timezone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}
