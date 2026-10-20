"""Canonical fixture/game ingestion from provider adapters (docs/spec/10_DATA_PIPELINES.md)."""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from rift.adapters.leaguepedia import LeaguepediaSource
from rift.adapters.lolesports import LolesportsClient, ScheduleMatch, TeamRef, team_key
from rift.config import Settings
from rift.models import Fixture, Game, HistoricalResult, OutboxEvent, Season, Team

log = logging.getLogger(__name__)

STATUS = {"unstarted": "SCHEDULED", "inProgress": "LIVE", "completed": "COMPLETED"}
RATING_LEAGUES = ["worlds", "msi", "first_stand", "ewc_lol", "lck", "lpl", "lec", "lcs", "cblol-brazil", "lcp",
                  "americas_cup"]
REGION_OF_LEAGUE = {"lck": "LCK", "lpl": "LPL", "lec": "LEC", "lcs": "LCS", "cblol-brazil": "CBLOL", "lcp": "LCP"}


def ensure_season(session: Session, settings: Settings) -> Season:
    season = session.execute(select(Season).where(Season.code == settings.season_code)).scalar_one_or_none()
    if season is None:
        season = Season(code=settings.season_code, name=settings.season_name, timezone=settings.season_timezone,
                        provider_league_id=settings.lolesports_worlds_league_id,
                        first_match_day=datetime.fromisoformat(settings.season_first_match_day).date(),
                        opening_grant_rc=settings.opening_grant_rc, match_day_grant_rc=settings.match_day_grant_rc)
        session.add(season)
        session.flush()
    return season


def upsert_team(session: Session, ref: TeamRef, region: str | None = None) -> Team:
    team = session.execute(select(Team).where(Team.provider_id == ref.key)).scalar_one_or_none()
    if team is None:
        team = Team(provider_id=ref.key, code=ref.code, name=ref.name, image_url=ref.image, region=region)
        session.add(team)
        session.flush()
    else:
        team.code, team.name = ref.code, ref.name
        team.image_url = ref.image or team.image_url
        if region and not team.region:
            team.region = region
    return team


def _apply_match(session: Session, season: Season, m: ScheduleMatch, now: datetime) -> Fixture:
    tz = ZoneInfo(season.timezone)
    teams = [upsert_team(session, t) if t else None for t in (m.teams + [None, None])[:2]]
    fixture = session.execute(select(Fixture).where(Fixture.provider_id == m.match_id)).scalar_one_or_none()
    if fixture is None:
        fixture = Fixture(season_id=season.id, provider_id=m.match_id, stage=m.block_name, best_of=m.best_of,
                          scheduled_at=m.start_time, local_date=m.start_time.astimezone(tz).date(),
                          status="SCHEDULED", team_a_wins=0, team_b_wins=0)
        session.add(fixture)
    a_wins = (m.teams[0].game_wins if m.teams and m.teams[0] else None) or 0
    b_wins = (m.teams[1].game_wins if len(m.teams) > 1 and m.teams[1] else None) or 0
    status = STATUS.get(m.state, "SCHEDULED")
    if fixture.status == "LIVE" and status == "SCHEDULED":
        status = "LIVE"  # getLive saw it start before the schedule caught up; never re-open a live series
    before =(fixture.status, fixture.team_a_wins, fixture.team_b_wins, fixture.team_a_id, fixture.team_b_id,
              fixture.scheduled_at)
    fixture.stage, fixture.best_of = m.block_name, m.best_of
    fixture.team_a_id = teams[0].id if teams[0] else None
    fixture.team_b_id = teams[1].id if teams[1] else None
    fixture.scheduled_at = m.start_time
    fixture.local_date = m.start_time.astimezone(tz).date()
    fixture.status, fixture.team_a_wins, fixture.team_b_wins = status, a_wins, b_wins
    if status == "COMPLETED":
        need = m.best_of // 2 + 1
        winner = 0 if a_wins == need else 1 if b_wins == need else None
        fixture.winner_team_id = teams[winner].id if winner is not None and teams[winner] else None
        fixture.completed_at = fixture.completed_at or now
    after = (fixture.status, fixture.team_a_wins, fixture.team_b_wins, fixture.team_a_id, fixture.team_b_id,
             fixture.scheduled_at)
    if after != before:
        fixture.data_changed_at = now
        fixture.updated_at = now
        session.add(OutboxEvent(type="event.updated", entity_id=m.match_id, payload={"status": status}))
    session.flush()
    return fixture


