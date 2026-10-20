"""Bounded historical priors isolated from wager fixtures and settlement."""
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from rift.champions import champion_key
from rift.models import Fixture, Game, ReferenceGame, Team


@dataclass(frozen=True)
class ReferenceEvent:
    name: str
    league_id: str
    league_slug: str
    category: str
    start: datetime
    end: datetime
    tournament_id: str | None = None

    def validate(self, cutoff):
        if self.category not in ("international", "regional"):
            raise ValueError("Unknown reference category")
        if not all(t.tzinfo is not None for t in (self.start, self.end, cutoff)):
            raise ValueError("Reference bounds require timezone-aware timestamps")
        if not self.start < self.end <= cutoff or self.start.year != cutoff.year:
            raise ValueError("Reference events must be this year's completed windows before cutoff")
        if self.end - self.start > timedelta(days=150 if self.category == "regional" else 60):
            raise ValueError("Use a split/event window, not a whole-year league history")


def ingest_references(session, client, secondary, events, cutoff, *, max_pages=4, max_matches=20,
                      max_games=60, cursor=(0, 0, 0)):
    """One bounded batch; caller owns transaction. Incomplete feeds remain missing.

    Manifest windows identify the latest regional season and international events explicitly.
    They are configuration, not evidence that a provider covers those events.
    """
    if not (1 <= max_pages <= 12 and 1 <= max_matches <= 100 and 1 <= max_games <= 300):
        raise ValueError("Reference batch limits out of bounds")
    if len(cursor) != 3 or any(type(v) is not int or v < 0 for v in cursor):
        raise ValueError("Cursor must contain three nonnegative integers")
    if not 1 <= len(events) <= 16:
        raise ValueError("Use 1..16 explicit reference event windows")
    for event in events:
        event.validate(cutoff)
    # Keep only the latest explicitly configured regional split per league.
    latest = {e.league_slug: max(x.start for x in events if x.category == "regional"
                               and x.league_slug == e.league_slug)
              for e in events if e.category == "regional"}
    events = [e for e in events if e.category != "regional" or e.start == latest[e.league_slug]]
    report = {"matches": 0, "attempted": 0, "stored": 0, "missing": 0, "coverage": "unverified",
              "next_cursor": list(cursor), "observed_games": 0, "with_stats": 0, "with_bans": 0,
              "enriched": 0, "draft_errors": 0, "schedule_pages_cap": max_pages}
    seen = set()
    teams = {t.provider_id: str(t.id) for t in session.scalars(select(Team))}
    from rift.adapters.lolesports import team_key
    for ei, event in enumerate(events):
        if ei < cursor[0]:
            continue
        matches = client.schedule_since(event.league_id, event.start, max_pages=max_pages)
        for mi, match in enumerate(sorted(matches, key=lambda m: (m.start_time, m.match_id))):
            if ei == cursor[0] and mi < cursor[1]:
                continue
            if report["matches"] >= max_matches or report["attempted"] >= max_games:
                return report
            if (match.match_id in seen or match.state != "completed" or match.league_slug != event.league_slug
                    or not event.start <= match.start_time < event.end):
                continue
            report["next_cursor"] = [ei, mi, 0]
            seen.add(match.match_id)
            report["matches"] += 1
            detail = client.event_details(match.match_id)
            if detail.match_id != match.match_id or len(detail.games) > 10:
                raise ValueError("Reference match identity or game count is invalid")
            names = {tid: name for tid, name, _ in detail.teams}
            drafts = None
            for gi, game in enumerate(detail.games):
                if ei == cursor[0] and mi == cursor[1] and gi < cursor[2]:
                    continue
                if report["attempted"] >= max_games:
                    report["next_cursor"] = [ei, mi, gi]
                    return report
                report["next_cursor"] = [ei, mi, gi + 1]
                if game.state != "completed":
                    continue
                report["observed_games"] += 1
                existing = session.get(ReferenceGame, game.game_id)
                if existing is not None:
                    report["with_stats"] += 1
                    report["with_bans"] += int(bool(existing.payload.get("bans")))
                    if existing.payload.get("bans") or not secondary.available:
                        continue
                report["attempted"] += 1
                stats = client.final_stats(game.game_id, cutoff)
                if (not stats or stats.state != "finished" or len(stats.players) != 10
                        or not stats.first_frame_at or not stats.last_frame_at
                        or not event.start <= stats.first_frame_at < stats.last_frame_at <= min(event.end, cutoff)
                        or stats.game_id != game.game_id):
                    report["missing"] += 1
                    continue
                side_ids = {"blue": game.blue_team_esports_id, "red": game.red_team_esports_id}
                if (set(side_ids.values()) != set(names) or len(names) != 2
                        or any(sum(p.side == side for p in stats.players) != 5 for side in side_ids)
                        or any(not p.champion or p.kills < 0 for p in stats.players)
                        or len({champion_key(p.champion) for p in stats.players}) != 10):
                    report["missing"] += 1
                    continue
                payload = {"league_slug": event.league_slug, "window_start": event.start.isoformat(),
                           "window_end": event.end.isoformat(), "tournament_id": event.tournament_id, "patch": stats.patch, "match_id": match.match_id, "players": [
                    {"player_id": p.esports_player_id, "name": p.name, "role": p.role,
                     "champion": p.champion, "kills": p.kills,
                     "team_id": teams.get(team_key(names[side_ids[p.side]]))} for p in stats.players]}
                if existing is None:
                    report["with_stats"] += 1
                if secondary.available:
                    if drafts is None:
                        try:
                            drafts = secondary.series_drafts(*names.values(), match.start_time) or []
                        except (RuntimeError, ValueError, KeyError, httpx.HTTPError):
                            drafts = []
                            report["draft_errors"] += 1
                    candidates = [d for d in drafts if d.game_in_series == game.number
                                  and {d.team1, d.team2} == set(names.values())
                                  and abs((d.played_at.replace(tzinfo=UTC) if d.played_at.tzinfo is None
                                           else d.played_at) - stats.first_frame_at).total_seconds() < 3600]
                    if len(candidates) == 1:
                        d = candidates[0]
                        if d.draft and d.team1 == names[side_ids["blue"]]:
                            expected = {champion_key(p.champion) for p in stats.players}
                            actual = {champion_key(c) for c in d.draft.team1_picks + d.draft.team2_picks}
                            bans = d.team1_bans + d.team2_bans
                            if (expected == actual and len(bans) == 10
                                    and len(set(map(champion_key, bans))) == 10
                                    and not expected.intersection(map(champion_key, bans))):
                                payload["bans"] = {"blue": d.team1_bans, "red": d.team2_bans}
                if existing is not None:
                    if not payload.get("bans"):
                        continue
                    # Enrich only the missing draft; never overwrite existing final stats on a rerun.
                    payload = {**existing.payload, "bans": payload["bans"]}
                    existing.payload = payload
                    existing.content_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
                    existing.fetched_at = datetime.now(UTC)
                    report["enriched"] += 1
                    report["with_bans"] += 1
                    continue
                report["with_bans"] += int(bool(payload.get("bans")))
                digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
                session.execute(insert(ReferenceGame).values(
                    provider_id=game.game_id, event=event.name, category=event.category,
                    played_at=stats.first_frame_at, ended_at=stats.last_frame_at, fetched_at=datetime.now(UTC),
                    content_hash=digest, payload=payload).on_conflict_do_nothing())
                report["stored"] += 1
            report["next_cursor"] = [ei, mi + 1, 0]
    report["next_cursor"] = None
    return report


