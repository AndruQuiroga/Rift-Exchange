"""Players & game: objective markets, lane duels and any-line kill totals, all graded from the timeline."""

from datetime import date, timedelta

import pytest
from conftest import T0
from sqlalchemy import select

from rift import props
from rift.config import Settings
from rift.markets import game_specs, series_close, tournament_stats, upsert_market
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
    assert set(props.OFFERED_OBJECTIVES) - {"game_length"} <= set(specs)
    assert "game_length" not in specs  # no game times recorded yet
    assert not set(props.RETIRED_OBJECTIVES) & set(specs)  # dragon element and soul are no longer offered
    blood = {o.code: o.probability for o in specs["first_blood"].outcomes}
    assert blood["A"] > 0.5  # A is the stronger side and winners have taken first blood every time
    assert specs["baron_before"].params == {"game_index": 2, "blind": True}  # D-040: blind, closing at the draft
    assert specs["baron_before"].template_key.endswith(":blind") and "(blind)" in specs["baron_before"].title


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
        fx.status = "LIVE"  # the series has started (its draft is under way) but Game 1 hasn't loaded
        before = props.duels(s, season, fx, 1, SETTINGS, fx.scheduled_at + timedelta(minutes=1))
        assert before["phase"] == "DRAFT" and "loads" in before["opens_when"]
        assert all(row["odds"]["gold15"]["A"] is None for row in before["duels"])  # preview: no prices yet
        s.rollback()
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
        tie_grade = grade_market(s, s.get(Market, tie_id))  # D-036: a tie is half back for both sides
        assert (tie_grade.status, tie_grade.winning_codes, tie_grade.partial_codes) == ("RESULT", [], ["A", "B"])


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
        assert props.kill_lines(s, fx, 1, stats, SETTINGS, at)["phase"] == "LIVE"
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
        # Three team races and the after-draft first blood, first tower and Baron (D-040).
        assert props.open_early_team_markets(s, season, SETTINGS, _Model(), T0 + timedelta(minutes=1)) == 6
        races = {m.kind: m for m in s.execute(select(Market).where(Market.kind.in_(props.EARLY_TEAM_KINDS))).scalars()}
        objectives = s.execute(select(Market).where(Market.kind.in_(props.OFFERED_OBJECTIVES))).scalars().all()
        assert {m.template_key for m in objectives} == {f"{k}:fx-1:1:live" for k in ("first_blood", "first_tower",
                                                                                     "baron_before")}
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


def test_through_draft_markets_close_at_three_minutes_and_first_blood_at_the_kill(factory, season_games):
    from conftest import make_market
    from test_money import join

    from rift.placement import PlacementError, QuoteItem, create_quote

    _live_game1(factory, season_games, blood_at=90)
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        made = {}
        for kind in ("game_winner", "first_blood"):
            m = make_market(s, season, fx, kind, [("A", "A", "1.80"), ("B", "B", "2.00")],
                            params={"game_index": 1, "through_draft": True}, scope="GAME")
            m.close_at = T0 + timedelta(hours=1)  # provisional, as created before the game loads
            made[kind] = s.execute(select(Outcome.id).where(Outcome.market_id == m.id, Outcome.code == "A")).scalar_one()
    join(factory, season_games, "alice")

    def quote(kind, at):
        with factory() as s, s.begin():
            create_quote(s, season_id=season_games["season"], user_id=season_games["alice"],
                         items=[QuoteItem(made[kind], 100)], now=at, ttl_seconds=20)

    quote("game_winner", T0 + timedelta(seconds=100))  # after the draft and first blood, before 3:00
    for kind, at in (("first_blood", T0 + timedelta(seconds=100)), ("game_winner", T0 + timedelta(seconds=181))):
        with pytest.raises(PlacementError, match="First blood has happened|closed at 3:00"):
            quote(kind, at)
    with factory() as s, s.begin():
        assert props.tighten_early(s, T0 + timedelta(seconds=100)) == 2
        cutoffs = {m.kind: m.close_at for m in s.execute(select(Market).where(Market.kind.in_(made))).scalars()}
    assert cutoffs == {"game_winner": T0 + timedelta(minutes=3), "first_blood": T0 + timedelta(seconds=90)}


def _state(kills=(0, 0), gap=0, clock=150, gold=None):
    return props.LiveState(T0 + timedelta(seconds=clock), clock, {"A": kills[0], "B": kills[1]}, gap, gold or {})


