export type Team = { id: string; code: string; name: string; image_url: string | null; region: string | null };

export type OutcomeT = { id: string; code: string; label: string; odds: string | null; odds_version: number; probability: number | null };

export type MarketState = "OPEN" | "SUSPENDED" | "LOCKED" | "HOLD" | "SETTLED" | "VOID";

export type MarketT = {
  id: string;
  kind: string;
  scope: string;
  category: "WINNER" | "DRAFT" | "PROPS" | "FUTURES" | "OBJECTIVES" | "PLAYERS";
  title: string;
  rules: string;
  state: MarketState;
  state_reason: string | null;
  close_at: string;
  /** false while its close follows a game that hasn't loaded: close_at is only a backstop (3:00 of game time). */
  close_known?: boolean;
  /** What really closes it while close_at is a backstop: "game" (3:00 into it) or "draft" (the series going live). */
  close_rule?: "game" | "draft" | null;
  confidence: string;
  model: string;
  params: Record<string, unknown>;
  outcomes: OutcomeT[];
  result: { void: boolean; winning_codes: string[]; reason: string; revision: number } | null;
  /** The result as soon as the data shows it, before it pays (D-032). final: graded, pays at pays_at once the
   * data holds steady; otherwise called from live game data and confirmed after the game. */
  call?: MarketCall | null;
  /** Futures markets about one team (Swiss record) carry it here. */
  team?: Team | null;
};

export type MarketCall = {
  winning_codes: string[]; void: boolean; reason: string; final: boolean; pays_at: string | null;
  /** Codes paid in part: a champion call whose champion was banned gets half back (D-033). */
  partial_codes?: string[];
  pending_refund?: boolean;
};

/** Where an open pick stands on the latest data, before it pays. */
export type PickCall = {
  result: "WON" | "LOST" | "VOID" | "PARTIAL"; final: boolean; reason: string; pays_at: string | null;
  /** Not picked, and bans aren't known yet: it may still be half back. */
  pending_refund?: boolean;
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
  /** Duels and kill lines can be picked right now (the loaded game's first minutes). */
  early_open?: boolean;
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
  /** Duels and kill lines: UPCOMING until the game loads, OPEN until 3:00 or first blood. */
  early?: "UPCOMING" | "OPEN" | "CLOSED";
  burned_champions: string[];
  /** Lane duels and kill lines: BLIND (before the draft), DRAFT (none), LIVE (after the draft, to 3:00), UPCOMING, CLOSED. */
  lanes?: "BLIND" | "DRAFT" | "LIVE" | "UPCOMING" | "CLOSED";
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

export type Wallet = {
  available_rc: number; open_stake_rc: number; recovery_due_rc: number; granted_rc: number; realized_net_rc: number;
  /** What picks settled today won or lost, plus Swiss rewards (the venue's day). */
  today_net_rc?: number;
};

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
  market_id: string;
  outcome_id: string;
  status: "OPEN" | "WON" | "PARTIAL" | "LOST" | "VOID" | "CANCELLED";
  stake_rc: number;
  odds: string;
  return_rc: number;
  potential_return_rc: number;
  /** Swiss record picks: what a right-side, wrong-record finish returns. */
  partial_return_rc: number | null;
  /** The market kind (champion_picked, lane_duel...). */
  kind?: string;
  market_title: string;
  outcome_label: string;
  market_state: MarketState;
  market_state_reason: string | null;
  /** Plain words for a void pick ("Tie", "Placed after first blood or 3:00"). */
  void_reason?: string | null;
  /** Swiss Board picks: the team's Swiss record so far ("2-1"). */
  swiss_record?: string | null;
  settled_revision: number;
  accepted_at: string;
  settled_at: string | null;
  event: EventT | null;
  user?: { handle: string; display_name: string };
  call?: PickCall | null;
  close_at?: string;
  closes_with_game?: boolean;
  close_known?: boolean;
  close_rule?: "game" | "draft" | null;
  /** What cancelling returns right now: the whole stake, 75% once the draft has started (D-040), or null. */
  cancel_refund_rc?: number | null;
  /** Placed after the draft, at the lower after-draft price (D-040). */
  after_draft?: boolean;
};

/** Friends on one match: picks revealed once their market locks, before that only a count (A-010). */
export type Person = { handle: string; display_name: string };

/** One player's standing on a match right now: settled plus already-decided picks (D-034). */
export type TableRow = {
  user: Person; you: boolean; rank: number; picks: number;
  staked: number; back: number; decided: number; riding: number; net: number;
  won: number; lost: number; partial: number;
  /** Net if every undecided pick wins; riding_return is those picks' full returns. */
  potential?: number; riding_return?: number;
};

export type ReactionT = { id: number; from: Person; to: Person; phrase: string; text: string; selection_id: string; pick: string; market: string; at: string };

export type FriendsOnMatch = {
  picks: Pick[];
  pending: { user: Person; picks: number; reveals_at: string }[];
  table?: TableRow[];
  reactions?: ReactionT[];
};

export type Standing = {
  user: { id: string; handle: string; display_name: string };
  available_rc: number;
  open_stake_rc: number;
  granted_rc: number;
  realized_net_rc: number;
  today_net_rc: number;
  /** Available plus in play: what the season table ranks by. */
  bankroll_rc: number;
  won: number;
  lost: number;
  won_today: number;
  lost_today: number;
  rank: number;
  /** Rank by today's net. */
  today_rank: number;
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

/** A free Swiss record call: price locked when made; exact pays exact_rc, right side partial_rc. */
export type SwissCallT = {
  market_id: string;
  outcome_id: string;
  record: string;
  odds: string;
  status: "OPEN" | "WON" | "PARTIAL" | "LOST" | "VOID";
  reward_rc: number;
  exact_rc: number;
  partial_rc: number;
  /** The team's Swiss record so far ("2-1"). */
  swiss_record: string;
};

export type SwissCardT = {
  open: boolean;
  close_at: string | null;
  reward: { base_rc: number; cap_rc: number; partial_share: string };
  slots: Record<string, number>;
  calls: SwissCallT[];
};
