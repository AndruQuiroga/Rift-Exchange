-- Rift Exchange proposed PostgreSQL migration sketch, v0.1 (NOT a finished migration).
-- Use Alembic and integration tests before deployment. PG 15+ assumed.
-- Virtual credits only. All balance-affecting writes must use a service transaction
-- locking the wallet row (SELECT ... FOR UPDATE), then atomically insert ledger rows.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE app_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  invite_code_hash TEXT UNIQUE,
  handle TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  auth_subject TEXT UNIQUE,
  role TEXT NOT NULL DEFAULT 'PLAYER' CHECK (role IN ('PLAYER','ADMIN')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  disabled_at TIMESTAMPTZ
);

CREATE TABLE seasons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  tournament_timezone TEXT NOT NULL DEFAULT 'America/Chicago',
  opening_grant_rc BIGINT NOT NULL DEFAULT 1000 CHECK (opening_grant_rc>=0),
  match_day_grant_rc BIGINT NOT NULL DEFAULT 1000 CHECK (match_day_grant_rc>=0),
  starts_on DATE NOT NULL,
  ends_on DATE NOT NULL,
  state TEXT NOT NULL DEFAULT 'DRAFT' CHECK (state IN ('DRAFT','OPEN','FROZEN','ARCHIVED')),
  rules_version INTEGER NOT NULL DEFAULT 1 CHECK (rules_version>0),
  CHECK (ends_on>=starts_on)
);

CREATE TABLE memberships (
  user_id UUID NOT NULL REFERENCES app_users(id),
  season_id UUID NOT NULL REFERENCES seasons(id),
  joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(user_id, season_id)
);

CREATE TABLE wallets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  season_id UUID NOT NULL,
  available_rc BIGINT NOT NULL DEFAULT 0 CHECK (available_rc>=0),
  recovery_due_rc BIGINT NOT NULL DEFAULT 0 CHECK (recovery_due_rc>=0),
  version BIGINT NOT NULL DEFAULT 0 CHECK (version>=0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(user_id,season_id),
  FOREIGN KEY(user_id,season_id) REFERENCES memberships(user_id,season_id)
);

CREATE TABLE match_days (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  season_id UUID NOT NULL REFERENCES seasons(id),
  tournament_date DATE NOT NULL,
  eligible BOOLEAN NOT NULL DEFAULT true,
  day_status TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK (day_status IN ('SCHEDULED','STARTED','COMPLETED','CANCELED')),
  eligibility_source TEXT,
  UNIQUE(season_id,tournament_date)
);

CREATE TABLE credit_grants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  wallet_id UUID NOT NULL REFERENCES wallets(id),
  season_id UUID NOT NULL REFERENCES seasons(id),
  user_id UUID NOT NULL REFERENCES app_users(id),
  match_day_id UUID REFERENCES match_days(id),
  kind TEXT NOT NULL CHECK (kind IN ('OPENING','MATCH_DAY','ADMIN_ADJUSTMENT')),
  amount_rc BIGINT NOT NULL CHECK (amount_rc>0),
  granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (wallet_id,kind,match_day_id),
  CHECK ((kind='MATCH_DAY' AND match_day_id IS NOT NULL) OR (kind<>'MATCH_DAY' AND match_day_id IS NULL))
);
CREATE UNIQUE INDEX uq_one_opening_grant ON credit_grants(wallet_id) WHERE kind='OPENING';

CREATE TABLE teams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  region TEXT,
  source_aliases JSONB NOT NULL DEFAULT '{}'
);
CREATE TABLE players (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name TEXT NOT NULL,
  current_team_id UUID REFERENCES teams(id),
  role TEXT CHECK (role IN ('TOP','JUNGLE','MID','BOT','SUPPORT')),
  source_aliases JSONB NOT NULL DEFAULT '{}'
);
CREATE TABLE champions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_key TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE fixtures (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  season_id UUID NOT NULL REFERENCES seasons(id),
  match_day_id UUID REFERENCES match_days(id),
  external_id TEXT,
  stage TEXT NOT NULL CHECK (stage IN ('PLAY_IN','SWISS','QUARTERFINAL','SEMIFINAL','FINAL')),
  best_of SMALLINT NOT NULL CHECK (best_of IN (1,3,5)),
  team_a_id UUID REFERENCES teams(id),
  team_b_id UUID REFERENCES teams(id),
  scheduled_at TIMESTAMPTZ NOT NULL,
  draft_started_at TIMESTAMPTZ,
  actual_started_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK (status IN ('SCHEDULED','DRAFTING','LIVE','POSTPONED','COMPLETED','CANCELED')),
  provider_quality TEXT NOT NULL DEFAULT 'MOCK' CHECK (provider_quality IN ('MOCK','UNVERIFIED','HUMAN_REVIEW','CONFIRMED')),
  source_meta JSONB NOT NULL DEFAULT '{}',
  UNIQUE(season_id,external_id),
  CHECK (team_a_id IS DISTINCT FROM team_b_id)
);
CREATE INDEX ix_fixtures_date ON fixtures(season_id,scheduled_at);