def test_live_prices_follow_the_kills_and_gold_so_far():
    assert props.race_probability(0.5, 5, 5) == pytest.approx(0.5)
    assert props.five_kills_probability(0.55, _state()) == pytest.approx(0.55, abs=1e-6)
    ahead = props.five_kills_probability(0.5, _state((2, 0)))
    assert ahead > 0.75 and props.five_kills_probability(0.5, _state((0, 2))) == pytest.approx(1 - ahead)
    assert props.five_kills_probability(0.5, _state((5, 1))) is None  # already won
    dist = (26.5, 49.0)
    quiet, bloody = (1 - props.kill_under_probability(26.5, dist, _state(k)) for k in ((0, 0), (3, 1)))
    assert bloody > 1 - props.kill_under_probability(26.5, dist, None) > quiet
    assert props.gold_lead_probability(0.6, 2500, None) == 0.6
    assert props.gold_lead_probability(0.5, 2500, _state(gap=1000)) > 0.6
    assert props.gold_lead_probability(0.5, 2500, _state(gap=-1000)) < 0.4


def _frame(factory, at_s, kills, kill_times=()):
    """Game 1's latest live frame at `at_s` seconds, and the kills recorded so far (side, seconds)."""
    with factory() as s, s.begin():
        g = s.execute(select(Game).where(Game.provider_id == "g1")).scalar_one()
        g.timeline = {**g.timeline, "live": {"at": (T0 + timedelta(seconds=at_s)).isoformat(), "clock_s": at_s,
                                             "kills": {"blue": kills[0], "red": kills[1]},
                                             "gold": {"blue": 2500 + 300 * kills[0], "red": 2500 + 300 * kills[1]}},
                      "kills_at": [{"side": side, "at": (T0 + timedelta(seconds=t)).isoformat()} for side, t in kill_times]}


def test_a_pick_on_a_price_that_had_not_seen_a_kill_is_void(factory, season_games):
    from test_money import join, place

    from rift.settlement import apply_grade

    _live_game1(factory, season_games)
    _frame(factory, 60, (0, 0))
    with factory() as s, s.begin():
        season = s.get(Season, season_games["season"])
        props.open_early_team_markets(s, season, SETTINGS, _Model(), T0 + timedelta(seconds=90))
        race = s.execute(select(Market).where(Market.kind == "five_kills")).scalar_one()
        assert race.params["priced_at"] == (T0 + timedelta(seconds=60)).isoformat()
        a = s.execute(select(Outcome).where(Outcome.market_id == race.id, Outcome.code == "A")).scalar_one()
        race_id, a_id, even = race.id, a.id, a.odds
    join(factory, season_games, "alice")
    join(factory, season_games, "bob")
    # Blue's kill at 1:40 is not in the 1:00 frame yet; Alice picks at 1:30 (before it), Bob at 1:50 (after it).
    place(factory, season_games, "alice", [(a_id, 100)], "before-kill", now=T0 + timedelta(seconds=90))
    place(factory, season_games, "bob", [(a_id, 100)], "stale", now=T0 + timedelta(seconds=110))
    _frame(factory, 120, (1, 0), [("blue", 100)])  # the next frame shows it: the price moves
    with factory() as s, s.begin():
        props.open_early_team_markets(s, s.get(Season, season_games["season"]), SETTINGS, _Model(),
                                      T0 + timedelta(seconds=150))
        moved = s.get(Outcome, a_id)
        assert moved.odds < even and s.get(Market, race_id).params["priced_at"] == (T0 + timedelta(seconds=120)).isoformat()
    with factory() as s, s.begin():
        from rift.models import User
        s.add(User(handle="cai", display_name="Cai"))
        season_games["cai"] = s.execute(select(User.id).where(User.handle == "cai")).scalar_one()
    join(factory, season_games, "cai")
    place(factory, season_games, "cai", [(a_id, 100)], "fresh", now=T0 + timedelta(seconds=160))
    _finish_game1(factory, season_games)
    with factory() as s, s.begin():
        g = s.execute(select(Game).where(Game.provider_id == "g1")).scalar_one()
        g.timeline = {**g.timeline, "kills_at": [{"side": "blue", "at": (T0 + timedelta(seconds=100)).isoformat()}]}
        apply_grade(s, race_id, grade_market(s, s.get(Market, race_id)), T0 + timedelta(hours=1))
    with factory() as s:
        result = {sel.user_id: sel.status for sel in s.execute(select(Selection)).scalars()}
    assert result[season_games["alice"]] == "WON"
    assert result[season_games["bob"]] == "VOID"
    assert result[season_games["cai"]] == "WON"


