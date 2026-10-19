import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from rift.db import session_factory
from rift.models import Base, Fixture, Market, Outcome, Season, Team, User

TEST_DB = os.environ.get("RIFT_TEST_DATABASE_URL", "postgresql+psycopg://rift:rift@localhost:5432/rift_test")
T0 = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)  # 10:00 venue time on the first Swiss day


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine):
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    return session_factory(engine)


@pytest.fixture
def world(factory):
    """A season with two players, one Bo3 fixture on the first match day and an open winner market."""
    with factory() as s, s.begin():
        season = Season(code="test", name="Test", timezone="America/Chicago", provider_league_id="x",
                        first_match_day=date(2026, 10, 23), opening_grant_rc=1000, match_day_grant_rc=1000)
        alice, bob = User(handle="alice", display_name="Alice"), User(handle="bob", display_name="Bob")
        ta = Team(provider_id="t-a", code="ATL", name="Atlas")
        tb = Team(provider_id="t-b", code="NOV", name="Nova")
        s.add_all([season, alice, bob, ta, tb])
        s.flush()
        fixture = Fixture(season_id=season.id, provider_id="fx-1", stage="Swiss", best_of=3, team_a_id=ta.id,
                          team_b_id=tb.id, scheduled_at=T0 + timedelta(hours=2), local_date=date(2026, 10, 23))
        s.add(fixture)
        s.flush()
        market = make_market(s, season, fixture, "series_winner", [("A", "Atlas", "1.62"), ("B", "Nova", "2.40")])
        ids = dict(season=season.id, alice=alice.id, bob=bob.id, fixture=fixture.id, market=market.id,
                   team_a=ta.id, team_b=tb.id)
    return ids


def make_market(s, season, fixture, kind, outcomes, *, params=None, scope="SERIES", key=None):
    market = Market(season_id=season.id, fixture_id=fixture.id if fixture else None,
                    template_key=key or f"{kind}:{uuid.uuid4()}", kind=kind, scope=scope, category="WINNER",
                    title=kind, rules_text="test", params=params or {}, model_key="test", confidence="EDITORIAL",
                    close_at=(fixture.scheduled_at if fixture else T0 + timedelta(days=5)))
    s.add(market)
    s.flush()
    for i, (code, label, odds) in enumerate(outcomes):
        s.add(Outcome(market_id=market.id, code=code, label=label, sort=i, odds_version=1, odds=Decimal(odds)))
    s.flush()
    return market


def outcome_id(factory, market_id, code):
    from sqlalchemy import select
    with factory() as s:
        return s.execute(select(Outcome.id).where(Outcome.market_id == market_id, Outcome.code == code)).scalar_one()