CREATE TABLE fixture_games (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fixture_id UUID NOT NULL REFERENCES fixtures(id) ON DELETE RESTRICT,
  game_index SMALLINT NOT NULL CHECK (game_index BETWEEN 1 AND 5),
  status TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK (status IN ('SCHEDULED','DRAFTING','LIVE','COMPLETED','VOID')),
  started_at TIMESTAMPTZ,
  draft_started_at TIMESTAMPTZ,
  result JSONB,
  source_meta JSONB NOT NULL DEFAULT '{}',
  UNIQUE(fixture_id,game_index)
);

CREATE TABLE markets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  season_id UUID NOT NULL REFERENCES seasons(id),
  fixture_id UUID REFERENCES fixtures(id),
  match_day_id UUID REFERENCES match_days(id),
  kind TEXT NOT NULL,
  scope TEXT NOT NULL CHECK (scope IN ('GAME','SERIES','MATCH_DAY','STAGE','TOURNAMENT')),
  label TEXT NOT NULL,
  rules JSONB NOT NULL,
  rule_version INT NOT NULL DEFAULT 1 CHECK (rule_version>0),
  required_fields JSONB NOT NULL DEFAULT '[]',
  close_at TIMESTAMPTZ NOT NULL,
  lock_trigger TEXT NOT NULL DEFAULT 'BEFORE_START' CHECK(lock_trigger IN ('BEFORE_START','BEFORE_DRAFT','EXPLICIT')),
  state TEXT NOT NULL DEFAULT 'DRAFT' CHECK (state IN ('DRAFT','OPEN','SUSPENDED','LOCKED','GRADING','SETTLED','VOID')),
  created_by UUID REFERENCES app_users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_markets_event_state ON markets(fixture_id,state,close_at);

CREATE TABLE outcomes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  market_id UUID NOT NULL REFERENCES markets(id),
  outcome_key TEXT NOT NULL,
  display_label TEXT NOT NULL,
  target_id UUID,
  sort_index INT NOT NULL DEFAULT 0,
  UNIQUE(market_id,outcome_key)
);

CREATE TABLE odds_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  outcome_id UUID NOT NULL REFERENCES outcomes(id),
  version INTEGER NOT NULL CHECK(version>0),
  -- Store as NUMERIC, not float. UI renders '2.40×'; database stores 2.4000.
  decimal_odds NUMERIC(12,4) NOT NULL CHECK(decimal_odds>1),
  implied_probability NUMERIC(10,8) CHECK (implied_probability>=0 AND implied_probability<=1),
  model_key TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'EDITORIAL' CHECK (confidence IN ('EDITORIAL','EXPERIMENTAL','CALIBRATED')),
  effective_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by UUID REFERENCES app_users(id),
  reason TEXT,
  UNIQUE(outcome_id,version)
);

CREATE TABLE quotes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES app_users(id),
  season_id UUID NOT NULL REFERENCES seasons(id),
  total_stake_rc BIGINT NOT NULL CHECK(total_stake_rc>0),
  quoted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  quote_json JSONB NOT NULL,
  CHECK(expires_at>quoted_at)
);

CREATE TABLE tickets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES app_users(id),
  season_id UUID NOT NULL REFERENCES seasons(id),
  quote_id UUID NOT NULL UNIQUE REFERENCES quotes(id),
  idempotency_key TEXT NOT NULL,
  accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  total_stake_rc BIGINT NOT NULL CHECK(total_stake_rc>0),
  UNIQUE(user_id,idempotency_key)
);