def test_open_kill_lines_and_duels_reprice_from_each_frame(factory, season_games):
    _live_game1(factory, season_games)
    _frame(factory, 30, (0, 0))
    at = T0 + timedelta(seconds=40)
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        line = props.ensure_kill_line(s, season, fx, 1, "44.5", tournament_stats(s, season), SETTINGS, at)
        duel = props.ensure_duel(s, season, fx, 1, "mid", "gold15", SETTINGS, at)
        over = s.execute(select(Outcome).where(Outcome.market_id == line.id, Outcome.code == "OVER")).scalar_one()
        ids, before = (line.id, duel.id, over.id), over.odds
    _frame(factory, 150, (3, 2), [("blue", 60), ("red", 70), ("blue", 80), ("red", 90), ("blue", 100)])
    with factory() as s, s.begin():
        props.open_early_team_markets(s, s.get(Season, season_games["season"]), SETTINGS, _Model(),
                                      T0 + timedelta(seconds=155))
        stamp = (T0 + timedelta(seconds=150)).isoformat()
        assert s.get(Outcome, ids[2]).odds < before  # five kills already: the over is shorter
        assert s.get(Market, ids[0]).params["priced_at"] == s.get(Market, ids[1]).params["priced_at"] == stamp


def test_blind_duels_and_kill_lines_before_the_draft_then_after_it(factory, season_games):
    """D-031: blind picks before the draft (expected players, no champions), none during it, then the
    after-draft markets with champions from the first frame until 3:00. Separate markets throughout."""
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        stats = tournament_stats(s, season)
        grid = props.duels(s, season, fx, 1, SETTINGS, T0)
        mid = next(d for d in grid["duels"] if d["role"] == "mid")
        assert grid["phase"] == "BLIND" and grid["close_at"] == series_close(fx).isoformat()
        # D-037: running late, the series not live yet: still blind, half an hour after the listed time.
        assert props.duels(s, season, fx, 1, SETTINGS, fx.scheduled_at + timedelta(minutes=30))["phase"] == "BLIND"
        assert mid["odds"]["gold15"]["A"] and "champion" not in mid["a"]
        blind = props.ensure_duel(s, season, fx, 1, "mid", "gold15", SETTINGS, T0)
        assert blind.template_key.endswith(":blind") and blind.params["blind"] and not blind.params.get("early")
        assert blind.close_at == series_close(fx) and "(blind)" in blind.title
        lines = props.kill_lines(s, fx, 1, stats, SETTINGS, T0)
        assert lines["phase"] == "BLIND" and lines["lines"]
        blind_line = props.ensure_kill_line(s, season, fx, 1, lines["lines"][0]["line"], stats, SETTINGS, T0)
        assert blind_line.params["blind"] and blind_line.model_key == "negbin_blind_v1"
        blind_id = blind.id

        fx.status = "LIVE"  # drafting: nothing to pick until the game loads
        s.flush()
        with pytest.raises(props.PropsError, match="draft"):
            props.ensure_duel(s, season, fx, 1, "mid", "gold15", SETTINGS, fx.scheduled_at + timedelta(minutes=2))
        with pytest.raises(props.PropsError, match="draft"):
            props.ensure_kill_line(s, season, fx, 1, lines["lines"][0]["line"], stats, SETTINGS,
                                   fx.scheduled_at + timedelta(minutes=2))
    _live_game1(factory, season_games)
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        after = props.ensure_duel(s, season, fx, 1, "mid", "gold15", SETTINGS, T0 + timedelta(minutes=1))
        assert after.id != blind_id and after.params["early"] and after.params["a_champion"] == "C3"
    _finish_game1(factory, season_games)
    with factory() as s:
        assert grade_market(s, s.get(Market, blind_id)).winning_codes == ["A"]


def test_a_blind_duel_voids_when_a_named_player_does_not_play(factory, season_games):
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        blind_id = props.ensure_duel(s, season, fx, 1, "top", "gold15", SETTINGS, T0).id
    _live_game1(factory, season_games)
    with factory() as s, s.begin():
        g = s.execute(select(Game).where(Game.provider_id == "g1")).scalar_one()
        tl = dict(g.timeline)
        tl["participants"] = {pid: ({**p, "player_id": "a-sub", "name": "A sub"} if p["player_id"] == "a-top" else p)
                              for pid, p in tl["participants"].items()}
        g.timeline = tl
    _finish_game1(factory, season_games)
    with factory() as s:
        grade = grade_market(s, s.get(Market, blind_id))
        assert grade.partial_codes == ["A", "B"] and "did not play" in grade.reason  # D-036: half back


