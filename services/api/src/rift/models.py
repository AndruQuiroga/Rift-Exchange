"""PostgreSQL schema (docs/spec/08_DB_SCHEMA.md). Money columns are BIGINT RC; odds NUMERIC."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------- identity


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid()
    handle: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default="PLAYER")
    created_at: Mapped[datetime] = _created()
    __table_args__ = (CheckConstraint("role IN ('PLAYER','ADMIN')", name="ck_user_role"),)


class Invite(Base):
    __tablename__ = "invites"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), default="PLAYER")
    created_at: Mapped[datetime] = _created()
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SignInCode(Base):
    """A short-lived, one-time code that signs another device into an existing account."""

    __tablename__ = "sign_in_codes"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- season & wallet


class Season(Base):
    __tablename__ = "seasons"
    id: Mapped[uuid.UUID] = _uuid()
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    timezone: Mapped[str] = mapped_column(String(64))
    provider_league_id: Mapped[str] = mapped_column(String(64))
    first_match_day: Mapped[date] = mapped_column(Date)
    opening_grant_rc: Mapped[int] = mapped_column(BigInteger)
    match_day_grant_rc: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(16), default="OPEN")
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint("opening_grant_rc >= 0 AND match_day_grant_rc >= 0", name="ck_season_grants"),
        CheckConstraint("state IN ('OPEN','FROZEN','ARCHIVED')", name="ck_season_state"),
    )


class Wallet(Base):
    """One per (season, user). Cached balance; the ledger is the source of truth."""

    __tablename__ = "wallets"
    id: Mapped[uuid.UUID] = _uuid()
    season_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seasons.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    available_rc: Mapped[int] = mapped_column(BigInteger, default=0)
    recovery_due_rc: Mapped[int] = mapped_column(BigInteger, default=0)
    joined_at: Mapped[datetime] = _created()
    __table_args__ = (
        UniqueConstraint("season_id", "user_id", name="uq_wallet_member"),
        CheckConstraint("available_rc >= 0", name="ck_wallet_available_nonneg"),
        CheckConstraint("recovery_due_rc >= 0", name="ck_wallet_recovery_nonneg"),
    )


class LedgerEntry(Base):
    """Append-only journal. sum(available_delta) == available_rc; sum(recovery_delta) == recovery_due_rc.

    gross_rc is the user-facing amount of the event (e.g. a 580 RC payout reversal) while the deltas
    record how it hit spendable balance versus the correction-recovery offset.
    """

    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    wallet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wallets.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    gross_rc: Mapped[int] = mapped_column(BigInteger)
    available_delta: Mapped[int] = mapped_column(BigInteger)
    recovery_delta: Mapped[int] = mapped_column(BigInteger, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[str | None] = mapped_column(String(64))
    memo: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint(
            "kind IN ('GRANT_OPENING','GRANT_MATCH_DAY','STAKE','PAYOUT','VOID_REFUND','REVERSAL','REWARD')",
            name="ck_ledger_kind",
        ),
    )


# ---------------------------------------------------------------- esports facts


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[uuid.UUID] = _uuid()
    provider_id: Mapped[str] = mapped_column(String(160), unique=True)  # lolesports:<normalised name>
    esports_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    image_url: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(32))
    # Starting five from the team's latest regional match, until it plays at Worlds: {match, at, players}
    lineup: Mapped[dict | None] = mapped_column(JSONB)


class Fixture(Base):
    __tablename__ = "fixtures"
    id: Mapped[uuid.UUID] = _uuid()
    season_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seasons.id"))
    provider_id: Mapped[str] = mapped_column(String(64), unique=True)
    stage: Mapped[str] = mapped_column(String(32))
    best_of: Mapped[int] = mapped_column(SmallInteger)
    team_a_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"))
    team_b_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="SCHEDULED")
    team_a_wins: Mapped[int] = mapped_column(SmallInteger, default=0)
    team_b_wins: Mapped[int] = mapped_column(SmallInteger, default=0)
    winner_team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint("best_of IN (1,3,5)", name="ck_fixture_bo"),
        CheckConstraint(
            "status IN ('SCHEDULED','LIVE','COMPLETED','POSTPONED','CANCELED')", name="ck_fixture_status"
        ),
        Index("ix_fixture_season_time", "season_id", "scheduled_at"),
    )


class Game(Base):
    __tablename__ = "games"
    id: Mapped[uuid.UUID] = _uuid()
    fixture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fixtures.id"))
    provider_id: Mapped[str] = mapped_column(String(64), unique=True)
    game_index: Mapped[int] = mapped_column(SmallInteger)
    state: Mapped[str] = mapped_column(String(16))  # unstarted / inProgress / completed / unneeded
    blue_team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"))
    red_team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"))
    winner_team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"))
    winner_evidence: Mapped[str | None] = mapped_column(String(32))
    patch: Mapped[str | None] = mapped_column(String(32))
    stats: Mapped[dict | None] = mapped_column(JSONB)
    stats_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    bans: Mapped[dict | None] = mapped_column(JSONB)
    data_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Livestats timeline (rift.timeline): first/last frame times, objective firsts, dragons, 15-minute and
    # final player lines, plus the latest live frame summary. Graders that read it HOLD until complete.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timeline: Mapped[dict | None] = mapped_column(JSONB)
    timeline_complete: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    __table_args__ = (UniqueConstraint("fixture_id", "game_index", name="uq_game_index"),)


class HistoricalResult(Base):
    """Series results from regional leagues used to fit team ratings (not markets)."""

    __tablename__ = "historical_results"
    provider_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    league_slug: Mapped[str] = mapped_column(String(64))
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    team_a_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"))
    team_b_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"))
    team_a_wins: Mapped[int] = mapped_column(SmallInteger)
    team_b_wins: Mapped[int] = mapped_column(SmallInteger)


class TeamRating(Base):
    __tablename__ = "team_ratings"
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    rating: Mapped[float] = mapped_column(Numeric(8, 2))
    games: Mapped[int] = mapped_column(Integer)
    model_key: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = _created()


# ---------------------------------------------------------------- markets


class Market(Base):
    __tablename__ = "markets"
    id: Mapped[uuid.UUID] = _uuid()
    season_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seasons.id"))
    fixture_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fixtures.id"), index=True)
    template_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(48))
    scope: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    rules_text: Mapped[str] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    model_key: Mapped[str] = mapped_column(String(48))
    confidence: Mapped[str] = mapped_column(String(16))
    close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), default="OPEN")
    state_reason: Mapped[str | None] = mapped_column(Text)
    result_revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        UniqueConstraint("season_id", "template_key", name="uq_market_template"),
        CheckConstraint(
            "state IN ('OPEN','SUSPENDED','LOCKED','HOLD','SETTLED','VOID')", name="ck_market_state"
        ),
        CheckConstraint("scope IN ('GAME','SERIES','MATCH_DAY','STAGE','TOURNAMENT')", name="ck_market_scope"),
    )


class Outcome(Base):
    __tablename__ = "outcomes"
    id: Mapped[uuid.UUID] = _uuid()
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("markets.id"), index=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(128))
    sort: Mapped[int] = mapped_column(SmallInteger, default=0)
    odds_version: Mapped[int] = mapped_column(Integer, default=0)  # 0 = not offered
    odds: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    probability: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    __table_args__ = (UniqueConstraint("market_id", "code", name="uq_outcome_code"),)


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    outcome_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outcomes.id"))
    version: Mapped[int] = mapped_column(Integer)
    odds: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    probability: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    model_key: Mapped[str] = mapped_column(String(48))
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        UniqueConstraint("outcome_id", "version", name="uq_snapshot_version"),
        CheckConstraint("odds IS NULL OR odds > 1", name="ck_snapshot_odds"),
    )


class MarketResult(Base):
    """A graded result revision for a market. Corrections append a new revision."""

    __tablename__ = "market_results"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("markets.id"))
    revision: Mapped[int] = mapped_column(Integer)
    void: Mapped[bool] = mapped_column(Boolean, default=False)
    winning_codes: Mapped[list] = mapped_column(JSONB, default=list)
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (UniqueConstraint("market_id", "revision", name="uq_market_result_revision"),)


# ---------------------------------------------------------------- tickets


class Quote(Base):
    __tablename__ = "quotes"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    season_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seasons.id"))
    items: Mapped[list] = mapped_column(JSONB)
    total_stake_rc: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("total_stake_rc > 0", name="ck_quote_total"),)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    season_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seasons.id"))
    quote_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quotes.id"), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    total_stake_rc: Mapped[int] = mapped_column(BigInteger)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("user_id", "season_id", "idempotency_key", name="uq_ticket_idempotency"),
        CheckConstraint("total_stake_rc > 0", name="ck_ticket_total"),
    )


class Selection(Base):
    __tablename__ = "selections"
    id: Mapped[uuid.UUID] = _uuid()
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("markets.id"), index=True)
    outcome_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outcomes.id"))
    stake_rc: Mapped[int] = mapped_column(BigInteger)
    odds: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    odds_version: Mapped[int] = mapped_column(Integer)
    rule_version: Mapped[int] = mapped_column(Integer)
    rules_snapshot: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(8), default="OPEN")
    return_rc: Mapped[int] = mapped_column(BigInteger, default=0)
    settled_revision: Mapped[int] = mapped_column(Integer, default=0)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("stake_rc > 0", name="ck_selection_stake"),
        CheckConstraint("odds > 1", name="ck_selection_odds"),
        CheckConstraint("status IN ('OPEN','WON','PARTIAL','LOST','VOID')", name="ck_selection_status"),
    )


class SwissCall(Base):
    """A free record call on the Swiss card: no stake, a capped RC reward at the price locked when called."""

    __tablename__ = "swiss_calls"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("markets.id"), index=True)
    outcome_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outcomes.id"))
    odds: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    odds_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(8), default="OPEN")
    reward_rc: Mapped[int] = mapped_column(BigInteger, default=0)
    settled_revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("user_id", "market_id", name="uq_swiss_call_market"),
        CheckConstraint("odds > 1", name="ck_swiss_call_odds"),
        CheckConstraint("status IN ('OPEN','WON','PARTIAL','LOST','VOID')", name="ck_swiss_call_status"),
    )


class Settlement(Base):
    __tablename__ = "settlements"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    selection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("selections.id"))
    revision: Mapped[int] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String(8))
    return_rc: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (UniqueConstraint("selection_id", "revision", name="uq_settlement_revision"),)


# ---------------------------------------------------------------- ops


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(48))
    entity_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()


class ProviderSync(Base):
    """Last-run bookkeeping for each worker job, surfaced on the admin health view."""

    __tablename__ = "provider_syncs"
    job: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class ReferenceGame(Base):
    __tablename__ = "reference_games"
    provider_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(16))
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