def sync_schedule(session: Session, season: Season, client: LolesportsClient, now: datetime) -> list[Fixture]:
    since = datetime.combine(season.first_match_day, datetime.min.time(), UTC) - timedelta(days=30)
    matches = client.schedule_since(season.provider_league_id, since)
    return [_apply_match(session, season, m, now) for m in matches]


def mark_live(session: Session, live_ids: set[str], now: datetime) -> int:
    """Flip scheduled fixtures to LIVE the moment the feed shows them in progress.

    Scheduled times can be hours off (FUR-C9 on 2026-10-16 started 2h07m before its listed time), so
    locking must not wait for the next schedule sync.
    """
    if not live_ids:
        return 0
    rows = session.execute(select(Fixture).where(Fixture.provider_id.in_(live_ids),
                                                 Fixture.status == "SCHEDULED")).scalars().all()
    for f in rows:
        f.status, f.data_changed_at, f.updated_at = "LIVE", now, now
        session.add(OutboxEvent(type="event.updated", entity_id=f.provider_id, payload={"status": "LIVE"}))
    session.flush()
    return len(rows)


def needs_details(f: Fixture, now: datetime, games_done: bool) -> bool:
    if f.team_a_id is None or f.team_b_id is None:
        return False
    if f.status == "LIVE":
        return True
    if f.status == "COMPLETED" and not games_done:
        # Keep polling briefly for late stats; after that the market HOLD → VOID path takes over.
        if f.completed_at and now - f.completed_at > timedelta(hours=6):
            return False
        return f.details_synced_at is None or now - f.details_synced_at > timedelta(minutes=2)
    return False


def games_complete(session: Session, f: Fixture) -> bool:
    games = list(session.execute(select(Game).where(Game.fixture_id == f.id)).scalars())
    if not games:
        return False
    return all(g.state == "unneeded" or (g.state == "completed" and g.stats_complete and g.winner_team_id)
               for g in games)


def sync_fixture_details(session: Session, fixture: Fixture, client: LolesportsClient,
                         secondary: LeaguepediaSource, now: datetime) -> None:
    detail = client.event_details(fixture.provider_id)
    by_esports: dict[str, Team] = {}
    for esports_id, name, _wins in detail.teams:
        team = session.execute(select(Team).where(Team.provider_id == team_key(name))).scalar_one_or_none()
        if team is not None:
            if team.esports_id != esports_id:
                clash = session.execute(select(Team).where(Team.esports_id == esports_id)).scalar_one_or_none()
                if clash is None:
                    team.esports_id = esports_id
            by_esports[esports_id] = team

    games = {g.game_index: g for g in session.execute(select(Game).where(Game.fixture_id == fixture.id)).scalars()}
    for ref in detail.games:
        game = games.get(ref.number)
        if game is None:
            game = Game(fixture_id=fixture.id, provider_id=ref.game_id, game_index=ref.number, state=ref.state,
                        stats_complete=False)
            session.add(game)
            games[ref.number] = game
        blue = by_esports.get(ref.blue_team_esports_id or "")
        red = by_esports.get(ref.red_team_esports_id or "")
        if game.state != ref.state:
            game.state, game.data_changed_at = ref.state, now
        game.blue_team_id = blue.id if blue else game.blue_team_id
        game.red_team_id = red.id if red else game.red_team_id
    session.flush()

    for game in games.values():
        if game.state == "completed" and not game.stats_complete:
            stats = client.final_stats(game.provider_id, now)
            if stats and stats.state == "finished" and len(stats.players) == 10:
                side_team = {"blue": game.blue_team_id, "red": game.red_team_id}
                game.patch = stats.patch
                game.stats = {
                    "players": [{"player_id": p.esports_player_id or p.name, "name": p.name, "side": p.side,
                                 "team_id": str(side_team[p.side]) if side_team[p.side] else None,
                                 "role": p.role, "champion": p.champion, "kills": p.kills, "deaths": p.deaths,
                                 "assists": p.assists} for p in stats.players],
                    "teams": stats.team_totals,
                    "final_frame_at": stats.last_frame_at.isoformat() if stats.last_frame_at else None,
                }
                game.stats_complete = True
                game.data_changed_at = now
    infer_game_winners(session, fixture, list(games.values()), secondary, now)
    fixture.details_synced_at = now
    session.flush()


