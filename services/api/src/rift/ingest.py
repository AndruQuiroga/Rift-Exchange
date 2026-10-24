"""Canonical fixture/game ingestion from provider adapters (docs/spec/10_DATA_PIPELINES.md)."""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from rift.adapters.leaguepedia import LeaguepediaGame, LeaguepediaSource
from rift.adapters.lolesports import LolesportsClient, ScheduleMatch, TeamRef, team_key
from rift.champions import champion_id
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
    # The feed may list the same pair in the other order once a game loads (blue side first). Markets,
    # picks and grading all key on A/B, so a fixture keeps the orientation it was created with.
    if teams[0] and teams[1] and (teams[1].id, teams[0].id) == (fixture.team_a_id, fixture.team_b_id):
        teams.reverse()
        a_wins, b_wins = b_wins, a_wins
    status = STATUS.get(m.state, "SCHEDULED")
    if fixture.status == "LIVE" and status == "SCHEDULED":
        status = "LIVE"  # getLive saw it start before the schedule caught up; never re-open a live series
    need = m.best_of // 2 + 1
    if status == "LIVE" and max(a_wins, b_wins) == need and min(a_wins, b_wins) < need:
        # The feed can list a decided series as in progress for a long while after its last game. The game
        # wins already settle it; settlement still waits for them to hold steady before paying.
        status = "COMPLETED"
    before =(fixture.status, fixture.team_a_wins, fixture.team_b_wins, fixture.team_a_id, fixture.team_b_id,
              fixture.scheduled_at)
    fixture.stage, fixture.best_of = m.block_name, m.best_of
    fixture.team_a_id = teams[0].id if teams[0] else None
    fixture.team_b_id = teams[1].id if teams[1] else None
    fixture.scheduled_at = m.start_time
    fixture.local_date = m.start_time.astimezone(tz).date()
    if status == "LIVE" and fixture.live_at is None:
        fixture.live_at = now  # D-039: starts the draft countdown (when the schedule saw it first)
    fixture.status, fixture.team_a_wins, fixture.team_b_wins = status, a_wins, b_wins
    if status == "COMPLETED":
        winner = 0 if a_wins == need else 1 if b_wins == need else None
        fixture.winner_team_id = teams[winner].id if winner is not None and teams[winner] else None
        fixture.completed_at = fixture.completed_at or now
    elif status == "LIVE":
        fixture.winner_team_id = fixture.completed_at = None  # a corrected score reopened the series
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
        f.live_at = f.live_at or now  # D-039: starts the draft countdown
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
            try:
                stats = client.final_stats(game.provider_id, now)
            except httpx.HTTPError as exc:
                # One game's feed trouble must not roll back every fixture's details this cycle; retry next time.
                log.warning("game %s: final stats unavailable (%s)", game.provider_id, type(exc).__name__)
                continue
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
                # The same fetch dates the game, so the next game's markets need not wait for the timeline.
                game.started_at = game.started_at or stats.first_frame_at
                game.ended_at = game.ended_at or stats.last_frame_at
    infer_game_winners(session, fixture, list(games.values()), secondary, now)
    fixture.details_synced_at = now
    session.flush()


def games_to_track(fixture: Fixture, games: list[Game], now: datetime) -> list[Game]:
    """Games whose livestats timeline should advance this cycle.

    Live and finished-but-incomplete games, plus the next unplayed game of an undecided live series: its
    first frame (the game has loaded after the draft) is the earliest sign it started, which locks its
    markets before the schedule feed catches up.
    """
    if fixture.status == "COMPLETED" and fixture.completed_at and now - fixture.completed_at > timedelta(hours=6):
        return []
    out = [g for g in games if not g.timeline_complete and (
        g.state in ("inProgress", "completed") or (g.state == "unstarted" and g.started_at is not None))]
    need = fixture.best_of // 2 + 1
    if fixture.status == "LIVE" and max(fixture.team_a_wins, fixture.team_b_wins) < need:
        played = {g.game_index for g in games if g.state == "completed" or g.ended_at is not None}
        nxt = next((g for g in sorted(games, key=lambda g: g.game_index)
                    if g.state == "unstarted" and set(range(1, g.game_index)) <= played), None)
        if nxt is not None and nxt.started_at is None:
            out.append(nxt)
    return out


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


LINEUP_ROLES = {"top", "jungle", "mid", "bottom", "support"}