def observations(session, season, *, cutoff=None):
    """Current weight 1, international .5, regional .25; historical mass capped at 40 games."""
    fixtures = list(session.scalars(select(Fixture).where(Fixture.season_id == season.id)))
    if not fixtures:
        return []
    boundary = min(f.scheduled_at for f in fixtures)
    boundary = min(boundary, cutoff) if cutoff else boundary
    games = list(session.scalars(select(Game).where(Game.fixture_id.in_([f.id for f in fixtures]))))
    out = [(g, 1.0) for g in games if g.state == "completed" and
           (cutoff is None or (g.ended_at is not None and g.ended_at < cutoff))]
    ids = set(session.scalars(select(Game.provider_id)))
    # Bound each stratum independently: a busy regional season must not push all
    # older internationals out before category budgets can be applied.
    refs = []
    for category in ("international", "regional"):
        refs.extend(session.scalars(select(ReferenceGame).where(
            ReferenceGame.category == category, ReferenceGame.ended_at < boundary,
            ReferenceGame.played_at >= datetime(boundary.year, 1, 1, tzinfo=UTC))
            .order_by(ReferenceGame.played_at.desc(), ReferenceGame.provider_id).limit(300)))
    refs.sort(key=lambda r: (r.played_at, r.provider_id), reverse=True)
    latest_split = {}
    for ref in refs:
        if ref.category == "regional":
            league = ref.payload.get("league_slug")
            start = datetime.fromisoformat(ref.payload["window_start"])
            latest_split[league] = max(start, latest_split.get(league, start))
    mass = 0.0
    category_mass = {}
    event_mass = {}
    for ref in refs:
        if (ref.category == "regional" and datetime.fromisoformat(ref.payload["window_start"]) !=
                latest_split.get(ref.payload.get("league_slug"))):
            continue
        if (ref.provider_id in ids or mass >= 40 or category_mass.get(ref.category, 0) >= 20
                or event_mass.get(ref.event, 0) >= 10):
            continue
        weight = .5 if ref.category == "international" else .25
        mass += weight
        category_mass[ref.category] = category_mass.get(ref.category, 0) + weight
        event_mass[ref.event] = event_mass.get(ref.event, 0) + weight
        out.append((SimpleNamespace(provider_id=ref.provider_id, stats=ref.payload, stats_complete=True,
                                    bans=ref.payload.get("bans"), timeline_complete=False), weight))
    return out