def test_a_tied_duel_pays_half_back_to_both_sides(factory, season_games):
    """D-036: a duel with no winner returns half the stake; picks from before the rule keep a full void."""
    from test_money import join, place

    _live_game1(factory, season_games)
    at = T0 + timedelta(minutes=1)
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        tie = props.ensure_duel(s, season, fx, 1, "bottom", "gold15", SETTINGS, at)  # 100 gold apart: a tie
        assert tie.params["void_refund"] == "0.5"
        a, b = (s.execute(select(Outcome.id).where(Outcome.market_id == tie.id, Outcome.code == c)).scalar_one()
                for c in ("A", "B"))
        tie_id = tie.id
    join(factory, season_games, "alice")
    join(factory, season_games, "bob")
    place(factory, season_games, "alice", [(a, 200)], "tie-a", now=at)
    place(factory, season_games, "bob", [(b, 100)], "tie-b", now=at)
    _finish_game1(factory, season_games)
    from rift.settlement import apply_grade
    with factory() as s, s.begin():
        apply_grade(s, tie_id, grade_market(s, s.get(Market, tie_id)), T0 + timedelta(hours=1))
    with factory() as s:
        got = sorted((sel.stake_rc, sel.status, sel.return_rc) for sel in s.execute(select(Selection)).scalars())
        assert got == [(100, "PARTIAL", 50), (200, "PARTIAL", 100)]


def test_team_races_are_blind_before_the_draft_like_duels_and_kill_lines(factory, season_games):
    """Lanes & kills behave as one: team races also open blind before the draft, as separate markets."""
    with factory() as s:
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        a, b = s.get(Team, fx.team_a_id), s.get(Team, fx.team_b_id)
        stats = tournament_stats(s, season)
        specs = {sp.template_key: sp for sp in game_specs(fx, 1, a, b, 0.6, stats, series_close(fx), "MODEL")}
    blind = {k: sp for k, sp in specs.items() if k.endswith(":blind")}
    assert {sp.kind for sp in blind.values()} == {"five_kills", "gold_lead_15", "first_dragon", "first_blood",
                                                 "first_tower", "baron_before"}
    race = blind["gold_lead_15:fx-1:1:blind"]
    assert race.close_at == series_close(fx) and race.params == {"game_index": 1, "blind": True}
    assert "(blind)" in race.title and "before the draft" in race.rules_text
    # After the draft the early-window races are their own markets (no ":blind"), and both grade the same way.
    _live_game1(factory, season_games)
    with factory() as s:
        fx = s.get(Fixture, season_games["fixture"])
        a, b = s.get(Team, fx.team_a_id), s.get(Team, fx.team_b_id)
        after = props.early_team_specs(fx, 1, a, b, 0.6, props.timeline_data(s, s.get(Season, season_games["season"])),
                                       T0 + timedelta(minutes=3))
    assert {sp.template_key for sp in after} == {"five_kills:fx-1:1", "gold_lead_15:fx-1:1", "first_dragon:fx-1:1"}


def test_after_draft_markets_pay_less_than_blind(factory, season_games):
    """D-040: the same race prices lower once it reopens after the draft (75% of the profit)."""
    from decimal import Decimal

    from rift.domain.pricing import after_draft, price

    assert after_draft(Decimal("2.00")) == Decimal("1.75") and after_draft(Decimal("1.01")) == Decimal("1.01")
    _live_game1(factory, season_games)
    with factory() as s, s.begin():
        season = s.get(Season, season_games["season"])
        props.open_early_team_markets(s, season, SETTINGS, _Model(), T0 + timedelta(minutes=1))
        tower = s.execute(select(Market).where(Market.template_key == "first_tower:fx-1:1:live")).scalar_one()
        for o in s.execute(select(Outcome).where(Outcome.market_id == tower.id)).scalars():
            fair = price(float(o.probability), min_probability=Decimal("0.01"), max_odds=Decimal(100))
            assert o.odds == after_draft(fair) and o.odds < fair


