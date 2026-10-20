"""Swiss Board: exact record pays in full; right side, wrong record pays the frozen consolation share."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import T0, make_market, outcome_id
from sqlalchemy import select
from test_money import balance, join, place

from rift.domain.money import partial_return, settlement_return
from rift.markets import SWISS_CONSOLATION, swiss_record_outcomes
from rift.models import Fixture, Market, Season, Selection, Team
from rift.settlement import apply_grade, grade_market


def test_record_prices_include_the_consolation():
    dist = {"3-0": 0.25, "3-1": 0.30, "3-2": 0.23, "2-3": 0.12, "1-3": 0.07, "0-3": 0.03}
    prices = {o.code: o.probability for o in swiss_record_outcomes(dist)}
    # odds = 1 / (P(exact) + 1/4 * P(same side, other record))
    assert prices["3-0"] == pytest.approx(0.25 + 0.25 * (0.30 + 0.23))
    assert prices["0-3"] == pytest.approx(0.03 + 0.25 * (0.12 + 0.07))
    # An impossible record is not offered at all.
    assert {o.code: o.probability for o in swiss_record_outcomes({"3-0": 1.0})}["3-1"] == 0.0


def test_partial_return_rounds_half_up_and_needs_a_share():
    assert partial_return(100, Decimal("2.48"), "0.25") == 62
    assert partial_return(3, Decimal("2.50"), "0.25") == 2  # 1.875 -> 2
    assert settlement_return(100, Decimal("12.97"), "PARTIAL", SWISS_CONSOLATION) == 324
    with pytest.raises(ValueError):
        settlement_return(100, Decimal("2.00"), "PARTIAL")


def _swiss_world(factory, world):
    """Atlas finishes 3-1 in Swiss; a swiss_record market on Atlas with three priced records."""
    with factory() as s, s.begin():
        season = s.get(Season, world["season"])
        atlas = s.get(Team, world["team_a"])
        market = make_market(s, season, None, "swiss_record",
                             [("3-0", "3–0", "2.50"), ("3-1", "3–1", "3.00"), ("2-3", "2–3", "8.00")],
                             params={"team": atlas.provider_id, "consolation": "0.25"}, scope="STAGE")
        return market.id


def _finish_swiss(factory, world, results, start=0):
    with factory() as s, s.begin():
        for i, won in enumerate(results, start=start):
            opp = Team(provider_id=f"opp-{i}", code=f"O{i}", name=f"Opp {i}")
            s.add(opp)
            s.flush()
            s.add(Fixture(season_id=world["season"], provider_id=f"sw-{i}", stage="Swiss", best_of=1,
                          team_a_id=world["team_a"], team_b_id=opp.id, status="COMPLETED",
                          scheduled_at=T0 + timedelta(days=i), local_date=date(2026, 10, 23 + i),
                          team_a_wins=int(won), team_b_wins=int(not won),
                          winner_team_id=world["team_a"] if won else opp.id))


def test_exact_partial_and_lost_settle_once(factory, world):
    market_id = _swiss_world(factory, world)
    join(factory, world, "alice")
    picks = [(outcome_id(factory, market_id, "3-1"), 100)]
    place(factory, world, "alice", picks, "exact")
    join(factory, world, "bob")
    place(factory, world, "bob", [(outcome_id(factory, market_id, "3-0"), 100)], "side")
    with factory() as s, s.begin():
        s.get(Market, market_id).state = "LOCKED"

    _finish_swiss(factory, world, [True, False])  # 1-1: still running
    with factory() as s, s.begin():
        assert grade_market(s, s.get(Market, market_id)).status == "PENDING"

    _finish_swiss(factory, world, [True, True], start=2)  # 3-1: advanced
    with factory() as s, s.begin():
        grade = grade_market(s, s.get(Market, market_id))
        assert grade.winning_codes == ["3-1"] and set(grade.partial_codes) == {"3-0", "3-2"}
        assert apply_grade(s, market_id, grade, T0 + timedelta(days=5))
    with factory() as s, s.begin():
        # Replaying the same grade moves nothing.
        assert not apply_grade(s, market_id, grade_market(s, s.get(Market, market_id)), T0 + timedelta(days=5))

    with factory() as s:
        rows = {sel.user_id: sel for sel in s.execute(select(Selection)).scalars()}
    assert rows[world["alice"]].status == "WON" and rows[world["alice"]].return_rc == 300
    assert rows[world["bob"]].status == "PARTIAL" and rows[world["bob"]].return_rc == 63  # 100 x 2.50 x 0.25
    assert balance(factory, world, "alice") == (2000 - 100 + 300, 0)
    assert balance(factory, world, "bob") == (2000 - 100 + 63, 0)
