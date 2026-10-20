"""Scheduled worker (docs/spec/07_ARCHITECTURE.md). Every job is idempotent; safe to run with replicas > 1."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from rift import grants, ingest, markets, ratings, settlement, timeline
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
        self._run("markets", self._price_markets)
        if self._due("futures", timedelta(minutes=10)):
            self._run("futures", self._price_futures)
        if self._due("lineups", timedelta(minutes=10)):
            self._run("lineups", lambda s, now: ingest.sync_lineups(s, self._season(s), self.client, now))
        self._run("lock", lambda s, now: markets.lock_due(s, now))
        self._run("settle", self._settle)
        self._run("grants", self._grants)

    def _season(self, s: Session) -> Season:
        return s.execute(select(Season).where(Season.code == self.settings.season_code)).scalar_one()

    def busy(self, within: timedelta = timedelta(hours=2)) -> bool:
        """A series is live, or one is scheduled within `within` and not yet completed."""
        now = self.clock()
        with self.factory() as s:
            return bool(s.execute(select(func.count()).select_from(Fixture).where(
                (Fixture.status == "LIVE")
                | ((Fixture.scheduled_at <= now + within)
                   & (Fixture.scheduled_at >= now - timedelta(hours=8)) & (Fixture.status != "COMPLETED"))
            )).scalar())

    def _schedule_interval(self) -> timedelta:
        return timedelta(minutes=1) if self.busy() else timedelta(minutes=10)

    def poll_interval(self) -> float:
        """15 s around live series so locks and between-game markets react quickly; 60 s otherwise."""
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

    def _track_games(self, s: Session, now: datetime) -> int:
        n = 0
        recent = (Fixture.status == "COMPLETED") & (
            Fixture.completed_at.is_(None) | (Fixture.completed_at >= now - timedelta(hours=6)))
        for f in s.execute(select(Fixture).where((Fixture.status == "LIVE") | recent)).scalars().all():
            games = list(s.execute(select(Game).where(Game.fixture_id == f.id)).scalars())
            for g in ingest.games_to_track(f, games, now):
                n += timeline.track(g, self.client, now)
        return n

    def _model(self, s: Session) -> tuple[ratings.EloModel, str]:
        model = ratings.fit(s)
        bt = ratings.backtest(s)
        ratings.persist(s, model)
        return model, ("MODEL" if bt.beats_baseline else "EXPERIMENTAL")

    def _price_markets(self, s: Session, now: datetime) -> int:
        season = self._season(s)
        model, confidence = self._model(s)
        stats = markets.tournament_stats(s, season)
        count = 0
        fixtures = s.execute(select(Fixture).where(
            Fixture.season_id == season.id, Fixture.status == "SCHEDULED", Fixture.scheduled_at > now,
            Fixture.team_a_id.is_not(None), Fixture.team_b_id.is_not(None))).scalars().all()
        markets.retire_kind(s, "champion_picked", "Replaced by the champion grid", template_prefix="champion_picked:")
        for f in fixtures:
            a, b = s.get(Team, f.team_a_id), s.get(Team, f.team_b_id)
            for spec in markets.fixture_specs(f, a, b, model, stats, confidence, markets.pinned_lines(s, f)):
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
            for spec in markets.game_specs(f, idx, a, b, q, stats, close_at, confidence,
                                           markets.pinned_lines(s, f).get(idx)):
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
        specs = markets.futures_specs(season, fixtures, teams, sim)
        markets.retire_kind(s, "swiss_advance", "Replaced by the Swiss Board")
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
