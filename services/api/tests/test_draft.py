"""Champion grid: on-demand champion markets, Fearless pool, and by-team settlement."""

from datetime import date, timedelta

import pytest
from conftest import T0
from sqlalchemy import select

from rift import draft
from rift.config import Settings
from rift.models import Fixture, Game, Market, Season, Team
from rift.settlement import grade_market

SETTINGS = Settings()
A_CHAMPS = ["Aatrox", "Vi", "Ahri", "Jinx", "Nautilus"]
B_CHAMPS = ["Gnar", "Sejuani", "Orianna", "Kalista", "Rell"]


def players(a_id, b_id, a=A_CHAMPS, b=B_CHAMPS):
    roles = ["top", "jungle", "mid", "bottom", "support"]
    return [{"player_id": f"{side}{i}", "name": f"{side}{i}", "side": side, "team_id": str(tid), "role": roles[i],
             "champion": c, "kills": 1, "deaths": 1, "assists": 1}
            for side, tid, champs in (("blue", a_id, a), ("red", b_id, b)) for i, c in enumerate(champs)]


@pytest.fixture
def history(factory, world):
    """Four verified games elsewhere at Worlds so every champion above has a pick rate."""
    with factory() as s, s.begin():
        other = Team(provider_id="t-o", code="OTH", name="Other")
        s.add(other)
        s.flush()
        past = Fixture(season_id=world["season"], provider_id="fx-past", stage="Swiss", best_of=1,
                       team_a_id=world["team_a"], team_b_id=other.id, status="COMPLETED",
                       scheduled_at=T0 - timedelta(days=1), local_date=date(2026, 10, 22))
        s.add(past)
        s.flush()
        for i in range(4):
            a = A_CHAMPS if i % 2 == 0 else ["Rumble", "Vi", "Azir", "Varus", "Rakan"]
            s.add(Game(fixture_id=past.id, provider_id=f"past-{i}", game_index=i + 1, state="completed",
                       stats_complete=True, stats={"players": players(world["team_a"], other.id, a=a)}))
    return world


def _fixture(s, world):
    return s.get(Fixture, world["fixture"])


def test_grid_prices_seen_champions_and_team_scopes(factory, history):
    with factory() as s:
        g = draft.grid(s, s.get(Season, history["season"]), _fixture(s, history), 1, SETTINGS)
    assert g["open"] and g["burned"] == [] and g["games_observed"] == 4
    by = {c["champion"]: c for c in g["champions"]}
    # Vi was picked in all four games: shortest price, and Atlas (team A) played it every time.
    assert float(by["Vi"]["odds"]["picked"]) < float(by["Ahri"]["odds"]["picked"])
    assert float(by["Vi"]["odds"]["A"]) < float(by["Vi"]["odds"]["B"])


def test_tapping_a_champion_creates_one_shared_market(factory, history):
    with factory() as s, s.begin():
        season, fx = s.get(Season, history["season"]), _fixture(s, history)
        first = draft.ensure_market(s, season, fx, 1, "Ahri", "A", SETTINGS, T0)
        again = draft.ensure_market(s, season, fx, 1, "Ahri", "A", SETTINGS, T0)
        assert first.id == again.id and first.params == {"champion": "Ahri", "game_index": 1, "side": "A"}
        assert first.close_at == fx.scheduled_at  # Game 1 locks with the series
        with pytest.raises(draft.DraftError) as e:
            draft.ensure_market(s, season, fx, 2, "Ahri", "picked", SETTINGS, T0)
        assert e.value.code == "NOT_OPEN"  # Game 2 opens only when Game 1 ends


def test_fearless_removes_earlier_picks(factory, history):
    with factory() as s, s.begin():
        s.add(Game(fixture_id=history["fixture"], provider_id="g1", game_index=1, state="completed",
                   stats_complete=True, stats={"players": players(history["team_a"], history["team_b"])}))
    with factory() as s:
        g = draft.grid(s, s.get(Season, history["season"]), _fixture(s, history), 2, SETTINGS)
    offered = {c["champion"] for c in g["champions"]}
    assert {c["champion"] for c in g["burned"]} == set(A_CHAMPS + B_CHAMPS)
    assert not offered & set(A_CHAMPS + B_CHAMPS)
    assert {"Rumble", "Azir"} <= offered


def test_by_team_pick_settles_on_that_team_only(factory, history):
    with factory() as s, s.begin():
        season, fx = s.get(Season, history["season"]), _fixture(s, history)
        mine = draft.ensure_market(s, season, fx, 1, "Ahri", "A", SETTINGS, T0).id
        theirs = draft.ensure_market(s, season, fx, 1, "Ahri", "B", SETTINGS, T0).id
        s.add(Game(fixture_id=fx.id, provider_id="g1", game_index=1, state="completed", stats_complete=True,
                   stats={"players": players(history["team_a"], history["team_b"])}))
    with factory() as s:
        assert grade_market(s, s.get(Market, mine)).winning_codes == ["YES"]
        assert grade_market(s, s.get(Market, theirs)).winning_codes == ["NO"]
        assert s.execute(select(Market).where(Market.kind == "champion_picked")).scalars().all()
