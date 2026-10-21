"""Opening and match-day grants (docs/spec/02_GAME_RULES.md, D-010). Idempotent by ledger key."""

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rift import ledger
from rift.models import Fixture, LedgerEntry, Season, Wallet


def season_local_date(season: Season, at: datetime) -> date:
    return at.astimezone(ZoneInfo(season.timezone)).date()


def eligible_match_days(session: Session, season: Season, today: date) -> list[date]:
    """Venue-local dates with at least one scheduled Worlds fixture, from the first match day up to today."""
    rows = session.execute(
        select(Fixture.local_date).where(
            Fixture.season_id == season.id,
            Fixture.local_date >= season.first_match_day,
            Fixture.local_date <= today,
            Fixture.status != "CANCELED",
        ).distinct().order_by(Fixture.local_date)
    ).scalars()
    return list(rows)


def _match_day_key(season: Season, user_id: uuid.UUID, day: date) -> str:
    return f"grant:match_day:{season.id}:{user_id}:{day.isoformat()}"


def join_season(session: Session, season: Season, user_id: uuid.UUID, now: datetime) -> Wallet:
    """Create the wallet, issue the opening grant and backfill every past match day (late-join parity)."""
    wallet = session.execute(
        select(Wallet).where(Wallet.season_id == season.id, Wallet.user_id == user_id)
    ).scalar_one_or_none()
    if wallet is None:
        wallet = Wallet(season_id=season.id, user_id=user_id, available_rc=0, recovery_due_rc=0)
        session.add(wallet)
        session.flush()
    wallet = ledger.lock_wallet(session, wallet.id)
    key = f"grant:opening:{season.id}:{user_id}"
    if season.opening_grant_rc > 0 and not ledger.entry_exists(session, key):
        ledger.credit(session, wallet, kind="GRANT_OPENING", amount_rc=season.opening_grant_rc, key=key,
                      ref_type="season", ref_id=str(season.id), memo="Opening grant")
    _top_up_opening(session, season, wallet)
    _grant_days(session, season, wallet, eligible_match_days(session, season, season_local_date(season, now)))
    return wallet


def _top_up_opening(session: Session, season: Season, wallet: Wallet) -> int:
    """If the season's opening grant was raised after members joined, pay them the difference (once per level)."""
    paid = session.execute(select(func.coalesce(func.sum(LedgerEntry.gross_rc), 0)).where(
        LedgerEntry.wallet_id == wallet.id, LedgerEntry.kind == "GRANT_OPENING")).scalar()
    short = season.opening_grant_rc - int(paid)
    key = f"grant:opening-topup:{season.id}:{wallet.user_id}:{season.opening_grant_rc}"
    if short <= 0 or int(paid) == 0 or ledger.entry_exists(session, key):
        return 0
    ledger.credit(session, wallet, kind="GRANT_OPENING", amount_rc=short, key=key, ref_type="season",
                  ref_id=str(season.id), memo=f"Opening grant raised to {season.opening_grant_rc:,} RC")
    return 1


def run_match_day_grants(session: Session, season: Season, now: datetime) -> int:
    """Grant every member for every eligible day so far. Safe to run repeatedly; returns grants issued."""
    days = eligible_match_days(session, season, season_local_date(season, now))
    issued = 0
    wallet_ids = session.execute(select(Wallet.id).where(Wallet.season_id == season.id)).scalars().all()
    for wallet_id in sorted(wallet_ids):
        wallet = ledger.lock_wallet(session, wallet_id)
        issued += _top_up_opening(session, season, wallet)
        if days:
            issued += _grant_days(session, season, wallet, days)
    return issued


def _grant_days(session: Session, season: Season, wallet: Wallet, days: list[date]) -> int:
    issued = 0
    if season.match_day_grant_rc <= 0:
        return 0
    for day in days:
        key = _match_day_key(season, wallet.user_id, day)
        if ledger.entry_exists(session, key):
            continue
        ledger.credit(session, wallet, kind="GRANT_MATCH_DAY", amount_rc=season.match_day_grant_rc, key=key,
                      ref_type="match_day", ref_id=day.isoformat(), memo=f"Match day {day:%b} {day.day}")
        issued += 1
    return issued