def sync_lineups(session: Session, season: Season, client: LolesportsClient, now: datetime, limit: int = 8) -> int:
    """Starting fives for teams in upcoming fixtures that haven't played at Worlds yet.

    Lane duels need a lineup before the series. Once a team has a Worlds game its timeline is used instead;
    until then take the five from the last completed game of its most recent regional match. A few teams
    per cycle, refreshed daily, so the feed sees a handful of requests.
    """
    fixtures = session.execute(select(Fixture).where(
        Fixture.season_id == season.id, Fixture.status == "SCHEDULED",
        Fixture.team_a_id.is_not(None), Fixture.team_b_id.is_not(None))).scalars().all()
    played = {t for row in session.execute(select(Game.blue_team_id, Game.red_team_id).join(
        Fixture, Fixture.id == Game.fixture_id).where(Fixture.season_id == season.id,
                                                      Game.timeline.is_not(None))).all() for t in row if t}
    done = 0
    for team_id in {t for f in fixtures for t in (f.team_a_id, f.team_b_id)} - played:
        team = session.get(Team, team_id)
        stale = team.lineup is None or now - datetime.fromisoformat(team.lineup["at"]) > timedelta(days=1)
        if not stale or done >= limit:
            continue
        done += 1
        last = session.execute(select(HistoricalResult).where(
            (HistoricalResult.team_a_id == team.id) | (HistoricalResult.team_b_id == team.id))
            .order_by(HistoricalResult.played_at.desc()).limit(1)).scalar_one_or_none()
        if last is None:
            continue
        try:
            detail = client.event_details(last.provider_id)
            game = next((g for g in sorted(detail.games, key=lambda g: -g.number) if g.state == "completed"), None)
            stats = client.window(game.game_id) if game else None
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            log.warning("lineup for %s unavailable (%s)", team.code, type(exc).__name__)
            continue
        esports_id = next((eid for eid, name, _w in detail.teams if team_key(name) == team.provider_id), None)
        side = ("blue" if stats and esports_id == stats.blue_esports_team_id else
                "red" if stats and esports_id == stats.red_esports_team_id else None)
        if side is None:
            continue
        players = {p.role: {"player_id": p.esports_player_id or p.name, "name": p.name}
                   for p in stats.players if p.side == side and p.role in LINEUP_ROLES}
        if set(players) == LINEUP_ROLES:
            team.lineup = {"match": last.provider_id, "at": now.isoformat(), "players": players}
    session.flush()
    return done


def needs_draft(game: Game) -> bool:
    """A completed game whose Leaguepedia bans or pick order are not stored yet."""
    return game.state == "completed" and (not game.bans or game.bans.get("first_pick") is None)


def draft_record(fixture: Fixture, game: Game, row: LeaguepediaGame, team_a: Team, team_b: Team) -> dict | None:
    """The `Game.bans` value for one Leaguepedia row, or None when it cannot be trusted yet.

    Leaguepedia's Team1 is blue side. Its team must agree with the side livestats reported for the game;
    otherwise bans would be attributed to the wrong team, so nothing is stored. Bans are required (both lists
    empty means editors have not filled the game in); pick order is optional and refetched until present.
    """
    sides = {(team_a.name, team_b.name): (team_a, team_b), (team_b.name, team_a.name): (team_b, team_a)}
    if (row.team1, row.team2) not in sides:
        return None
    blue, red = sides[(row.team1, row.team2)]
    if game.blue_team_id is not None and game.blue_team_id != blue.id:
        log.warning("fixture %s game %s: Leaguepedia sides disagree with livestats", fixture.provider_id,
                    game.game_index)
        return None
    try:
        bans = {"blue": [c for c in map(champion_id, row.team1_bans) if c],
                "red": [c for c in map(champion_id, row.team2_bans) if c]}
        draft = row.draft
        picks = {"blue": [champion_id(c) for c in draft.team1_picks],
                 "red": [champion_id(c) for c in draft.team2_picks]} if draft else None
    except ValueError:
        log.warning("fixture %s game %s: unreadable Leaguepedia champion", fixture.provider_id, game.game_index)
        return None
    if not bans["blue"] and not bans["red"]:
        return None
    if picks and not all(all(side) for side in picks.values()):
        picks = None
    code = {fixture.team_a_id: "A", fixture.team_b_id: "B"}
    return {"source": "leaguepedia", **bans,
            "first_pick": picks["blue"][0] if picks else None, "first_pick_side": "blue" if picks else None,
            "picks": picks, "roles": {"blue": draft.team1_roles, "red": draft.team2_roles} if picks else None,
            "sides": {"blue": code.get(blue.id), "red": code.get(red.id)}}


def sync_drafts(session: Session, fixture: Fixture, secondary: LeaguepediaSource, now: datetime) -> int:
    """Store bans and pick order from Leaguepedia on completed games that lack them. Returns games updated.

    One query per fixture per call; the worker runs this on its own slow cadence. Any provider failure
    leaves the games without bans (their ban/first-pick markets HOLD, then void after the deadline).
    """
    games = [g for g in session.execute(select(Game).where(Game.fixture_id == fixture.id)).scalars()
             if needs_draft(g)]
    if not games or not secondary.available or fixture.team_a_id is None or fixture.team_b_id is None:
        return 0
    team_a, team_b = session.get(Team, fixture.team_a_id), session.get(Team, fixture.team_b_id)
    try:
        rows = secondary.series_drafts(team_a.name, team_b.name, fixture.scheduled_at)
    except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as exc:
        log.warning("fixture %s: Leaguepedia draft lookup failed (%s)", fixture.provider_id, type(exc).__name__)
        return 0
    updated = 0
    for game in games:
        row = next((r for r in rows or [] if r.game_in_series == game.game_index), None)
        record = draft_record(fixture, game, row, team_a, team_b) if row else None
        if record is None or record == game.bans:
            continue
        if game.bans and game.bans.get("first_pick") is not None and record["first_pick"] is None:
            continue  # never drop pick order already stored because a later read lacked it
        game.bans, game.data_changed_at = record, now
        updated += 1
    session.flush()
    return updated


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
