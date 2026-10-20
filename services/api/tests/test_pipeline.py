"""End-to-end worker behaviour against a scripted fake feed (no network)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from test_timeline import ScriptedGame

from rift import grants, markets
from rift.adapters.leaguepedia import MockLeaguepedia
from rift.adapters.lolesports import (
    GameRef,
    GameStats,
    MatchDetail,
    PlayerLine,
    ScheduleMatch,
    TeamRef,
    parse_detail_frames,
    parse_frames,
    team_key,
)
from rift.config import Settings
from rift.domain.money import winning_return
from rift.models import (
    Fixture,
    Game,
    HistoricalResult,
    Market,
    Outcome,
    Season,
    Selection,
    Team,
    User,
    Wallet,
)
from rift.placement import QuoteItem, accept_ticket, create_quote
from rift.worker import Worker

START = datetime(2026, 10, 23, 17, 0, tzinfo=UTC)


def tref(name, code, wins=None):
    return TeamRef(team_key(name), code, name, None, wins, None)


class FakeFeed:
    def __init__(self):
        self.state, self.score = "unstarted", (0, 0)
        self.games: list[GameRef] = [GameRef(f"g{i}", i, "unstarted", "e-a", "e-b") for i in (1, 2, 3)]
        self.stats: dict[str, GameStats] = {}
        self.live_ids: set[str] = set()
        self.scripted: dict[str, ScriptedGame] = {}  # livestats frames, keyed by game id
        self.clock = lambda: START

    def live(self):
        return self.live_ids

    def schedule_since(self, league_id, since, max_pages=12):
        a, b = self.score
        live = self.state != "unstarted"
        return [ScheduleMatch("m1", "worlds", START, self.state, "Swiss", 3,
                              [tref("Atlas", "ATL", a if live else None), tref("Nova", "NOV", b if live else None)])]

    def leagues(self):
        return {}

    def event_details(self, match_id):
        a, b = self.score
        return MatchDetail("m1", [("e-a", "Atlas", a), ("e-b", "Nova", b)], self.games)

    def final_stats(self, game_id, now):
        return self.stats.get(game_id)

    def frames(self, game_id, starting_time=None):
        game = self.scripted.get(game_id)
        payload = game.window(starting_time, self.clock()) if game else None
        return parse_frames(payload) if payload else None

    def detail_frames(self, game_id, starting_time):
        game = self.scripted.get(game_id)
        payload = game.details(starting_time, self.clock()) if game else None
        return parse_detail_frames(payload) if payload else []

    def finish_game(self, idx, winner_side, kills, ended=START):
        self.games[idx - 1].state = "completed"
        a, b = self.score
        self.score = (a + 1, b) if winner_side == "A" else (a, b + 1)
        champs = ["Aatrox", "Vi", "Ahri", "Jinx", "Nautilus", "Gnar", "Sejuani", "Orianna", "Kalista", "Rell"]
        if idx == 2:
            champs[0] = "Rumble"
        players = [PlayerLine(i + 1, f"p{i}", f"P{i}", "blue" if i < 5 else "red", "top", champs[i], kills[i], 0, 0)
                   for i in range(10)]
        self.stats[f"g{idx}"] = GameStats(f"g{idx}", "16.20", "finished", ended - timedelta(minutes=30), ended,
                                          "e-a", "e-b", players, {})


def make_worker(factory, feed, clock):
    feed.clock = clock
    settings = Settings(season_code="worlds-2026", settle_delay_seconds=600, season_first_match_day="2026-10-23")
    return Worker(factory, settings, feed, MockLeaguepedia(), clock=clock)


def test_full_series_lifecycle(factory):
    feed = FakeFeed()
    now = [START - timedelta(hours=6)]
    worker = make_worker(factory, feed, lambda: now[0])
    with factory() as s, s.begin():
        # history so both teams are rated (Atlas stronger)
        a = Team(provider_id=team_key("Atlas"), code="ATL", name="Atlas", region="LCK")
        b = Team(provider_id=team_key("Nova"), code="NOV", name="Nova", region="LCS")
        s.add_all([a, b, User(handle="ana", display_name="Ana")])
        s.flush()
        s.add(HistoricalResult(provider_id="h1", league_slug="msi", played_at=START - timedelta(days=90),
                               team_a_id=a.id, team_b_id=b.id, team_a_wins=3, team_b_wins=1))
    worker.cycle()
    with factory() as s, s.begin():
        season = s.execute(select(Season)).scalar_one()
        user = s.execute(select(User)).scalar_one()
        grants.join_season(s, season, user.id, now[0])
        kinds = sorted(m.kind for m in s.execute(select(Market)).scalars())
        assert kinds == ["game_winner", "series_score", "series_winner", "total_games"]
        winner_mkt = s.execute(select(Market).where(Market.kind == "series_winner")).scalar_one()
        g1_mkt = s.execute(select(Market).where(Market.kind == "game_winner")).scalar_one()
        atlas = s.execute(select(Outcome).where(Outcome.market_id == winner_mkt.id, Outcome.code == "A")).scalar_one()
        nova_g1 = s.execute(select(Outcome).where(Outcome.market_id == g1_mkt.id, Outcome.code == "B")).scalar_one()
        assert atlas.odds < 2  # Atlas favoured
        q = create_quote(s, season_id=season.id, user_id=user.id,
                         items=[QuoteItem(atlas.id, 500), QuoteItem(nova_g1.id, 100)], now=now[0], ttl_seconds=20)
        accept_ticket(s, season_id=season.id, user_id=user.id, quote_id=q["quote_id"],
                      confirm_odds_versions={i["outcome_id"]: i["odds_version"] for i in q["items"]},
                      idempotency_key="t1", now=now[0])
        user_id, atlas_odds, nova_odds = user.id, atlas.odds, nova_g1.odds
    # 06:00 venue time on Oct 23 is already a match day: opening + match-day grant, minus 600 staked.
    assert _balance(factory, user_id) == 2000 - 600

    # Series goes live: markets lock immediately; no second grant for the same day.
    now[0] = START + timedelta(minutes=5)
    feed.state = "inProgress"
    worker.cycle()
    with factory() as s:
        assert {m.state for m in s.execute(select(Market)).scalars()} == {"LOCKED"}
    assert _balance(factory, user_id) == 1400

    # Game 1 to Nova, observed by a poll; then games 2 and 3 to Atlas, observed one poll each.
    for idx, side, minutes in ((1, "B", 40), (2, "A", 80), (3, "A", 120)):
        feed.finish_game(idx, side, [3, 2, 5, 1, 0, 1, 2, 4, 6, 1] if idx != 3 else [9, 1, 1, 1, 1, 1, 1, 1, 1, 1])
        now[0] = START + timedelta(minutes=minutes)
        if idx == 3:
            feed.state = "completed"
        worker.cycle()
    with factory() as s:
        games = {g.game_index: g for g in s.execute(select(Game)).scalars()}
        fx = s.execute(select(Fixture)).scalar_one()
        assert games[1].winner_team_id == fx.team_b_id and games[1].winner_evidence == "series_score"
        assert games[2].winner_team_id == fx.team_a_id and games[3].winner_team_id == fx.team_a_id
        # Settlement waits for the data to be stable.
        assert {m.state for m in s.execute(select(Market)).scalars()} == {"LOCKED"}

    now[0] = START + timedelta(minutes=135)
    worker.cycle()
    with factory() as s:
        states = {m.kind: m.state for m in s.execute(select(Market)).scalars()}
        assert set(states.values()) == {"SETTLED"}
        sels = {sel.stake_rc: sel for sel in s.execute(select(Selection)).scalars()}
        assert sels[500].status == "WON" and sels[100].status == "WON"
        expected = 1400 + winning_return(500, atlas_odds) + winning_return(100, nova_odds)
    assert _balance(factory, user_id) == expected


def _balance(factory, user_id):
    with factory() as s:
        return s.execute(select(Wallet.available_rc).where(Wallet.user_id == user_id)).scalar_one()


def test_early_start_locks_before_the_schedule_catches_up(factory):
    """FUR-C9 (2026-10-16) started 2h07m before its listed time: getLive alone must lock its markets."""
    feed = FakeFeed()
    now = [START - timedelta(hours=6)]
    worker = make_worker(factory, feed, lambda: now[0])
    with factory() as s, s.begin():
        a = Team(provider_id=team_key("Atlas"), code="ATL", name="Atlas", region="LCK")
        b = Team(provider_id=team_key("Nova"), code="NOV", name="Nova", region="LCS")
        s.add_all([a, b])
        s.flush()
        s.add(HistoricalResult(provider_id="h1", league_slug="msi", played_at=START - timedelta(days=90),
                               team_a_id=a.id, team_b_id=b.id, team_a_wins=3, team_b_wins=1))
    worker.cycle()
    with factory() as s:
        assert {m.state for m in s.execute(select(Market)).scalars()} == {"OPEN"}

    now[0] = START - timedelta(hours=2)  # the schedule still says unstarted
    feed.live_ids = {"m1"}
    worker.cycle()
    worker.cycle()  # a second pass must not re-open the series from the stale schedule
    with factory() as s:
        assert s.execute(select(Fixture.status)).scalar_one() == "LIVE"
        assert {m.state for m in s.execute(select(Market)).scalars()} == {"LOCKED"}
    assert worker.poll_interval() == 15


def _seed_rated_teams(factory):
    with factory() as s, s.begin():
        a = Team(provider_id=team_key("Atlas"), code="ATL", name="Atlas", region="LCK")
        b = Team(provider_id=team_key("Nova"), code="NOV", name="Nova", region="LCS")
        s.add_all([a, b])
        s.flush()
        s.add(HistoricalResult(provider_id="h1", league_slug="msi", played_at=START - timedelta(days=90),
                               team_a_id=a.id, team_b_id=b.id, team_a_wins=3, team_b_wins=1))


def _markets(factory):
    with factory() as s:
        return {m.template_key: m for m in s.execute(select(Market)).scalars()}


def _go_live(feed, worker, now):
    """Series open, then live with Game 1 under way: everything open so far locks."""
    worker.cycle()
    assert {m.state for m in _markets(worker.factory).values()} == {"OPEN"}
    now[0] = START + timedelta(minutes=2)
    feed.state, feed.games[0].state = "inProgress", "inProgress"
    worker.cycle()
    assert {m.state for m in _markets(worker.factory).values()} == {"LOCKED"}


KILLS = [3, 2, 5, 1, 0, 1, 2, 4, 6, 1]


def test_game_two_opens_when_game_one_ends_and_locks_when_it_loads(factory):
    feed = FakeFeed()
    now = [START - timedelta(hours=6)]
    worker = make_worker(factory, feed, lambda: now[0])
    _seed_rated_teams(factory)
    _go_live(feed, worker, now)

    # Game 1 ends at +35m and is observed a minute later: Game 2 opens, closing 7 minutes after the end.
    feed.finish_game(1, "B", KILLS, ended=START + timedelta(minutes=35))
    now[0] = START + timedelta(minutes=36)
    worker.cycle()
    ms = _markets(factory)
    g2 = ms["game_winner:m1:2"]
    assert g2.state == "OPEN" and g2.params == {"game_index": 2} and g2.scope == "GAME"
    assert g2.close_at == START + timedelta(minutes=42)
    # Series markets and Game 1 stay locked while the series is live; Game 3 is not offered yet.
    assert all(m.state == "LOCKED" for k, m in ms.items() if k != "game_winner:m1:2")
    assert "game_winner:m1:3" not in ms
    with factory() as s:
        g1 = s.execute(select(Game).where(Game.game_index == 1)).scalar_one()
        assert g1.ended_at == START + timedelta(minutes=35)

    # Game 2 loads (first livestats frame) at +40m, before the cutoff and before the schedule says so.
    feed.scripted["g2"] = ScriptedGame("g2", START + timedelta(minutes=40), 1800)
    now[0] = START + timedelta(minutes=40, seconds=20)
    worker.cycle()
    g2 = _markets(factory)["game_winner:m1:2"]
    assert g2.state == "LOCKED" and g2.state_reason == "Locked at Game 2 start"
    with factory() as s:
        game2 = s.execute(select(Game).where(Game.game_index == 2)).scalar_one()
        assert game2.started_at == START + timedelta(minutes=40) and game2.state == "unstarted"
        assert game2.timeline["participants"]["1"]["champion"] == "Jayce"
    # A live poll fills the scoreboard summary the /live endpoint serves.
    now[0] = START + timedelta(minutes=50)
    feed.games[1].state = "inProgress"
    worker.cycle()
    with factory() as s:
        live = s.execute(select(Game).where(Game.game_index == 2)).scalar_one().timeline["live"]
        assert live["state"] == "in_game" and 500 < live["clock_s"] < 600 and live["kills"]["blue"] == 1


def test_two_nil_never_opens_game_three_and_voids_a_stray_one(factory):
    feed = FakeFeed()
    now = [START - timedelta(hours=6)]
    worker = make_worker(factory, feed, lambda: now[0])
    _seed_rated_teams(factory)
    _go_live(feed, worker, now)

    feed.finish_game(1, "A", KILLS, ended=START + timedelta(minutes=35))
    now[0] = START + timedelta(minutes=36)
    worker.cycle()
    assert _markets(factory)["game_winner:m1:2"].state == "OPEN"
    # Nobody saw Game 2 load in time: the market locks at its own cutoff.
    now[0] = START + timedelta(minutes=43)
    worker.cycle()
    g2 = _markets(factory)["game_winner:m1:2"]
    assert g2.state == "LOCKED" and g2.state_reason == "Locked before Game 2 draft"

    # A Game 3 market left open by a lagging feed must not outlive the series.
    with factory() as s, s.begin():
        season, fixture = s.execute(select(Season)).scalar_one(), s.execute(select(Fixture)).scalar_one()
        stray = Market(season_id=season.id, fixture_id=fixture.id, template_key="game_winner:m1:3",
                       kind="game_winner", scope="GAME", category="WINNER", title="Game 3 winner", rules_text="t",
                       params={"game_index": 3}, model_key="elo_v1", confidence="MODEL",
                       close_at=START + timedelta(hours=3))
        s.add(stray)
        s.flush()
        s.add_all([Outcome(market_id=stray.id, code=c, label=c, sort=i, odds_version=1, odds=2)
                   for i, c in enumerate("AB")])

    feed.finish_game(2, "A", KILLS, ended=START + timedelta(minutes=75))
    feed.state, feed.games[2].state = "completed", "unneeded"
    now[0] = START + timedelta(minutes=76)
    worker.cycle()
    ms = _markets(factory)
    assert ms["game_winner:m1:3"].state == "LOCKED" and ms["game_winner:m1:3"].state_reason == "Series over"
    assert sum(1 for m in ms.values() if m.kind == "game_winner") == 3  # Games 1, 2 and the stray only

    now[0] = START + timedelta(minutes=90)
    worker.cycle()
    ms = _markets(factory)
    assert ms["game_winner:m1:3"].state == "VOID"
    assert ms["game_winner:m1:2"].state == "SETTLED" and ms["series_score:m1"].state == "SETTLED"


def test_next_game_opens_from_a_final_frame_only_when_reachable_whoever_won():
    end = START + timedelta(minutes=35)

    def g(idx, state, ended=None):
        return Game(game_index=idx, state=state, ended_at=ended, started_at=None)

    bo3 = Fixture(best_of=3, status="LIVE", team_a_wins=0, team_b_wins=0)
    # Game 1's last frame says finished before the schedule or the score catch up: Game 2 happens either way.
    assert markets.next_game(bo3, [g(1, "inProgress", end), g(2, "unstarted"), g(3, "unstarted")]) == (
        2, end + timedelta(minutes=7))
    assert markets.next_game(bo3, [g(1, "inProgress"), g(2, "unstarted")]) is None  # end time unknown
    # 1-0 and Game 2 just ended unscored: it may be 2-0, so Game 3 waits for the score.
    bo3.team_a_wins = 1
    games = [g(1, "completed", START), g(2, "inProgress", end), g(3, "unstarted")]
    assert markets.next_game(bo3, games) is None
    bo3.team_b_wins = 1
    games[1].state = "completed"
    assert markets.next_game(bo3, games) == (3, end + timedelta(minutes=7))
    games[2].started_at = end + timedelta(minutes=6)  # already loaded: too late to open
    assert markets.next_game(bo3, games) is None


def test_game_kill_lines_stay_pinned_once_offered():
    fixture = Fixture(provider_id="m1", best_of=3)
    a, b = Team(name="Atlas"), Team(name="Nova")
    stats = markets.TournamentStats(games=15, pick_rate={}, kill_totals=[20] * 10 + [30] * 5)
    close = START + timedelta(minutes=42)
    fresh = {s.kind: s for s in markets.game_specs(fixture, 2, a, b, 0.6, stats, close, "MODEL")}
    assert fresh["total_kills_game"].template_key == "total_kills_game:m1:2:23.5"
    assert fresh["total_kills_game"].params == {"game_index": 2, "line": "23.5"}
    assert fresh["game_winner"].close_at == close and "Opens when Game 1 ends" in fresh["game_winner"].rules_text
    # The tournament mean moved after Game 1; the Game 2 market already offered keeps its line.
    stats.kill_totals.append(40)
    pinned = {s.kind: s for s in markets.game_specs(fixture, 2, a, b, 0.6, stats, close, "MODEL", "23.5")}
    assert pinned["total_kills_game"].template_key == "total_kills_game:m1:2:23.5"
    assert pinned["total_kills_game"].outcomes[0].probability != fresh["total_kills_game"].outcomes[0].probability