CREATE TABLE selections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket_id UUID NOT NULL REFERENCES tickets(id),
  outcome_id UUID NOT NULL REFERENCES outcomes(id),
  odds_snapshot_id UUID NOT NULL REFERENCES odds_snapshots(id),
  stake_rc BIGINT NOT NULL CHECK(stake_rc>0),
  accepted_decimal_odds NUMERIC(12,4) NOT NULL CHECK(accepted_decimal_odds>1),
  accepted_rule_version INT NOT NULL CHECK(accepted_rule_version>0),
  accepted_rules_snapshot JSONB NOT NULL,
  accepted_at TIMESTAMPTZ NOT NULL,
  state TEXT NOT NULL DEFAULT 'OPEN' CHECK(state IN ('OPEN','HOLD','WON','LOST','VOID','CORRECTED')),
  UNIQUE(ticket_id,outcome_id)
);
CREATE INDEX ix_selections_ticket ON selections(ticket_id);

CREATE TABLE result_revisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fixture_id UUID REFERENCES fixtures(id),
  market_id UUID REFERENCES markets(id),
  revision INTEGER NOT NULL CHECK (revision>0),
  source_id TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  result_json JSONB NOT NULL,
  quality TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK(quality IN ('UNVERIFIED','REVIEWED','CONFIRMED')),
  reviewed_by UUID REFERENCES app_users(id),
  confirmed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(source_id,payload_hash),
  CHECK (fixture_id IS NOT NULL OR market_id IS NOT NULL)
);

CREATE TABLE settlements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  selection_id UUID NOT NULL REFERENCES selections(id),
  result_revision_id UUID NOT NULL REFERENCES result_revisions(id),
  grade TEXT NOT NULL CHECK (grade IN ('WIN','LOSS','VOID','HOLD')),
  return_rc BIGINT NOT NULL CHECK(return_rc>=0),
  adjustment_rc BIGINT NOT NULL, -- return value minus prior credited return; may be negative
  applied_at TIMESTAMPTZ,
  reason TEXT,
  UNIQUE(selection_id,result_revision_id)
);

CREATE TABLE ledger_transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind TEXT NOT NULL CHECK(kind IN ('GRANT','STAKE','SETTLEMENT','CORRECTION','RECOVERY','ADMIN_ADJUSTMENT')),
  source_id UUID NOT NULL,
  actor_user_id UUID REFERENCES app_users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(kind,source_id)
);
CREATE TABLE ledger_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  transaction_id UUID NOT NULL REFERENCES ledger_transactions(id),
  wallet_id UUID NOT NULL REFERENCES wallets(id),
  line_number INT NOT NULL CHECK(line_number>0),
  delta_available_rc BIGINT NOT NULL,
  delta_recovery_due_rc BIGINT NOT NULL DEFAULT 0,
  balance_after_rc BIGINT NOT NULL CHECK(balance_after_rc>=0),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(transaction_id,wallet_id,line_number)
);
CREATE INDEX ix_wallet_ledger ON ledger_entries(wallet_id,recorded_at,id);

CREATE TABLE admin_audit (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id UUID NOT NULL REFERENCES app_users(id),
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  before_json JSONB,
  after_json JSONB,
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE outbox_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  delivered_at TIMESTAMPTZ,
  delivery_attempts INT NOT NULL DEFAULT 0 CHECK(delivery_attempts>=0)
);

-- REQUIRED BY SERVICE / INTEGRATION TESTS (not provided by these DDL constraints alone):
-- 1. Lock wallet row; enforce available >= total stake and no re-use of quotes.
-- 2. Enforce source quote matches latest odds snapshot AND server lock/draft times.
-- 3. Enforce accepted selections always reference odds from the same market/outcome.
-- 4. Enforce owner of quote = owner of ticket, fixture / season consistency.
-- 5. Enforce grant eligibility and one opening + one match-day grant per user/day.
-- 6. Enforce immutable accepted stakes/rules/odds and append-only audit + ledger.
-- 7. Enforce negative-correction recovery; zero balance is allowed but debt is not spendable.
-- 8. Enforce valid legal score outcomes per best_of; mark unresolved props HOLD.
