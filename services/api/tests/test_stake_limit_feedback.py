import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest

from rift.models import Fixture, Market, Outcome, Wallet
from rift.placement import PlacementError, QuoteItem, create_quote


def slip(stakes, already):
    """Exercise quote validation with real models and a read-only query stub."""
    now = datetime(2026, 10, 23, tzinfo=UTC)
    season_id, user_id = uuid.uuid4(), uuid.uuid4()
    rows, items = [], []
    for index, stake in enumerate(stakes):
        market = Market(id=uuid.uuid4(), fixture_id=uuid.uuid4(), season_id=season_id,
                        title=f"Prediction {index + 1}", kind="first_tower", params={},
                        state="OPEN", close_at=now + timedelta(hours=1))
        outcome = Outcome(id=uuid.uuid4(), market_id=market.id, label="T1", odds=Decimal("2.06"),
                          odds_version=1)
        rows.append((outcome, market))
        items.append(QuoteItem(outcome.id, stake))
    session = Mock()
    session.get.return_value = Fixture(stage="Swiss")
    session.execute.return_value.all.return_value = rows
    session.execute.return_value.scalar.side_effect = already
    session.execute.return_value.scalar_one_or_none.return_value = Wallet(available_rc=4424)
    return session, dict(season_id=season_id, user_id=user_id, items=items, now=now,
                         ttl_seconds=20, stake_cap_rc=1000), rows


def test_custom_whole_credit_amount_is_accepted():
    session, args, _ = slip([424], [0])
    quote = create_quote(session, **args)
    assert quote["total_stake_rc"] == 424
    assert quote["items"][0]["stake_rc"] == 424


def test_all_over_limit_picks_are_identified_before_a_quote_is_saved():
    session, args, rows = slip([1000, 424, 1000], [700, 0, 1000])
    with pytest.raises(PlacementError) as error:
        create_quote(session, **args)
    assert error.value.code == "STAKE_LIMIT"
    violations = error.value.details["violations"]
    assert [v["market_id"] for v in violations] == [str(rows[0][1].id), str(rows[2][1].id)]
    assert [(v["placed_rc"], v["max_stake_rc"]) for v in violations] == [(700, 300), (1000, 0)]
    assert "No bets were placed" in error.value.message
    session.add.assert_not_called()


def test_single_limit_names_market_and_explains_cumulative_allowance():
    session, args, _ = slip([301], [700])
    with pytest.raises(PlacementError) as error:
        create_quote(session, **args)
    assert "Prediction 1" in error.value.message
    assert "700 RC staked" in error.value.message
    assert "300 RC more" in error.value.message
    assert error.value.details["requested_stake_rc"] == 301
    assert error.value.details["max_stake_rc"] == 300
    assert len(error.value.details["violations"]) == 1


def test_bet_equal_to_remaining_room_is_accepted():
    session, args, _ = slip([300], [700])
    assert create_quote(session, **args)["total_stake_rc"] == 300
