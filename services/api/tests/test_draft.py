"""Champion grid: on-demand champion markets, Fearless pool, and by-team settlement."""

from datetime import date, timedelta

import pytest
from conftest import T0, make_market
from sqlalchemy import select
from test_api import H, api, signup  # noqa: F401  (api is a fixture)

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


def ban_records(s, world, n):
    """`n` games elsewhere at Worlds with Leaguepedia drafts: Ahri banned in half, Vi first pick in 60%."""
    other = Team(provider_id="t-bans", code="BAN", name="Banners")
    s.add(other)
    s.flush()
    fx = Fixture(season_id=world["season"], provider_id="fx-bans", stage="Swiss", best_of=1,
                 team_a_id=world["team_a"], team_b_id=other.id, status="COMPLETED",
                 scheduled_at=T0 - timedelta(days=2), local_date=date(2026, 10, 21))
    s.add(fx)
    s.flush()
    for i in range(n):
        s.add(Game(fixture_id=fx.id, provider_id=f"bans-{i}", game_index=i + 1, state="completed",
                   bans={"source": "leaguepedia", "blue": ["Ahri", "Jax"] if i % 2 else ["Jax"], "red": ["Rell"],
                         "first_pick": "Vi" if i < 6 else "Azir", "first_pick_side": "blue"}))


def test_ban_and_first_pick_scopes_need_ten_games_of_data(factory, history, monkeypatch):
    monkeypatch.setattr(draft, "FIRST_PICK_VERIFIED", True)  # off in production until verified
    with factory() as s, s.begin():
        ban_records(s, history, 9)
    with factory() as s:
        g = draft.grid(s, s.get(Season, history["season"]), _fixture(s, history), 1, SETTINGS)
    assert g["scopes"] == ["picked", "A", "B"]
    assert all(c["odds"]["banned"] is None and c["odds"]["first"] is None for c in g["champions"])
    with factory() as s, s.begin():
        s.add(Game(fixture_id=s.execute(select(Fixture.id).where(Fixture.provider_id == "fx-bans")).scalar_one(),
                   provider_id="bans-9", game_index=10, state="completed",
                   bans={"source": "leaguepedia", "blue": ["Ahri"], "red": ["Jax"], "first_pick": "Vi"}))
    with factory() as s, s.begin():
        season, fx = s.get(Season, history["season"]), _fixture(s, history)
        g = draft.grid(s, season, fx, 1, SETTINGS)
        assert g["scopes"] == ["picked", "A", "B", "banned", "first"]
        by = {c["champion"]: c for c in g["champions"]}
        assert by["Ahri"]["odds"]["banned"] == "2.00" and by["Vi"]["odds"]["first"] == "1.43"
        assert by["Jax"]["odds"]["picked"] is None and by["Jax"]["odds"]["banned"] == "1.05"  # banned, never picked
        assert by["Ahri"]["odds"]["first"] is None  # never first-picked: not offered
        banned = draft.ensure_market(s, season, fx, 1, "Ahri", "banned", SETTINGS, T0)
        first = draft.ensure_market(s, season, fx, 1, "vi", "first", SETTINGS, T0)
        assert (banned.kind, banned.params) == ("champion_banned", {"champion": "Ahri", "game_index": 1})
        assert (first.kind, first.params) == ("champion_first_pick", {"champion": "Vi", "game_index": 1})


def test_role_picks_shrink_team_record_toward_global_role_rate(factory, history):
    with factory() as s, s.begin():
        season, fx = s.get(Season, history["season"]), _fixture(s, history)
        by = {c["champion"]: c for c in draft.grid(s, season, fx, 1, SETTINGS)["champions"]}
        # Atlas played Ahri mid in 2 of its 4 games; Nova has no games, so it gets half the global role rate.
        assert by["Ahri"]["roles"] == {"A": {"mid": "2.86"}, "B": {"mid": "4.00"}}
        assert by["Vi"]["roles"]["A"] == {"jungle": "1.43"}
        market = draft.ensure_market(s, season, fx, 1, "Ahri", "A", SETTINGS, T0, role="mid")
        assert market.params == {"champion": "Ahri", "game_index": 1, "side": "A", "role": "mid"}
        assert market.title == "ATL play Ahri mid in Game 1"
        for scope, role, code in (("A", "top", "NOT_OFFERED"), ("picked", "mid", "BAD_ROLE"),
                                  ("banned", None, "NOT_OFFERED")):
            with pytest.raises(draft.DraftError) as e:
                draft.ensure_market(s, season, fx, 1, "Ahri", scope, SETTINGS, T0, role=role)
            assert e.value.code == code


