"""End-to-end worker behaviour against a scripted fake feed (no network)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from rift import grants
from rift.adapters.leaguepedia import MockLeaguepedia
from rift.adapters.lolesports import GameRef, GameStats, MatchDetail, PlayerLine, ScheduleMatch, TeamRef, team_key
from rift.config import Settings
from rift.domain.money import winning_return
from rift.models import Fixture, Game, HistoricalResult, Market, Outcome, Season, Selection, Team, User, Wallet
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

    def finish_game(self, idx, winner_side, kills):
        self.games[idx - 1].state = "completed"
        a, b = self.score
        self.score = (a + 1, b) if winner_side == "A" else (a, b + 1)
        champs = ["Aatrox", "Vi", "Ahri", "Jinx", "Nautilus", "Gnar", "Sejuani", "Orianna", "Kalista", "Rell"]
        if idx == 2:
            champs[0] = "Rumble"
        players = [PlayerLine(i + 1, f"p{i}", f"P{i}", "blue" if i < 5 else "red", "top", champs[i], kills[i], 0, 0)
                   for i in range(10)]
        self.stats[f"g{idx}"] = GameStats(f"g{idx}", "16.20", "finished", START, START, "e-a", "e-b", players, {})


def make_worker(factory, feed, clock):
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