def discover_events(client, cutoff):
    """Discover actual provider tournament IDs/date bounds; never infer a split from year-long schedules."""
    if cutoff.tzinfo is None:
        raise ValueError("Discovery cutoff requires timezone")
    from rift.ingest import RATING_LEAGUES, REGION_OF_LEAGUE
    leagues = client.leagues()
    events = []
    diagnostics = []
    for slug in RATING_LEAGUES:
        if slug == "worlds" or slug not in leagues:
            continue
        result = client._get(f"{client.settings.lolesports_api}/getTournamentsForLeague",
                             {"hl": "en-US", "leagueId": leagues[slug]})
        candidates = []
        wrappers = result.get("data", {}).get("leagues", [])
        if not wrappers:
            diagnostics.append({"league": slug, "status": "no tournament wrappers; coverage unknown"})
        for league in wrappers:
            if league.get("id") is None and len(wrappers) != 1:
                diagnostics.append({"league": slug, "status": "ambiguous anonymous league wrappers"})
                continue
            if league.get("id") is not None and str(league["id"]) != leagues[slug]:
                continue
            for tournament in league.get("tournaments", []):
                try:
                    start = datetime.fromisoformat(tournament["startDate"]).replace(tzinfo=UTC)
                    # Provider date-only end bounds are inclusive calendar dates.
                    end = datetime.fromisoformat(tournament["endDate"]).replace(tzinfo=UTC) + timedelta(days=1)
                    category = "regional" if slug in REGION_OF_LEAGUE else "international"
                    event = ReferenceEvent(str(tournament["slug"]), leagues[slug], slug, category, start, end,
                                           str(tournament["id"]))
                    event.validate(cutoff)
                    candidates.append(event)
                except (KeyError, TypeError, ValueError):
                    diagnostics.append({"league": slug, "tournament": tournament.get("id"),
                                        "status": "excluded: missing/invalid bounds, other year or after cutoff"})
        if slug in REGION_OF_LEAGUE and candidates:
            candidates = [max(candidates, key=lambda e: (e.start, e.end, e.name))]
        events.extend(candidates)
    return events, diagnostics


def main():
    import argparse

    from rift.adapters.leaguepedia import make_source
    from rift.adapters.lolesports import LolesportsClient
    from rift.config import get_settings
    from rift.db import transaction
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?")
    parser.add_argument("--discover", type=Path, help="write a feed-derived manifest; no database access")
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--cursor", default="[0,0,0]", help="JSON next_cursor from previous batch")
    args = parser.parse_args()
    settings = get_settings()
    if args.discover:
        from dataclasses import asdict
        events, diagnostics = discover_events(LolesportsClient(settings), datetime.fromisoformat(args.cutoff))
        args.discover.write_text(json.dumps([dict(asdict(e), start=e.start.isoformat(), end=e.end.isoformat())
                                            for e in events], indent=2), encoding="utf-8")
        print(json.dumps({"events": len(events), "coverage": "unverified", "diagnostics": diagnostics}))
        return
    if args.manifest is None:
        parser.error("provide a manifest or --discover output.json")
    events = [ReferenceEvent(**{**e, "start": datetime.fromisoformat(e["start"]),
                               "end": datetime.fromisoformat(e["end"])})
              for e in json.loads(args.manifest.read_text())]
    with transaction() as session:
        print(json.dumps(ingest_references(session, LolesportsClient(settings), make_source(settings),
                                         events, datetime.fromisoformat(args.cutoff), cursor=tuple(json.loads(args.cursor)))))


if __name__ == "__main__":
    main()