def test_role_pick_settles_on_role_and_team(factory, history):
    with factory() as s, s.begin():
        season, fx = s.get(Season, history["season"]), _fixture(s, history)
        mid = draft.ensure_market(s, season, fx, 1, "Ahri", "A", SETTINGS, T0, role="mid").id
        anywhere = draft.ensure_market(s, season, fx, 1, "Ahri", "A", SETTINGS, T0).id
        # Atlas pick Ahri but play her top.
        s.add(Game(fixture_id=fx.id, provider_id="g1", game_index=1, state="completed", stats_complete=True,
                   stats={"players": players(history["team_a"], history["team_b"],
                                             a=["Ahri", "Vi", "Aatrox", "Jinx", "Nautilus"])}))
    with factory() as s:
        assert grade_market(s, s.get(Market, mid)).winning_codes == ["NO"]
        assert grade_market(s, s.get(Market, anywhere)).winning_codes == ["YES"]


def test_ban_and_first_pick_grading(factory, history, monkeypatch):
    monkeypatch.setattr(draft, "FIRST_PICK_VERIFIED", True)  # off in production until verified
    with factory() as s, s.begin():
        ban_records(s, history, 10)
    with factory() as s, s.begin():
        season, fx = s.get(Season, history["season"]), _fixture(s, history)
        banned = draft.ensure_market(s, season, fx, 1, "Ahri", "banned", SETTINGS, T0).id
        first = draft.ensure_market(s, season, fx, 1, "Vi", "first", SETTINGS, T0).id
        g2 = make_market(s, season, fx, "champion_banned", [("YES", "Yes", "2.00"), ("NO", "No", "2.00")],
                         params={"champion": "Ahri", "game_index": 2}, scope="GAME").id
        s.add(Game(fixture_id=fx.id, provider_id="g1", game_index=1, state="inProgress"))
    with factory() as s:
        assert grade_market(s, s.get(Market, banned)).status == "PENDING"
        assert grade_market(s, s.get(Market, g2)).status == "PENDING"
    with factory() as s, s.begin():
        s.execute(select(Game).where(Game.provider_id == "g1")).scalar_one().state = "completed"
    with factory() as s:
        assert grade_market(s, s.get(Market, banned)).status == "HOLD"  # Leaguepedia not in yet
        assert grade_market(s, s.get(Market, first)).status == "HOLD"
    with factory() as s, s.begin():
        s.execute(select(Game).where(Game.provider_id == "g1")).scalar_one().bans = {
            "source": "leaguepedia", "blue": ["Jax", "Azir"], "red": ["Kaisa", "Ahri"], "first_pick": None}
    with factory() as s:
        assert grade_market(s, s.get(Market, banned)).winning_codes == ["YES"]
        assert grade_market(s, s.get(Market, first)).status == "HOLD"  # bans in, pick order not yet
    with factory() as s, s.begin():
        game = s.execute(select(Game).where(Game.provider_id == "g1")).scalar_one()
        game.bans = {**game.bans, "first_pick": "MonkeyKing", "first_pick_side": "blue"}
        s.get(Fixture, history["fixture"]).status = "COMPLETED"
    with factory() as s:
        assert grade_market(s, s.get(Market, first)).winning_codes == ["NO"]
        assert grade_market(s, s.get(Market, g2)).status == "VOID"  # Game 2 never played


def test_burned_champions_are_not_offered_to_ban(factory, history):
    with factory() as s, s.begin():
        ban_records(s, history, 10)
        s.add(Game(fixture_id=history["fixture"], provider_id="g1", game_index=1, state="completed",
                   stats_complete=True, stats={"players": players(history["team_a"], history["team_b"])}))
    with factory() as s:
        g = draft.grid(s, s.get(Season, history["season"]), _fixture(s, history), 2, SETTINGS)
        offered = {c["champion"] for c in g["champions"]}
        assert "Ahri" not in offered and "Rell" not in offered and "Jax" in offered


def test_draft_api_shape(api, history):  # noqa: F811
    app, codes = api
    client = signup(app, codes[0], "kai")
    event = str(history["fixture"])
    g = client.get(f"/api/v1/events/{event}/draft?game=1").json()
    assert g["scopes"] == ["picked", "A", "B"]
    ahri = next(c for c in g["champions"] if c["champion"] == "Ahri")
    assert set(ahri["odds"]) == {"picked", "A", "B", "banned", "first"} and ahri["roles"]["A"] == {"mid": "2.86"}
    r = client.post(f"/api/v1/events/{event}/draft", headers=H,
                    json={"game_index": 1, "champion": "Ahri", "scope": "A", "role": "mid"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/events/{event}/draft", headers=H,
                    json={"game_index": 1, "champion": "Ahri", "scope": "banned"})
    assert r.json()["error"]["code"] == "NOT_OFFERED"
