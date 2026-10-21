"""Swiss Board: exact record pays in full; right side, wrong record pays the frozen consolation share."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import T0, make_market, outcome_id
from sqlalchemy import select
from test_money import balance, join, place

from rift import swiss_card
from rift.domain.money import partial_return, settlement_return
from rift.markets import SWISS_CONSOLATION, swiss_record_outcomes
from rift.models import Fixture, Market, Outcome, Season, Selection, SwissCall, Team
from rift.placement import PlacementError
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


def _place_staked(factory, world, user, market_id, code, key):
    """A staked record pick as placed before the free card existed (placement now refuses them)."""
    with factory() as s, s.begin():
        s.get(Market, market_id).kind = "swiss_record_legacy"
    place(factory, world, user, [(outcome_id(factory, market_id, code), 100)], key)
    with factory() as s, s.begin():
        s.get(Market, market_id).kind = "swiss_record"


def test_staked_record_picks_are_refused(factory, world):
    market_id = _swiss_world(factory, world)
    join(factory, world, "alice")
    with pytest.raises(PlacementError) as e:
        place(factory, world, "alice", [(outcome_id(factory, market_id, "3-1"), 100)], "k")
    assert e.value.code == "USE_RECORD_CARD"


def test_legacy_staked_picks_settle_once_after_lock(factory, world):
    market_id = _swiss_world(factory, world)
    join(factory, world, "alice")
    _place_staked(factory, world, "alice", market_id, "3-1", "exact")
    join(factory, world, "bob")
    _place_staked(factory, world, "bob", market_id, "3-0", "side")
    with factory() as s, s.begin():
        s.get(Market, market_id).state = "LOCKED"
        # Once calls lock, conversion leaves staked picks to settle as bets.
        assert swiss_card.convert_staked(s, s.get(Season, world["season"]), T0) == 0

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


# ---------------------------------------------------------------- the free record card (D-020)


def _season(s, world):
    return s.get(Season, world["season"])


def test_rewards_are_capped_and_right_side_is_a_quarter():
    assert swiss_card.reward(Decimal("3.00"), "WON") == 300
    assert swiss_card.reward(Decimal("2.50"), "PARTIAL") == 63  # 250 x 0.25 = 62.5 -> 63
    assert swiss_card.reward(Decimal("14.00"), "WON") == 1000  # capped
    assert swiss_card.reward(Decimal("14.00"), "PARTIAL") == 250  # a quarter of the capped reward
    assert swiss_card.reward(Decimal("3.00"), "LOST") == swiss_card.reward(Decimal("3.00"), "VOID") == 0


def test_calls_lock_the_price_respect_row_limits_and_lock_with_the_market(factory, world, monkeypatch):
    market_id = _swiss_world(factory, world)
    join(factory, world, "alice")
    monkeypatch.setitem(swiss_card.SLOTS, "3-1", 1)
    with factory() as s, s.begin():
        season = _season(s, world)
        call = swiss_card.set_call(s, season, world["alice"], market_id, outcome_id(factory, market_id, "3-1"), T0)
        assert call.odds == Decimal("3.00")
        # Changing the call replaces it rather than adding a second one.
        swiss_card.set_call(s, season, world["alice"], market_id, outcome_id(factory, market_id, "3-0"), T0)
        card = swiss_card.card(s, season, world["alice"], T0)
        assert [c["record"] for c in card["calls"]] == ["3-0"] and card["calls"][0]["exact_rc"] == 250
    with factory() as s, s.begin():
        other = make_market(s, _season(s, world), None, "swiss_record", [("3-1", "3–1", "4.00")],
                            params={"team": "t-b"}, scope="STAGE")
        swiss_card.set_call(s, _season(s, world), world["alice"], market_id, outcome_id(factory, market_id, "3-1"),
                            T0)
        with pytest.raises(swiss_card.CardError) as e:  # the 3-1 row (one slot here) is full
            swiss_card.set_call(s, _season(s, world), world["alice"], other.id,
                                s.execute(select(Outcome.id).where(Outcome.market_id == other.id)).scalar_one(), T0)
        assert e.value.code == "ROW_FULL"
    with factory() as s, s.begin():
        s.get(Market, market_id).state = "LOCKED"
    with factory() as s, s.begin(), pytest.raises(swiss_card.CardError):
        swiss_card.clear_call(s, _season(s, world), world["alice"], market_id, T0)


def test_staked_picks_move_to_the_card_and_calls_pay_rewards(factory, world):
    market_id = _swiss_world(factory, world)
    join(factory, world, "alice")
    _place_staked(factory, world, "alice", market_id, "3-1", "staked")
    join(factory, world, "bob")
    with factory() as s, s.begin():
        swiss_card.set_call(s, _season(s, world), world["bob"], market_id, outcome_id(factory, market_id, "3-0"), T0)
    assert balance(factory, world, "alice") == (1900, 0)

    with factory() as s, s.begin():
        assert swiss_card.convert_staked(s, _season(s, world), T0) == 1
    with factory() as s, s.begin():
        assert swiss_card.convert_staked(s, _season(s, world), T0) == 0  # idempotent
    assert balance(factory, world, "alice") == (2000, 0)  # stake refunded
    with factory() as s:
        sel = s.execute(select(Selection)).scalar_one()
        assert sel.status == "VOID" and swiss_card.moved_to_card(sel)
        call = s.execute(select(SwissCall).where(SwissCall.user_id == world["alice"])).scalar_one()
        assert call.odds == Decimal("3.00")  # carried over at the price it was placed at

    with factory() as s, s.begin():
        s.get(Market, market_id).state = "LOCKED"
    _finish_swiss(factory, world, [True, False, True, True])  # 3-1
    with factory() as s, s.begin():
        assert apply_grade(s, market_id, grade_market(s, s.get(Market, market_id)), T0 + timedelta(days=5))
    assert balance(factory, world, "alice") == (2000 + 300, 0)  # exact: 100 x 3.00
    assert balance(factory, world, "bob") == (2000 + 63, 0)  # right side: a quarter of 250
    with factory() as s:
        assert s.execute(select(Selection)).scalar_one().return_rc == 100  # the refunded pick is left alone
        assert {c.status for c in s.execute(select(SwissCall)).scalars()} == {"WON", "PARTIAL"}