def infer_game_winners(session: Session, fixture: Fixture, games: list[Game], secondary: LeaguepediaSource,
                       now: datetime) -> None:
    """Assign game winners only when the series score forces the answer.

    The worker polls every minute during live series, so at most one newly completed game is unresolved
    at a time and the series score delta identifies its winner exactly. If several games finished between
    polls with mixed results we ask the secondary source, and otherwise leave the winner unknown (HOLD).
    """
    completed = [g for g in games if g.state == "completed"]
    a, b = fixture.team_a_wins, fixture.team_b_wins
    if a + b != len(completed):
        return  # score and game states are momentarily out of step; try again next poll
    unknown = [g for g in completed if g.winner_team_id is None]
    if not unknown:
        return
    known_a = sum(1 for g in completed if g.winner_team_id == fixture.team_a_id)
    known_b = sum(1 for g in completed if g.winner_team_id == fixture.team_b_id)
    rem_a, rem_b = a - known_a, b - known_b
    if rem_a < 0 or rem_b < 0:
        log.warning("fixture %s: known game winners exceed series score", fixture.provider_id)
        return
    if rem_a == 0 or rem_b == 0:
        winner = fixture.team_a_id if rem_b == 0 else fixture.team_b_id
        for g in unknown:
            g.winner_team_id, g.winner_evidence, g.data_changed_at = winner, "series_score", now
        return
    team_a, team_b = session.get(Team, fixture.team_a_id), session.get(Team, fixture.team_b_id)
    if not secondary.available:
        return
    try:
        rows = secondary.series_games(team_a.name, team_b.name, fixture.scheduled_at)
    except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as exc:
        # The secondary source is optional; its failure leaves these games on HOLD, not the whole sync.
        log.warning("fixture %s: Leaguepedia lookup failed (%s)", fixture.provider_id, type(exc).__name__)
        return
    if not rows:
        return
    for g in unknown:
        row = next((r for r in rows if r.game_in_series == g.game_index), None)
        if row is None:
            continue
        name = row.team1 if row.winner == 1 else row.team2
        g.winner_team_id = team_a.id if name == team_a.name else team_b.id if name == team_b.name else None
        if g.winner_team_id:
            g.winner_evidence, g.data_changed_at = "leaguepedia", now


def sync_history(session: Session, client: LolesportsClient, since: datetime) -> int:
    """Pull completed 2026 series from rated leagues for the team-strength model."""
    ids = client.leagues()
    added = 0
    for slug in RATING_LEAGUES:
        if slug not in ids:
            continue
        for m in client.schedule_since(ids[slug], since, max_pages=30):
            if m.state != "completed" or len(m.teams) != 2 or not all(m.teams):
                continue
            ta, tb = m.teams
            if ta.game_wins is None or tb.game_wins is None or ta.game_wins + tb.game_wins == 0:
                continue
            region = REGION_OF_LEAGUE.get(slug)
            a, b = upsert_team(session, ta, region), upsert_team(session, tb, region)
            row = session.get(HistoricalResult, m.match_id)
            if row is None:
                session.add(HistoricalResult(provider_id=m.match_id, league_slug=slug, played_at=m.start_time,
                                             team_a_id=a.id, team_b_id=b.id, team_a_wins=ta.game_wins,
                                             team_b_wins=tb.game_wins))
                added += 1
        session.flush()
    return added
