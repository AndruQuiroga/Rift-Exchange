"""Players & game: objective markets, lane duels and any-line kill totals, all graded from the timeline."""

from datetime import date, timedelta

import pytest
from conftest import T0
from sqlalchemy import select

from rift import props
from rift.config import Settings
from rift.markets import game_specs, tournament_stats
from rift.models import Fixture, Game, Market, Season, Team
from rift.settlement import grade_market

SETTINGS = Settings()
ROLES = props.ROLES


def timeline(a_id, b_id, *, a_kills=(3, 2, 4, 1, 0), b_kills=(1, 1, 2, 2, 0), a_cs=(130, 100, 140, 150, 20),
             b_cs=(120, 105, 135, 150, 25), blood="A", dragon="infernal", soul="ocean", baron_at=1400,
             prefix=("a", "b")):
    side_team = {"A": str(a_id), "B": str(b_id)}
    participants, final, at15 = {}, {}, {}
    for s, (side, kills, cs, tag) in enumerate((("blue", a_kills, a_cs, prefix[0]), ("red", b_kills, b_cs, prefix[1]))):
        for i, role in enumerate(ROLES):
            pid = str(s * 5 + i + 1)
            participants[pid] = {"player_id": f"{tag}-{role}", "name": f"{tag.upper()} {role}", "role": role,
                                 "side": side, "champion": f"C{pid}"}
            final[pid] = {"kills": kills[i], "deaths": 1, "assists": 1, "cs": cs[i] * 2, "gold": 9000,
                          "damage_share": 0.1 + 0.02 * i + 0.01 * s, "kill_participation": 0.5}
            at15[pid] = {"cs": cs[i], "gold": 5000}
    first = {"side": "blue", "team_id": side_team[blood], "at_s": 300}
    return {"participants": participants, "final": final, "at_15": {"at_s": 900, "players": at15},
            "firsts": {"blood": first, "tower": {**first, "at_s": 800},
                       "dragon": {**first, "type": dragon, "at_s": 400},
                       "baron": {**first, "at_s": baron_at} if baron_at else None},
            "dragons": [], "soul": soul}


@pytest.fixture
def season_games(factory, world):
    """Fifteen completed games of the two world teams (A always blue) so every model has data."""
    with factory() as s, s.begin():
        past = Fixture(season_id=world["season"], provider_id="fx-past", stage="Swiss", best_of=5,
                       team_a_id=world["team_a"], team_b_id=world["team_b"], status="COMPLETED",
                       scheduled_at=T0 - timedelta(days=2), local_date=date(2026, 10, 21))
        s.add(past)
        s.flush()
        for i in range(15):
            s.add(Game(fixture_id=past.id, provider_id=f"past-{i}", game_index=i + 1, state="completed",
                       blue_team_id=world["team_a"], red_team_id=world["team_b"], winner_team_id=world["team_a"],
                       started_at=T0 - timedelta(days=2, hours=-i), timeline_complete=True,
                       stats_complete=True, stats={"players": [{"champion": "X", "kills": 4, "role": "top"}] * 10},
                       timeline=timeline(world["team_a"], world["team_b"], soul="ocean" if i % 2 else None)))
    return world


def _open_game1(factory, world):
    """Game 1 of the world fixture with its series winner market OPEN (the conftest market is a series_winner)."""
    with factory() as s, s.begin():
        s.get(Market, world["market"]).kind = "series_winner"


def test_objective_markets_open_with_each_game(factory, season_games):
    with factory() as s:
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        a, b = s.get(Team, fx.team_a_id), s.get(Team, fx.team_b_id)
        specs = {sp.kind: sp for sp in game_specs(fx, 2, a, b, 0.6, tournament_stats(s, season), T0, "EXPERIMENTAL")}
    assert set(props.OBJECTIVE_KINDS) <= set(specs)
    blood = {o.code: o.probability for o in specs["first_blood"].outcomes}
    assert blood["A"] > 0.5  # A is the stronger side and winners have taken first blood every time
    assert specs["dragon_soul"].outcomes[-1].code == "NONE"
    assert specs["baron_before"].params == {"game_index": 2}


@pytest.mark.parametrize("kind,codes", [("first_blood", ["A"]), ("first_tower", ["A"]),
                                        ("first_dragon_type", ["infernal"]), ("baron_before", ["YES"]),
                                        ("dragon_soul", ["ocean"])])
