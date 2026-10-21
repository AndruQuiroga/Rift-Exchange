"""Players & game: objective markets, lane duels and any-line kill totals, all graded from the timeline."""

from datetime import date, timedelta

import pytest
from conftest import T0
from sqlalchemy import select

from rift import props
from rift.config import Settings
from rift.markets import game_specs, tournament_stats
from rift.models import Fixture, Game, Market, Outcome, Season, Selection, Team
from rift.settlement import grade_market

SETTINGS = Settings()
ROLES = props.ROLES


def timeline(a_id, b_id, *, a_kills=(3, 2, 4, 1, 0), b_kills=(1, 1, 2, 2, 0), a_cs=(130, 100, 140, 150, 20),
             b_cs=(120, 105, 135, 150, 25), a_gold=(5200, 4800, 6400, 6100, 3200),
             b_gold=(5000, 4900, 5500, 6000, 3100), blood="A", dragon="infernal", soul="ocean", baron_at=1400,
             prefix=("a", "b")):
    side_team = {"A": str(a_id), "B": str(b_id)}
    participants, final, at15 = {}, {}, {}
    sides = (("blue", a_kills, a_cs, a_gold, prefix[0]), ("red", b_kills, b_cs, b_gold, prefix[1]))
    for s, (side, kills, cs, gold, tag) in enumerate(sides):
        for i, role in enumerate(ROLES):
            pid = str(s * 5 + i + 1)
            participants[pid] = {"player_id": f"{tag}-{role}", "name": f"{tag.upper()} {role}", "role": role,
                                 "side": side, "champion": f"C{pid}"}
            final[pid] = {"kills": kills[i], "deaths": 1, "assists": 1, "cs": cs[i] * 2, "gold": 9000,
                          "damage_share": 0.1 + 0.02 * i + 0.01 * s, "kill_participation": 0.5}
            at15[pid] = {"cs": cs[i], "gold": gold[i]}
    first = {"side": "blue", "team_id": side_team[blood], "at_s": 300}
    return {"participants": participants, "final": final, "at_15": {"at_s": 900, "players": at15},
            "firsts": {"blood": first, "tower": {**first, "at_s": 800},
                       "dragon": {**first, "type": dragon, "at_s": 400}, "five_kills": {**first, "at_s": 500},
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


def test_objective_markets_open_with_each_game(factory, season_games):
    with factory() as s:
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        a, b = s.get(Team, fx.team_a_id), s.get(Team, fx.team_b_id)
        specs = {sp.kind: sp for sp in game_specs(fx, 2, a, b, 0.6, tournament_stats(s, season), T0, "EXPERIMENTAL")}
    assert set(props.OFFERED_OBJECTIVES) <= set(specs)
    assert not set(props.RETIRED_OBJECTIVES) & set(specs)  # dragon element and soul are no longer offered
    blood = {o.code: o.probability for o in specs["first_blood"].outcomes}
    assert blood["A"] > 0.5  # A is the stronger side and winners have taken first blood every time
    assert specs["baron_before"].params == {"game_index": 2}


@pytest.mark.parametrize("kind,codes", [("first_blood", ["A"]), ("first_tower", ["A"]), ("five_kills", ["A"]),
                                        ("first_dragon", ["A"]), ("gold_lead_15", ["A"]),
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


def _live_game1(factory, world, *, blood_at=None):
    """The world fixture is live and Game 1 has loaded at T0 (champions known); first blood optional."""
    with factory() as s, s.begin():
        fx = s.get(Fixture, world["fixture"])
        fx.status = "LIVE"
        tl = timeline(fx.team_a_id, fx.team_b_id, a_kills=(1, 1, 5, 2, 0), b_kills=(1, 1, 2, 2, 0))
        tl["firsts"] = {"blood": {"side": "blue", "team_id": str(fx.team_a_id), "at_s": blood_at}} if blood_at else {}
        s.add(Game(fixture_id=fx.id, provider_id="g1", game_index=1, state="inProgress", started_at=T0,
                   blue_team_id=fx.team_a_id, red_team_id=fx.team_b_id, timeline=tl))


def _finish_game1(factory, world):
    with factory() as s, s.begin():
        g = s.execute(select(Game).where(Game.provider_id == "g1")).scalar_one()
        g.state, g.ended_at, g.timeline_complete = "completed", T0 + timedelta(minutes=30), True
        tl = dict(g.timeline)
        tl["firsts"] = {**timeline(world["team_a"], world["team_b"])["firsts"], **tl["firsts"]}
        g.timeline = tl


def test_early_window_opens_at_game_load_and_closes_at_three_minutes(factory, season_games):
    with factory() as s:
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        before = props.duels(s, season, fx, 1, SETTINGS, T0)
        assert before["state"] == "UPCOMING" and "loads" in before["opens_when"]
        assert all(row["odds"]["gold15"]["A"] is None for row in before["duels"])  # preview: no prices yet
    _live_game1(factory, season_games)
    with factory() as s:
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        grid = props.duels(s, season, fx, 1, SETTINGS, T0 + timedelta(minutes=1))
        assert grid["open"] and grid["close_at"] == (T0 + timedelta(minutes=3)).isoformat()
        mid = next(d for d in grid["duels"] if d["role"] == "mid")
        assert mid["a"]["champion"] == "C3" and mid["odds"]["gold15"]["A"]
        assert not props.duels(s, season, fx, 1, SETTINGS, T0 + timedelta(minutes=3))["open"]


def test_first_blood_does_not_close_the_window(factory, season_games):
    _live_game1(factory, season_games, blood_at=95)
    with factory() as s:
        fx = s.get(Fixture, season_games["fixture"])
        w = props.early_window(s, fx, 1, T0 + timedelta(seconds=96))
        assert w.open and w.close_at == T0 + timedelta(minutes=3)
        assert not props.early_window(s, fx, 1, T0 + timedelta(minutes=3)).open


def test_lane_duel_priced_created_once_and_graded(factory, season_games):
    _live_game1(factory, season_games)
    at = T0 + timedelta(minutes=1)
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        first = props.ensure_duel(s, season, fx, 1, "mid", "gold15", SETTINGS, at)
        assert props.ensure_duel(s, season, fx, 1, "mid", "gold15", SETTINGS, at).id == first.id
        assert first.close_at == T0 + timedelta(minutes=3) and first.params["a_champion"] == "C3"
        tie = props.ensure_duel(s, season, fx, 1, "bottom", "gold15", SETTINGS, at)  # bottoms 100 gold apart at 15:00
        first_id, tie_id = first.id, tie.id
        with pytest.raises(props.PropsError):
            props.ensure_duel(s, season, fx, 1, "top", "gold15", SETTINGS, T0 + timedelta(minutes=4))
    _finish_game1(factory, season_games)
    with factory() as s:
        assert grade_market(s, s.get(Market, first_id)).winning_codes == ["A"]
        assert grade_market(s, s.get(Market, tie_id)).status == "VOID"


def test_picks_after_first_blood_stand_and_after_three_minutes_are_void(factory, season_games):
    from test_money import balance, join, place

    from rift.markets import lock_due
    from rift.settlement import apply_grade

    _live_game1(factory, season_games)
    at = T0 + timedelta(seconds=60)
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        duel = props.ensure_duel(s, season, fx, 1, "mid", "gold15", SETTINGS, at)
        outcome = next(o for o in s.execute(select(Outcome).where(Outcome.market_id == duel.id)).scalars()
                       if o.code == "A")
        duel_id, outcome_id = duel.id, outcome.id
    join(factory, season_games, "alice")
    join(factory, season_games, "bob")
    place(factory, season_games, "alice", [(outcome_id, 100)], "early", now=at)
    # First blood at 1:30 by the feed's clock no longer closes anything: Bob's pick at 2:40 stands.
    with factory() as s, s.begin():
        g = s.execute(select(Game).where(Game.provider_id == "g1")).scalar_one()
        g.timeline = {**g.timeline, "firsts": {"blood": {"side": "blue", "team_id": str(g.blue_team_id), "at_s": 90}}}
    place(factory, season_games, "bob", [(outcome_id, 100)], "after-blood", now=T0 + timedelta(seconds=160))
    with factory() as s, s.begin():
        assert props.tighten_early(s, T0 + timedelta(seconds=170)) == 0
        lock_due(s, T0 + timedelta(minutes=3))
        assert s.get(Market, duel_id).state == "LOCKED"
    _finish_game1(factory, season_games)
    with factory() as s, s.begin():
        apply_grade(s, duel_id, grade_market(s, s.get(Market, duel_id)), T0 + timedelta(hours=1))
    with factory() as s:
        rows = {sel.user_id: sel for sel in s.execute(select(Selection)).scalars()}
    assert rows[season_games["alice"]].status == rows[season_games["bob"]].status == "WON"

    # A corrected final scan puts the game's start 30 s earlier: Bob's pick (now 3:10 in) is void.
    with factory() as s, s.begin():
        g = s.execute(select(Game).where(Game.provider_id == "g1")).scalar_one()
        g.started_at = T0 - timedelta(seconds=30)
        assert apply_grade(s, duel_id, grade_market(s, s.get(Market, duel_id)), T0 + timedelta(hours=2))
    with factory() as s:
        bob = s.execute(select(Selection).where(Selection.user_id == season_games["bob"])).scalar_one()
    assert bob.status == "VOID" and bob.return_rc == 100
    assert balance(factory, season_games, "bob") == (2000, 0)


def test_any_kill_line_is_one_shared_market(factory, season_games):
    _live_game1(factory, season_games)
    at = T0 + timedelta(minutes=1)
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        stats = tournament_stats(s, season)
        assert props.kill_lines(s, fx, 1, stats, SETTINGS, T0 - timedelta(minutes=5))["lines"] == []  # not loaded
        grid = props.kill_lines(s, fx, 1, stats, SETTINGS, at)
        offered = [row["line"] for row in grid["lines"]]
        assert grid["open"] and offered and min(float(x) for x in offered) >= props.KILL_LINE_FLOOR
        line = offered[len(offered) // 2]
        m = props.ensure_kill_line(s, season, fx, 1, line, stats, SETTINGS, at)
        again = props.ensure_kill_line(s, season, fx, 1, line, stats, SETTINGS, at)
        assert m.id == again.id and m.params == {"game_index": 1, "line": line, "early": True}
        assert m.close_at == T0 + timedelta(minutes=3)
        for bad in ("31.0", "14.5"):  # not a half line; a line nobody should be offered (every game had 40)
            with pytest.raises(props.PropsError):
                props.ensure_kill_line(s, season, fx, 1, bad, stats, SETTINGS, at)
        # Twelve kills in the first minutes lift the lowest line to 17.5 (5 clear of the count so far).
        g = s.execute(select(Game).where(Game.provider_id == "g1")).scalar_one()
        g.timeline = {**g.timeline, "live": {"kills": {"A": 7, "B": 5}}}
        s.flush()
        assert props.kill_line_floor(g) == 17.5
        assert all(float(r["line"]) >= 17.5 for r in props.kill_lines(s, fx, 1, stats, SETTINGS, at)["lines"])
        with pytest.raises(props.PropsError, match="start at 17.5"):
            props.ensure_kill_line(s, season, fx, 1, "16.5", stats, SETTINGS, at)


class _RegionalFeed:
    """Atlas's last regional match: one completed game with Atlas on red."""

    def event_details(self, match_id):
        from rift.adapters.lolesports import GameRef, MatchDetail
        return MatchDetail(match_id, [("e-x", "Xeno", 1), ("e-atl", "Atlas", 2)],
                           [GameRef("rg1", 1, "completed", "e-x", "e-atl"), GameRef("rg2", 2, "unneeded", None, None)])

    def window(self, game_id):
        from rift.adapters.lolesports import GameStats, PlayerLine
        players = [PlayerLine(i + 1, f"{side}-{role}", f"{side.upper()} {role}", side, role, "C", 0, 0, 0)
                   for side in ("blue", "red") for i, role in enumerate(ROLES)]
        return GameStats(game_id, None, "finished", T0, T0, "e-x", "e-atl", players)


def test_regional_lineup_until_a_team_plays_at_worlds(factory, world):
    from rift.ingest import sync_lineups
    from rift.models import HistoricalResult

    with factory() as s, s.begin():
        x = Team(provider_id="lolesports:xeno", code="XEN", name="Xeno")
        s.add(x)
        s.flush()
        s.get(Team, world["team_a"]).provider_id = "lolesports:atlas"
        s.add(HistoricalResult(provider_id="reg-1", league_slug="lck", played_at=T0 - timedelta(days=30),
                               team_a_id=x.id, team_b_id=world["team_a"], team_a_wins=1, team_b_wins=2))
    with factory() as s, s.begin():
        sync_lineups(s, s.get(Season, world["season"]), _RegionalFeed(), T0)
    with factory() as s:
        atlas = s.get(Team, world["team_a"])
        assert atlas.lineup["players"]["mid"] == {"player_id": "red-mid", "name": "RED mid"}
        assert props.lineups(s, s.get(Fixture, world["fixture"]))["A"]["mid"]["name"] == "RED mid"

def test_quote_after_first_blood_is_fine_but_not_after_three_minutes(factory, season_games):
    from test_money import join

    from rift.placement import PlacementError, QuoteItem, create_quote

    _live_game1(factory, season_games)
    at = T0 + timedelta(seconds=60)
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        duel = props.ensure_duel(s, season, fx, 1, "mid", "gold15", SETTINGS, at)
        oid = s.execute(select(Outcome.id).where(Outcome.market_id == duel.id, Outcome.code == "A")).scalar_one()
        game = s.execute(select(Game).where(Game.provider_id == "g1")).scalar_one()
        game.timeline = {**game.timeline, "firsts": {"blood": {"at_s": 90}}}
    join(factory, season_games, "alice")
    with factory() as s, s.begin():  # first blood at 1:30 no longer closes the window
        create_quote(s, season_id=season_games["season"], user_id=season_games["alice"],
                     items=[QuoteItem(oid, 100)], now=T0 + timedelta(seconds=100), ttl_seconds=20)
    with factory() as s, s.begin(), pytest.raises(PlacementError, match="window has closed"):  # before the worker locks
        create_quote(s, season_id=season_games["season"], user_id=season_games["alice"],
                     items=[QuoteItem(oid, 100)], now=T0 + timedelta(seconds=181), ttl_seconds=20)


def test_first_to_five_kills_is_recorded_from_the_fifth_kill():
    from rift.timeline import summarise

    t0 = T0
    at = lambda s_: (t0 + timedelta(seconds=s_)).isoformat()
    events = {f"kills:blue:{n}": {"at": at(60 * n), "type": None} for n in range(1, 6)}
    events |= {f"kills:red:{n}": {"at": at(50 * n), "type": None} for n in range(1, 5)}
    summary = summarise(events, {"blue": "team-blue", "red": "team-red"}, t0, complete=True)
    assert summary["firsts"]["five_kills"] == {"side": "blue", "team_id": "team-blue", "at_s": 300}
    assert summary["firsts"]["blood"]["side"] == "red"  # red drew first blood at 0:50 but stalled on four
    assert summarise({}, {}, t0, complete=True)["firsts"]["five_kills"] is None


class _Model:
    def game_probability(self, a, b):
        return 0.6


def test_team_races_open_with_the_game_and_close_at_three_minutes(factory, season_games):
    _live_game1(factory, season_games)
    with factory() as s, s.begin():
        season = s.get(Season, season_games["season"])
        assert props.open_early_team_markets(s, season, SETTINGS, _Model(), T0 + timedelta(minutes=1)) == 3
        races = {m.kind: m for m in s.execute(select(Market).where(Market.kind.in_(props.EARLY_TEAM_KINDS))).scalars()}
        assert set(races) == set(props.EARLY_TEAM_KINDS)
        assert all(m.close_at == T0 + timedelta(minutes=3) and m.params["early"] for m in races.values())
    with factory() as s, s.begin():  # after 3:00 nothing new opens
        season = s.get(Season, season_games["season"])
        assert props.open_early_team_markets(s, season, SETTINGS, _Model(), T0 + timedelta(minutes=4)) == 0


def test_team_gold_lead_under_700_is_a_tie(factory, world):
    close = (5100, 4900, 6200, 6100, 3200)  # 25,500 against the default 24,500: a 1,000 lead
    with factory() as s, s.begin():
        m = Market(season_id=world["season"], fixture_id=world["fixture"], template_key="gold_lead_15:x",
                   kind="gold_lead_15", scope="GAME", category="OBJECTIVES", title="g", rules_text="",
                   params={"game_index": 1}, model_key="t", confidence="EXPERIMENTAL", close_at=T0)
        g = Game(fixture_id=world["fixture"], provider_id="g1", game_index=1, state="completed",
                 blue_team_id=world["team_a"], red_team_id=world["team_b"], timeline_complete=True,
                 timeline=timeline(world["team_a"], world["team_b"], a_gold=close))
        s.add_all([m, g])
        s.flush()
        assert grade_market(s, m).winning_codes == ["A"]
        g.timeline = timeline(world["team_a"], world["team_b"], a_gold=(5000, 4800, 5900, 6000, 3200))  # +400
        assert grade_market(s, m).status == "VOID"
