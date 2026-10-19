from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rift.domain.money import settlement_return, winning_return
from rift.domain.pricing import price, series_score_distribution, series_win_probability, total_games_distribution


@given(st.floats(min_value=0.01, max_value=0.99), st.sampled_from([1, 3, 5]))
def test_series_distributions_sum_to_one(q, bo):
    assert sum(series_score_distribution(q, bo).values()) == pytest.approx(1.0)
    assert sum(total_games_distribution(q, bo).values()) == pytest.approx(1.0)


def test_known_closed_forms():
    q = 0.6
    assert series_win_probability(q, 3) == pytest.approx(3 * q**2 - 2 * q**3)
    assert series_win_probability(q, 5) == pytest.approx(10 * q**3 - 15 * q**4 + 6 * q**5)
    d = series_score_distribution(q, 3)
    assert set(d) == {(2, 0), (2, 1), (0, 2), (1, 2)}
    assert d[(2, 1)] == pytest.approx(2 * q**2 * (1 - q))
    assert set(series_score_distribution(q, 5)) == {(3, 0), (3, 1), (3, 2), (0, 3), (1, 3), (2, 3)}


def test_price_bounds():
    kw = dict(min_probability=Decimal("0.01"), max_odds=Decimal("100"))
    assert price(0.7, **kw) == Decimal("1.43")
    assert price(0.3, **kw) == Decimal("3.33")
    assert price(0.0, **kw) is None
    assert price(1.0, **kw) is None
    assert price(0.999, **kw) is None  # would round to 1.00x
    assert price(0.005, **kw) is None


def test_return_arithmetic_matches_spec_examples():
    assert winning_return(400, Decimal("1.45")) == 580
    assert winning_return(400, Decimal("1.62")) == 648
    assert winning_return(250, Decimal("3.40")) == 850
    assert winning_return(1, Decimal("1.50")) == 2  # half-up
    assert settlement_return(300, Decimal("2.10"), "VOID") == 300
    assert settlement_return(300, Decimal("2.10"), "LOST") == 0