def test_one_bet_per_market_and_cancel_until_three_minutes(factory, season_games):
    """D-040: blind or after the draft, not both. Cancel: all back before the draft, 75% after, nothing after 3:00."""
    from conftest import outcome_id
    from test_money import join, place

    from rift.placement import PlacementError, cancel_selection

    join(factory, season_games, "alice")
    before = T0 - timedelta(hours=1)  # the series starts at T0 + 2h
    with factory() as s, s.begin():
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        a, b = s.get(Team, fx.team_a_id), s.get(Team, fx.team_b_id)
        for spec in game_specs(fx, 1, a, b, 0.6, tournament_stats(s, season), series_close(fx), "MODEL"):
            upsert_market(s, season, fx, spec, SETTINGS, before)
        blind = s.execute(select(Market).where(Market.template_key == "first_tower:fx-1:1:blind")).scalar_one().id
    tower = outcome_id(factory, blind, "A")

    def cancel(at):
        with factory() as s, s.begin():
            pick = s.execute(select(Selection).where(Selection.status == "OPEN")).scalars().one()
            return cancel_selection(s, season_id=season_games["season"], user_id=season_games["alice"],
                                    selection_id=pick.id, now=at).return_rc

    place(factory, season_games, "alice", [(tower, 100)], "b1", now=before)
    assert cancel(before) == 100  # before the draft: all of it
    place(factory, season_games, "alice", [(tower, 100)], "b2", now=before)

    _live_game1(factory, season_games)  # the draft has happened and the game loaded at T0
    at = T0 + timedelta(minutes=1)
    with factory() as s, s.begin():
        props.open_early_team_markets(s, s.get(Season, season_games["season"]), SETTINGS, _Model(), at)
        live = s.execute(select(Market).where(Market.template_key == "first_tower:fx-1:1:live")).scalar_one().id
    live_a = outcome_id(factory, live, "A")
    with pytest.raises(PlacementError) as err:
        place(factory, season_games, "alice", [(live_a, 100)], "l1", now=at)
    assert err.value.code == "CALLED_BLIND"
    assert cancel(at) == 75  # after the draft started: 75%
    place(factory, season_games, "alice", [(live_a, 100)], "l2", now=at)  # replaced at the after-draft price
    assert cancel(at + timedelta(seconds=30)) == 75
    place(factory, season_games, "alice", [(live_a, 100)], "l3", now=at)
    with pytest.raises(PlacementError) as err:
        cancel(T0 + timedelta(minutes=3, seconds=1))
    assert err.value.code == "MARKET_LOCKED"


def test_game_length_line_and_grade(factory, season_games):
    """D-040: over/under the median game time, on a half minute; official (Leaguepedia) time first."""
    with factory() as s, s.begin():
        for i, g in enumerate(s.execute(select(Game).where(Game.provider_id.like("past-%"))).scalars()):
            g.ended_at = g.started_at + timedelta(minutes=28 + i % 6)  # 28-33 minutes
    with factory() as s:
        season, fx = s.get(Season, season_games["season"]), s.get(Fixture, season_games["fixture"])
        a, b = s.get(Team, fx.team_a_id), s.get(Team, fx.team_b_id)
        specs = {sp.template_key: sp for sp in game_specs(fx, 1, a, b, 0.6, tournament_stats(s, season), T0,
                                                          "MODEL")}
    length = specs["game_length:fx-1:1:blind"]
    line = length.params["line_s"]
    assert line % 60 == 30 and 28 * 60 < line < 34 * 60 and length.outcomes[0].label.startswith("Over")
    with factory() as s, s.begin():
        m = Market(season_id=season_games["season"], fixture_id=season_games["fixture"], template_key="gl:x",
                   kind="game_length", scope="GAME", category="OBJECTIVES", title="g", rules_text="",
                   params={"game_index": 1, "line_s": 1830}, model_key="t", confidence="EXPERIMENTAL", close_at=T0)
        g = Game(fixture_id=season_games["fixture"], provider_id="g1", game_index=1, state="completed",
                 started_at=T0, ended_at=T0 + timedelta(minutes=31), timeline_complete=False)
        s.add_all([m, g])
        s.flush()
        assert grade_market(s, m).status == "HOLD"  # no official time, live data not complete
        g.timeline_complete = True
        assert grade_market(s, m).winning_codes == ["OVER"]  # 31:00 by the feed's clock
        g.bans = {"length_s": 1800}  # Leaguepedia: 30:00 once the pause is taken out
        assert grade_market(s, m).winning_codes == ["UNDER"]
