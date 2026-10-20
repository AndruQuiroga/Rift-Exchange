"""Adapter for the public lolesports web feed (D-009).

The feed is undocumented: every parser is defensive and returns typed records. Anything we cannot
parse confidently is surfaced as missing data so markets HOLD rather than guess.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from rift.config import Settings


def team_key(name: str) -> str:
    return "lolesports:" + " ".join(name.lower().split())


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


@dataclass
class TeamRef:
    key: str
    code: str
    name: str
    image: str | None
    game_wins: int | None
    outcome: str | None  # win / loss / None


@dataclass
class ScheduleMatch:
    match_id: str
    league_slug: str
    start_time: datetime
    state: str  # unstarted / inProgress / completed
    block_name: str
    best_of: int
    teams: list[TeamRef | None]  # None for TBD


@dataclass
class GameRef:
    game_id: str
    number: int
    state: str  # unstarted / inProgress / completed / unneeded
    blue_team_esports_id: str | None
    red_team_esports_id: str | None


@dataclass
class MatchDetail:
    match_id: str
    teams: list[tuple[str, str, int | None]]  # (esports_id, name, game_wins)
    games: list[GameRef]


@dataclass
class PlayerLine:
    participant_id: int
    esports_player_id: str | None
    name: str
    side: str
    role: str
    champion: str
    kills: int
    deaths: int
    assists: int


@dataclass
class GameStats:
    game_id: str
    patch: str | None
    state: str  # in_game / paused / finished
    first_frame_at: datetime | None
    last_frame_at: datetime | None
    blue_esports_team_id: str | None
    red_esports_team_id: str | None
    players: list[PlayerLine] = field(default_factory=list)
    team_totals: dict = field(default_factory=dict)


def _team_ref(raw: dict) -> TeamRef | None:
    name = (raw.get("name") or "").strip()
    if not name or name.upper() == "TBD" or (raw.get("code") or "").upper() == "TBD":
        return None
    result = raw.get("result") or {}
    return TeamRef(key=team_key(name), code=raw.get("code") or name[:4].upper(), name=name,
                   image=raw.get("image"), game_wins=result.get("gameWins"), outcome=result.get("outcome"))


def parse_schedule(payload: dict) -> tuple[list[ScheduleMatch], str | None]:
    sched = payload["data"]["schedule"]
    out = []
    for ev in sched.get("events", []):
        match = ev.get("match")
        if ev.get("type") != "match" or not match:
            continue
        strategy = match.get("strategy") or {}
        best_of = strategy.get("count") if strategy.get("type") == "bestOf" else None
        if best_of not in (1, 3, 5):
            continue
        out.append(ScheduleMatch(
            match_id=str(match["id"]), league_slug=(ev.get("league") or {}).get("slug", ""),
            start_time=parse_time(ev["startTime"]), state=ev.get("state", "unstarted"),
            block_name=ev.get("blockName") or "", best_of=best_of,
            teams=[_team_ref(t) for t in match.get("teams", [])],
        ))
    return out, (sched.get("pages") or {}).get("older")


def live_match_ids(payload: dict) -> set[str]:
    """Match ids the feed reports as in progress right now (getLive)."""
    events = ((payload.get("data") or {}).get("schedule") or {}).get("events") or []
    out = set()
    for ev in events:
        match = ev.get("match") or {}
        if ev.get("type") == "match" and match.get("id") and ev.get("state", "inProgress") == "inProgress":
            out.add(str(match["id"]))
    return out


def parse_event_details(payload: dict) -> MatchDetail:
    event = payload["data"]["event"]
    match = event["match"]
    teams = [(str(t["id"]), t.get("name", ""), (t.get("result") or {}).get("gameWins")) for t in match["teams"]]
    games = []
    for g in match.get("games", []):
        sides = {t.get("side"): str(t["id"]) for t in g.get("teams", []) if t.get("id")}
        games.append(GameRef(game_id=str(g["id"]), number=int(g["number"]), state=g.get("state", "unstarted"),
                             blue_team_esports_id=sides.get("blue"), red_team_esports_id=sides.get("red")))
    return MatchDetail(match_id=str(event["id"]), teams=teams, games=games)


def parse_window(payload: dict) -> GameStats:
    meta = payload.get("gameMetadata") or {}
    frames = payload.get("frames") or []
    blue_meta, red_meta = meta.get("blueTeamMetadata") or {}, meta.get("redTeamMetadata") or {}
    stats = GameStats(
        game_id=str(payload.get("esportsGameId", "")), patch=meta.get("patchVersion"),
        state=frames[-1]["gameState"] if frames else "unknown",
        first_frame_at=parse_time(frames[0]["rfc460Timestamp"]) if frames else None,
        last_frame_at=parse_time(frames[-1]["rfc460Timestamp"]) if frames else None,
        blue_esports_team_id=blue_meta.get("esportsTeamId"), red_esports_team_id=red_meta.get("esportsTeamId"),
    )
    if not frames:
        return stats
    last = frames[-1]
    for side, team_meta, frame_key in (("blue", blue_meta, "blueTeam"), ("red", red_meta, "redTeam")):
        by_pid = {p["participantId"]: p for p in last.get(frame_key, {}).get("participants", [])}
        for p in team_meta.get("participantMetadata", []):
            live = by_pid.get(p["participantId"], {})
            stats.players.append(PlayerLine(
                participant_id=p["participantId"], esports_player_id=p.get("esportsPlayerId"),
                name=p.get("summonerName", ""), side=side, role=p.get("role", ""), champion=p.get("championId", ""),
                kills=int(live.get("kills", 0)), deaths=int(live.get("deaths", 0)),
                assists=int(live.get("assists", 0)),
            ))
        team = last.get(frame_key, {})
        stats.team_totals[side] = {k: team.get(k) for k in
                                   ("totalKills", "towers", "inhibitors", "barons", "dragons", "totalGold")}
    return stats


class LolesportsClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.settings = settings
        self.http = http or httpx.Client(timeout=20, headers={"x-api-key": settings.lolesports_api_key})

    def _get(self, url: str, params: dict) -> dict:
        resp = self.http.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def schedule(self, league_id: str, page_token: str | None = None) -> tuple[list[ScheduleMatch], str | None]:
        params = {"hl": "en-US", "leagueId": league_id}
        if page_token:
            params["pageToken"] = page_token
        return parse_schedule(self._get(f"{self.settings.lolesports_api}/getSchedule", params))

    def schedule_since(self, league_id: str, since: datetime, max_pages: int = 12) -> list[ScheduleMatch]:
        matches, token = self.schedule(league_id)
        pages = 1
        while token and pages < max_pages and matches and min(m.start_time for m in matches) > since:
            older, token = self.schedule(league_id, token)
            matches = older + matches
            pages += 1
        return [m for m in matches if m.start_time >= since]

    def leagues(self) -> dict[str, str]:
        payload = self._get(f"{self.settings.lolesports_api}/getLeagues", {"hl": "en-US"})
        return {lg["slug"]: str(lg["id"]) for lg in payload["data"]["leagues"]}

    def live(self) -> set[str]:
        return live_match_ids(self._get(f"{self.settings.lolesports_api}/getLive", {"hl": "en-US"}))

    def event_details(self, match_id: str) -> MatchDetail:
        return parse_event_details(
            self._get(f"{self.settings.lolesports_api}/getEventDetails", {"hl": "en-US", "id": match_id}))

    def window(self, game_id: str, starting_time: datetime | None = None) -> GameStats | None:
        params = {}
        if starting_time is not None:
            # The feed wants a timestamp aligned to 10 seconds.
            t = starting_time.astimezone(UTC).replace(microsecond=0)
            t -= timedelta(seconds=t.second % 10)
            params["startingTime"] = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = self.http.get(f"{self.settings.lolesports_feed}/window/{game_id}", params=params)
        if resp.status_code in (204, 404):
            return None
        resp.raise_for_status()
        if not resp.content:
            return None
        return parse_window(resp.json())

    def final_stats(self, game_id: str, now: datetime) -> GameStats | None:
        """Latest frames for a game. Asking past the end of a game returns its final frames."""
        first = self.window(game_id)
        if first is None or first.first_frame_at is None:
            return None
        probe = min(now - timedelta(seconds=30), first.first_frame_at + timedelta(hours=3))
        if probe <= first.first_frame_at:
            return first
        latest = self.window(game_id, probe)
        return latest if latest is not None and latest.last_frame_at is not None else first