def test_objectives_grade_from_the_timeline(factory, world, kind, codes):
    with factory() as s, s.begin():
        m = Market(season_id=world["season"], fixture_id=world["fixture"], template_key=f"{kind}:x", kind=kind,
                   scope="GAME", category="OBJECTIVES", title=kind, rules_text="", params={"game_index": 1},
                   model_key="t", confidence="EXPERIMENTAL", close_at=T0)
        g = Game(fixture_id=world["fixture"], provider_id="g1", game_index=1, state="completed",
                 blue_team_id=world["team_a"], red_team_id=world["team_b"], timeline_complete=False,
                 timeline=timeline(world["team_a"], world["team_b"]))
        s.add_all([m, g])
        s.flush()
        assert grade_market(s, m).status == "HOLD"  # timeline not complete yet
        g.timeline_complete = True
        assert grade_market(s, m).winning_codes == codes


def test_late_or_missing_baron_and_no_soul(factory, world):
    with factory() as s, s.begin():
        g = Game(fixture_id=world["fixture"], provider_id="g1", game_index=1, state="completed",
                 timeline_complete=True, timeline=timeline(world["team_a"], world["team_b"], baron_at=None, soul=None))
        s.add(g)
        markets = {k: Market(season_id=world["season"], fixture_id=world["fixture"], template_key=f"{k}:x", kind=k,
                             scope="GAME", category="OBJECTIVES", title=k, rules_text="", params={"game_index": 1},
                             model_key="t", confidence="EXPERIMENTAL", close_at=T0)
                   for k in ("baron_before", "dragon_soul")}
        s.add_all(markets.values())
        s.flush()
        assert grade_market(s, markets["baron_before"]).winning_codes == ["NO"]
        assert grade_market(s, markets["dragon_soul"]).winning_codes == ["NONE"]


def test_lane_duel_priced_created_once_and_graded(factory, season_games):
    _open_game1(factory, season_games)
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        grid = props.duels(s, season, fx, 1, SETTINGS)
        assert grid["open"] and [d["role"] for d in grid["duels"]] == list(ROLES)
        mid = next(d for d in grid["duels"] if d["role"] == "mid")
        assert mid["a"]["name"] == "A mid" and float(mid["odds"]["kills"]["A"]) < float(mid["odds"]["kills"]["B"])
        first = props.ensure_duel(s, season, fx, 1, "mid", "kills", SETTINGS, T0)
        assert props.ensure_duel(s, season, fx, 1, "mid", "kills", SETTINGS, T0).id == first.id
        tie = props.ensure_duel(s, season, fx, 1, "bottom", "kills", SETTINGS, T0)  # both bottoms get 2 below
        s.add(Game(fixture_id=fx.id, provider_id="g1", game_index=1, state="completed", timeline_complete=True,
                   blue_team_id=fx.team_a_id, red_team_id=fx.team_b_id,
                   timeline=timeline(fx.team_a_id, fx.team_b_id, a_kills=(1, 1, 5, 2, 0), b_kills=(1, 1, 2, 2, 0))))
        s.flush()
        assert grade_market(s, first).winning_codes == ["A"]
        assert grade_market(s, tie).status == "VOID"  # 2 v 2: exact tie


def test_duel_voids_when_a_player_sits_out(factory, season_games):
    _open_game1(factory, season_games)
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        duel = props.ensure_duel(s, season, fx, 1, "top", "cs15", SETTINGS, T0)
        s.add(Game(fixture_id=fx.id, provider_id="g1", game_index=1, state="completed", timeline_complete=True,
                   blue_team_id=fx.team_a_id, red_team_id=fx.team_b_id,
                   timeline=timeline(fx.team_a_id, fx.team_b_id, prefix=("sub", "b"))))
        s.flush()
        assert grade_market(s, duel).status == "VOID"


def test_any_kill_line_is_one_shared_market(factory, season_games):
    _open_game1(factory, season_games)
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        stats = tournament_stats(s, season)
        grid = props.kill_lines(s, fx, 1, stats, SETTINGS)
        offered = [row["line"] for row in grid["lines"]]
        assert grid["open"] and offered and "14.5" not in offered  # every game had 40 kills: 14.5 is a lock
        line = offered[len(offered) // 2]
        m = props.ensure_kill_line(s, season, fx, 1, line, stats, SETTINGS, T0)
        again = props.ensure_kill_line(s, season, fx, 1, line, stats, SETTINGS, T0)
        assert m.id == again.id and m.params == {"game_index": 1, "line": line}
        for bad in ("31.0", "14.5"):  # not a half line; a line nobody should be offered
            with pytest.raises(props.PropsError):
                props.ensure_kill_line(s, season, fx, 1, bad, stats, SETTINGS, T0)
        assert s.execute(select(Market).where(Market.kind == "total_kills_game")).scalars().all()
