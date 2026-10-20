export type Team = { id: string; code: string; name: string; image_url: string | null; region: string | null };

export type OutcomeT = { id: string; code: string; label: string; odds: string | null; odds_version: number; probability: number | null };

export type MarketState = "OPEN" | "SUSPENDED" | "LOCKED" | "HOLD" | "SETTLED" | "VOID";

export type MarketT = {
  id: string;
  kind: string;
  scope: string;
  category: "WINNER" | "DRAFT" | "PROPS" | "FUTURES";
  title: string;
  rules: string;
  state: MarketState;
  state_reason: string | null;
  close_at: string;
  confidence: string;
  model: string;
  params: Record<string, unknown>;
  outcomes: OutcomeT[];
  result: { void: boolean; winning_codes: string[]; reason: string; revision: number } | null;
  /** Futures markets about one team (Swiss record) carry it here. */
  team?: Team | null;
};

export type EventT = {
  id: string;
  stage: string;
  best_of: number;
  scheduled_at: string;
  local_date: string;
  status: "SCHEDULED" | "LIVE" | "COMPLETED" | "POSTPONED" | "CANCELED";
  team_a: Team | null;
  team_b: Team | null;
  score: [number, number];
  winner: "A" | "B" | null;
  market_count?: number;
  /** Categories with an open market, for the "what's inside" tags on Today. */
  categories?: string[];
  close_at?: string | null;
  featured?: MarketT | null;
  markets?: MarketT[];
  games?: GameT[];
};

export type GameWindow = "OPEN" | "UPCOMING" | "LOCKED" | "DONE" | "NOT_NEEDED";

export type GameT = {
  index: number;
  state: string;
  started_at: string | null;
  ended_at: string | null;
  winner: "A" | "B" | null;
  window: GameWindow;
  opens_when: string | null;
  closes_at: string | null;
  burned_champions: string[];
};

export type LiveEvent = { type: "first_blood" | "first_tower" | "dragon" | "baron" | "inhibitor"; team: "A" | "B" | null; at_s: number; detail: string | null };

export type LiveT = {
  status: EventT["status"];
  game_index: number | null;
  game_state: string | null;
  as_of: string | null;
  game_clock_s: number | null;
  gold: [number, number] | null;
  kills: [number, number] | null;
  towers: [number, number] | null;
  dragons: [string[], string[]] | null;
  events: LiveEvent[];
  my_picks: (Pick & { live: { score?: [number, number]; current?: number; line?: string; needed?: number } | null })[];
};

export type Wallet = { available_rc: number; open_stake_rc: number; recovery_due_rc: number; granted_rc: number; realized_net_rc: number };

export type Me = { user: { id: string; handle: string; display_name: string; role: string }; wallet: Wallet };

export type SeasonT = {
  code: string;
  name: string;
  timezone: string;
  server_time: string;
  opening_grant_rc: number;
  match_day_grant_rc: number;
  first_match_day: string;
  match_days: string[];
  stages_by_day: Record<string, string>;
  data_as_of: string | null;
};

export type Pick = {
  id: string;
  ticket_id: string;
  status: "OPEN" | "WON" | "PARTIAL" | "LOST" | "VOID";
  stake_rc: number;
  odds: string;
  return_rc: number;
  potential_return_rc: number;
  /** Swiss record picks: what a right-side, wrong-record finish returns. */
  partial_return_rc: number | null;
  market_title: string;
  outcome_label: string;
  market_state: MarketState;
  market_state_reason: string | null;
  settled_revision: number;
  accepted_at: string;
  settled_at: string | null;
  event: EventT | null;
  user?: { handle: string; display_name: string };
};

export type Standing = {
  user: { id: string; handle: string; display_name: string };
  available_rc: number;
  open_stake_rc: number;
  granted_rc: number;
  realized_net_rc: number;
  won: number;
  lost: number;
  rank: number;
  provisional: boolean;
};

export type QuoteItem = {
  outcome_id: string;
  market_id: string;
  stake_rc: number;
  odds: string;
  odds_version: number;
  potential_return_rc: number;
  partial_return_rc: number | null;
  market_title: string;
  outcome_label: string;
};

export type Quote = {
  quote_id: string;
  expires_at: string;
  total_stake_rc: number;
  available_rc: number;
  available_after_rc: number;
  conditional_return_if_all_win_rc: number;
  items: QuoteItem[];
};

export type Receipt = { ticket_id: string; accepted_at: string; total_stake_rc: number; selections: Pick[]; wallet: Wallet };

export type LedgerRow = { id: number; kind: string; amount_rc: number; available_delta_rc: number; memo: string; created_at: string };
