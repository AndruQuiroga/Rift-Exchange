import type { Team } from "./types";

// Provider names are inconsistent ("BILIBILI GAMING", "Hanwha Life Esports", "Gen.G Esports").
// One display table keeps every screen consistent; anything unlisted falls back to tidy casing.
const DISPLAY: Record<string, string> = {
  GEN: "Gen.G",
  HLE: "Hanwha Life",
  BLG: "Bilibili Gaming",
  TES: "Top Esports",
  AL: "Anyone's Legend",
  IG: "Invictus Gaming",
  DK: "Dplus KIA",
  KC: "Karmine Corp",
  MVK: "MVK Esports",
  C9: "Cloud9",
  G2: "G2 Esports",
  FLY: "FlyQuest",
  FUR: "FURIA",
  CFO: "CTBC Flying Oyster",
  T1: "T1",
};

function tidy(name: string): string {
  if (name !== name.toUpperCase() || name.length <= 4) return name;
  return name.toLowerCase().replace(/\b\p{L}/gu, (c) => c.toUpperCase());
}

export function teamName(team: Pick<Team, "code" | "name"> | null | undefined): string {
  if (!team) return "TBD";
  return DISPLAY[team.code] ?? tidy(team.name);
}

export function teamCode(team: Pick<Team, "code"> | null | undefined): string {
  return team?.code ?? "TBD";
}
