"""Scheduled worker (docs/spec/07_ARCHITECTURE.md). Every job is idempotent; safe to run with replicas > 1."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from rift import grants, ingest, markets, props, ratings, settlement, swiss_card, timeline
from rift.adapters.leaguepedia import LeaguepediaSource, make_source
from rift.adapters.lolesports import LolesportsClient
from rift.config import Settings, get_settings
from rift.db import session_factory, transaction
from rift.models import Fixture, Game, Market, ProviderSync, Season, Team
from rift.settlement import Grade
from rift.simulate import simulate

log = logging.getLogger("rift.worker")


class Worker:
    def __init__(self, factory: sessionmaker[Session], settings: Settings, client: LolesportsClient,
                 secondary: LeaguepediaSource, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.factory, self.settings, self.client, self.secondary, self.clock = (
            factory, settings, client, secondary, clock)

    # ------------------------------------------------------------ bookkeeping

    def _due(self, job: str, every: timedelta) -> bool:
        with self.factory() as s:
            row = s.get(ProviderSync, job)
            return row is None or row.last_ok_at is None or self.clock() - row.last_ok_at >= every

    def _run(self, job: str, fn: Callable[[Session, datetime], object]) -> object:
        now = self.clock()
        try:
            with transaction(self.factory) as s:
                result = fn(s, now)
                row = s.get(ProviderSync, job) or ProviderSync(job=job)
                row.last_ok_at = now
                s.add(row)
            return result
        except Exception as exc:  # recorded for the admin health view, then the cycle continues
            log.exception("job %s failed", job)
            with transaction(self.factory) as s:
                row = s.get(ProviderSync, job) or ProviderSync(job=job)
                row.last_error_at, row.last_error = now, f"{type(exc).__name__}: {exc}"[:2000]
                s.add(row)
            return None

    # ------------------------------------------------------------ cycle

    def cycle(self) -> None:
        self._run("season", lambda s, now: ingest.ensure_season(s, self.settings))
        if self._due("history", timedelta(hours=12)):
            self._run("history", lambda s, now: ingest.sync_history(s, self.client, datetime(2026, 1, 1, tzinfo=UTC)))
        if self._due("schedule", self._schedule_interval()):
            self._run("schedule", self._sync_schedule)
        self._run("live", lambda s, now: ingest.mark_live(s, self.client.live(), now))
        self._run("details", self._sync_details)
        self._run("timeline", self._track_games)
        if not self.busy(timedelta(minutes=20)) and self._due("backfill", timedelta(minutes=2)):
            self._run("backfill", self._backfill_timelines)
        if self.secondary.available and self._due("drafts", timedelta(minutes=10)):
            self._run("drafts", self._sync_drafts)
        self._run("markets", self._price_markets)
        if self._due("futures", timedelta(minutes=10)):
            self._run("futures", self._price_futures)
        if self._due("lineups", timedelta(minutes=10)):
            self._run("lineups", lambda s, now: ingest.sync_lineups(s, self._season(s), self.client, now))
        self._run("early_teams", lambda s, now: props.open_early_team_markets(
            s, self._season(s), self.settings, self._model(s)[0], now))
        self._run("early", lambda s, now: props.tighten_early(s, now))
        self._run("lock", lambda s, now: markets.lock_due(s, now))
        self._run("card", lambda s, now: swiss_card.convert_staked(s, self._season(s), now))
        self._run("settle", self._settle)
        self._run("grants", self._grants)

    def _season(self, s: Session) -> Season:
        return s.execute(select(Season).where(Season.code == self.settings.season_code)).scalar_one()

    def busy(self, within: timedelta = timedelta(hours=2)) -> bool:
        """A series is live or just finished, or one is scheduled within `within` and not yet completed. A just
        finished series keeps the fast schedule sync through its settle delay, so a corrected score reopens it
        before anything pays."""
        now = self.clock()
        with self.factory() as s:
            return bool(s.execute(select(func.count()).select_from(Fixture).where(
                (Fixture.status == "LIVE") | (Fixture.completed_at >= now - timedelta(minutes=30))
                | ((Fixture.scheduled_at <= now + within)
                   & (Fixture.scheduled_at >= now - timedelta(hours=8)) & (Fixture.status != "COMPLETED"))
            )).scalar())

    def _schedule_interval(self) -> timedelta:
        return timedelta(minutes=1) if self.busy() else timedelta(minutes=10)

    def early_window_open(self) -> bool:
        """A game loaded within the last few minutes and still running: its early-game window may be open."""
        now = self.clock()
        with self.factory() as s:
            return bool(s.execute(select(func.count()).select_from(Game).where(
                Game.started_at >= now - props.EARLY_WINDOW - timedelta(seconds=30), Game.ended_at.is_(None)
            )).scalar())

    def poll_interval(self) -> float:
        """5 s during a game's first minutes (early-game picks close at 3:00), 15 s around live series,
        60 s otherwise."""
        if self.early_window_open():
            return self.settings.early_poll_seconds
        return self.settings.live_poll_seconds if self.busy(timedelta(minutes=30)) else self.settings.idle_poll_seconds

    def _sync_schedule(self, s: Session, now: datetime) -> int:
        return len(ingest.sync_schedule(s, self._season(s), self.client, now))

    def _sync_details(self, s: Session, now: datetime) -> int:
        n = 0
        for f in s.execute(select(Fixture).where(Fixture.status.in_(("LIVE", "COMPLETED")))).scalars().all():
            if ingest.needs_details(f, now, ingest.games_complete(s, f)):
                ingest.sync_fixture_details(s, f, self.client, self.secondary, now)
                n += 1
        return n

    def _sync_drafts(self, s: Session, now: datetime) -> int:
        """Leaguepedia bans and pick order, on a slow cadence: editors fill games in minutes to hours after
        they end, and its API is rate-limited. Stops at the HOLD -> VOID deadline, when waiting is moot."""
        since = now - timedelta(hours=self.settings.hold_void_after_hours)
        fixtures = s.execute(select(Fixture).where(Fixture.status.in_(("LIVE", "COMPLETED")),
                                                   Fixture.scheduled_at >= since)).scalars().all()
        return sum(ingest.sync_drafts(s, f, self.secondary, now) for f in fixtures)

    def _track_games(self, s: Session, now: datetime) -> int:
        n = 0
        recent = (Fixture.status == "COMPLETED") & (
            Fixture.completed_at.is_(None) | (Fixture.completed_at >= now - timedelta(hours=6)))
        for f in s.execute(select(Fixture).where((Fixture.status == "LIVE") | recent)).scalars().all():
            games = list(s.execute(select(Game).where(Game.fixture_id == f.id)).scalars())
            for g in ingest.games_to_track(f, games, now):
                n += timeline.track(g, self.client, now)
        return n

    def _backfill_timelines(self, s: Session, now: datetime) -> int:
        """Finished games the live tracker never saw (e.g. played before this deployment): two per pass, in
        random order so one game the feed can't serve never starves the rest. Their timelines price the
        objective and early-window markets."""
        season = self._season(s)
        rows = s.execute(select(Game).join(Fixture, Fixture.id == Game.fixture_id).where(
            Fixture.season_id == season.id, Fixture.status == "COMPLETED", Game.state == "completed",
            Game.timeline_complete.is_(False)).order_by(func.random()).limit(2)).scalars().all()
        return sum(int(timeline.track(g, self.client, now)) for g in rows)

    def _model(self, s: Session) -> tuple[ratings.EloModel, str]:
        model = ratings.fit(s)
        bt = ratings.backtest(s)
        ratings.persist(s, model)
        return model, ("MODEL" if bt.beats_baseline else "EXPERIMENTAL")

    def _price_markets(self, s: Session, now: datetime) -> int:
        season = self._season(s)
        for kind in (*props.RETIRED_OBJECTIVES, "total_games"):  # D-023/D-024: placed picks still settle
            markets.retire_kind(s, kind, "No longer offered")
        model, confidence = self._model(s)
        stats = markets.tournament_stats(s, season)
        count = 0
        fixtures = s.execute(select(Fixture).where(
            Fixture.season_id == season.id, Fixture.status == "SCHEDULED",
            Fixture.scheduled_at > now - markets.SERIES_LOCK_BACKSTOP,  # D-037: keep pricing while running late
            Fixture.team_a_id.is_not(None), Fixture.team_b_id.is_not(None))).scalars().all()
        markets.retire_kind(s, "champion_picked", "Replaced by the champion grid", template_prefix="champion_picked:")
        # D-040: no champion markets, and objectives no longer stay open through the draft. Picks still settle.
        for kind in ("champion_picked", "champion_banned", "champion_first_pick"):
            markets.retire_kind(s, kind, "Champion picks are no longer offered")
        props.retire_through_draft(s)
        markets.retire_kind(s, "total_kills_game", "Kill lines now open when the game loads",
                            model_key="negbin_tournament_v1")
        for f in fixtures:
            a, b = s.get(Team, f.team_a_id), s.get(Team, f.team_b_id)
            for spec in markets.fixture_specs(f, a, b, model, stats, confidence):
                if markets.upsert_market(s, season, f, spec, self.settings, now):
                    count += 1
        # Between games of a live series: open (and keep pricing) the next game's markets.
        live = s.execute(select(Fixture).where(
            Fixture.season_id == season.id, Fixture.status == "LIVE", Fixture.best_of > 1,
            Fixture.team_a_id.is_not(None), Fixture.team_b_id.is_not(None))).scalars().all()
        for f in live:
            games = list(s.execute(select(Game).where(Game.fixture_id == f.id)).scalars())
            nxt = markets.next_game(f, games)
            if nxt is None:
                continue
            idx, close_at = nxt
            a, b = s.get(Team, f.team_a_id), s.get(Team, f.team_b_id)
            q = model.game_probability(a.id, b.id)
            for spec in markets.game_specs(f, idx, a, b, q, stats, close_at, confidence):
                if markets.upsert_market(s, season, f, spec, self.settings, now):
                    count += 1
        return count

    def _price_futures(self, s: Session, now: datetime) -> int:
        season = self._season(s)
        model, _ = self._model(s)
        fixtures = list(s.execute(select(Fixture).where(Fixture.season_id == season.id)).scalars())
        sim = simulate(fixtures, model)
        if sim is None:
            return 0
        teams = {t.id: t for t in s.execute(select(Team).where(Team.id.in_(sim.champion.keys()))).scalars()}
        offer = self.settings.offer_tournament_winner
        specs = markets.futures_specs(season, fixtures, teams, sim, tournament_winner=offer)
        markets.retire_kind(s, "swiss_advance", "Replaced by the Swiss Board")
        if offer:  # resume a paused champion market; picks placed before the pause still stand
            for m in s.execute(select(Market).where(Market.kind == "tournament_winner", Market.state == "SUSPENDED",
                                                    Market.state_reason == markets.TOURNAMENT_WINNER_PAUSED)):
                m.state, m.state_reason = "OPEN", None
        else:
            markets.retire_kind(s, "tournament_winner", markets.TOURNAMENT_WINNER_PAUSED)
        return sum(1 for spec in specs if markets.upsert_market(s, season, None, spec, self.settings, now))

    def _settle(self, s: Session, now: datetime) -> int:
        delay = timedelta(seconds=self.settings.settle_delay_seconds)
        deadline = timedelta(hours=self.settings.hold_void_after_hours)
        changed = 0
        candidates = s.execute(select(Market).where(
            Market.state.in_(("LOCKED", "HOLD", "SETTLED", "VOID")),
            Market.close_at >= now - timedelta(days=21))).scalars().all()
        for market in candidates:
            if market.fixture_id is not None:
                fixture = s.get(Fixture, market.fixture_id)
                last_change = s.execute(select(func.max(Game.data_changed_at)).where(
                    Game.fixture_id == fixture.id)).scalar()
                stamps = [t for t in (fixture.data_changed_at, last_change) if t]
                if stamps and now - max(stamps) < delay:
                    continue  # data still moving
                grade = settlement.grade_market(s, market)
                if grade.status in ("HOLD", "PENDING") and market.state in ("LOCKED", "HOLD") \
                        and now - fixture.scheduled_at > deadline:
                    grade = Grade("VOID", reason=f"Unresolved after {self.settings.hold_void_after_hours}h: "
                                  f"{grade.reason}")
            else:
                grade = settlement.grade_market(s, market)
            if settlement.apply_grade(s, market.id, grade, now):
                changed += 1
        return changed

    def _grants(self, s: Session, now: datetime) -> int:
        return grants.run_match_day_grants(s, self._season(s), now)


def run_forever(idle_seconds: int | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    if idle_seconds:
        settings = settings.model_copy(update={"idle_poll_seconds": idle_seconds})
    worker = Worker(session_factory(), settings, LolesportsClient(settings), make_source(settings))
    while True:
        started = time.monotonic()
        worker.cycle()
        time.sleep(max(5.0, worker.poll_interval() - (time.monotonic() - started)))
