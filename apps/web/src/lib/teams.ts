import type { Team } from "./types";

// Display names come from the API (rift.display), so every screen and every market label agree.
export function teamName(team: Pick<Team, "name"> | null | undefined): string {
  return team?.name ?? "TBD";
}

export function teamCode(team: Pick<Team, "code"> | null | undefined): string {
  return team?.code ?? "TBD";
}
