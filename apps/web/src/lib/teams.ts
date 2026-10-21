import type { Team } from "./types";

// Display names come from the API (rift.display), so every screen and every market label agree.
export function teamName(team: Pick<Team, "name"> | null | undefined): string {
  return team?.name ?? "TBD";
}

export function teamCode(team: Pick<Team, "code"> | null | undefined): string {
  return team?.code ?? "TBD";
}

// Team colours for the winner face-off: each Worlds 2026 team's primary brand colour, darkened enough for
// white text. Unknown teams get a steady hue from their code, so a new team still has its own colour.
const COLORS: Record<string, string> = {
  GEN: "#8a6a1c", T1: "#a3172d", HLE: "#b4531b", KT: "#9e1b22", DK: "#1a6f73", BLG: "#1f4f9c",
  TES: "#a8261f", IG: "#23407e", AL: "#7a2a7f", JDG: "#a3172d", LNG: "#1c5f8a", WBG: "#7a5a1c",
  G2: "#3d3d45", FNC: "#b1541a", KC: "#1d4a8f", MKOI: "#3a2f7a", FUR: "#1e3a5f", C9: "#1666a8",
  FLY: "#1f6b4a", TLAW: "#1b3a6b", CFO: "#9a6a12", PSG: "#1d3c78", LOS: "#b3471d", VKS: "#a01f2a",
  MVK: "#2a5f8a", SHG: "#a3352b",
};

export function teamColor(team: Pick<Team, "code"> | null | undefined): string {
  const code = (team?.code ?? "").toUpperCase();
  if (COLORS[code]) return COLORS[code];
  let h = 0;
  for (const c of code) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 45% 30%)`;
}
