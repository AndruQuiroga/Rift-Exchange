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


SIDES = ("blue", "red")
COUNTERS = ("kills", "towers", "inhibitors", "barons", "dragons")


@dataclass
class TeamFrame:
    gold: int
    kills: int
    towers: int
    inhibitors: int
    barons: int
    dragons: list[str]  # dragon types in the order this team took them

    def count(self, metric: str) -> int:
        return len(self.dragons) if metric == "dragons" else getattr(self, metric)


@dataclass
class Frame:
    at: datetime
    state: str  # in_game / paused / finished
    teams: dict[str, TeamFrame]  # blue / red
    players: dict[int, dict]  # participantId -> {kills, deaths, assists, cs, gold, level}


@dataclass
class Window:
    """One livestats window: participant metadata plus the (dense, ~10 s) frames it returned."""

    game_id: str
    patch: str | None
    team_esports_ids: dict[str, str | None]
    participants: dict[int, dict]  # participantId -> {side, champion, player_id, name, role}
    frames: list[Frame]


def _int(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"not a count: {value!r}")
    return int(value)


def _team_frame(raw: dict) -> TeamFrame:
    dragons = raw.get("dragons")
    if not isinstance(dragons, list) or not all(isinstance(d, str) for d in dragons):
        raise TypeError("dragons must be a list of type names")
    return TeamFrame(gold=_int(raw.get("totalGold")), kills=_int(raw.get("totalKills")),
                     towers=_int(raw.get("towers")), inhibitors=_int(raw.get("inhibitors")),
                     barons=_int(raw.get("barons")), dragons=[d.lower() for d in dragons])


def parse_frames(payload: dict) -> Window:
    """Parse a /window payload. Frames with missing or malformed counters are dropped, never guessed."""
    meta = payload.get("gameMetadata") or {}
    participants: dict[int, dict] = {}
    team_ids: dict[str, str | None] = {}
    for side in SIDES:
        team_meta = meta.get(f"{side}TeamMetadata") or {}
        team_ids[side] = team_meta.get("esportsTeamId")
        for p in team_meta.get("participantMetadata") or []:
            if isinstance(p.get("participantId"), int):
                participants[p["participantId"]] = {
                    "side": side, "champion": p.get("championId") or None, "player_id": p.get("esportsPlayerId"),
                    "name": p.get("summonerName", ""), "role": p.get("role", "")}
    frames = []
    for raw in payload.get("frames") or []:
        try:
            teams = {side: _team_frame(raw[f"{side}Team"]) for side in SIDES}
            players = {}
            for side in SIDES:
                for p in raw[f"{side}Team"].get("participants") or []:
                    players[_int(p["participantId"])] = {
                        "kills": _int(p.get("kills")), "deaths": _int(p.get("deaths")),
                        "assists": _int(p.get("assists")), "cs": _int(p.get("creepScore")),
                        "gold": _int(p.get("totalGold")), "level": _int(p.get("level"))}
            frames.append(Frame(at=parse_time(raw["rfc460Timestamp"]), state=str(raw.get("gameState", "unknown")),
                                teams=teams, players=players))
        except (KeyError, TypeError, ValueError):
            continue
    frames.sort(key=lambda f: f.at)
    return Window(game_id=str(payload.get("esportsGameId", "")), patch=meta.get("patchVersion"),
                  team_esports_ids=team_ids, participants=participants, frames=frames)


def parse_detail_frames(payload: dict) -> list[tuple[datetime, dict[int, dict]]]:
    """Parse a /details payload into (time, participantId -> end-of-frame line) pairs."""
    out = []
    for raw in payload.get("frames") or []:
        try:
            players = {}
            for p in raw["participants"]:
                share, kp = p.get("championDamageShare"), p.get("killParticipation")
                players[_int(p["participantId"])] = {
                    "kills": _int(p.get("kills")), "deaths": _int(p.get("deaths")),
                    "assists": _int(p.get("assists")), "cs": _int(p.get("creepScore")),
                    "gold": _int(p.get("totalGoldEarned")),
                    "damage_share": round(float(share), 4) if isinstance(share, int | float) else None,
                    "kill_participation": round(float(kp), 4) if isinstance(kp, int | float) else None}
            out.append((parse_time(raw["rfc460Timestamp"]), players))
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda row: row[0])
    return out


def feed_time(t: datetime) -> str:
    """The livestats feed wants a UTC timestamp aligned down to 10 seconds."""
    t = t.astimezone(UTC).replace(microsecond=0)
    t -= timedelta(seconds=t.second % 10)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


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

    def _feed(self, path: str, game_id: str, starting_time: datetime | None) -> dict | None:
        params = {"startingTime": feed_time(starting_time)} if starting_time is not None else {}
        resp = self.http.get(f"{self.settings.lolesports_feed}/{path}/{game_id}", params=params)
        if resp.status_code in (204, 404):
            return None
        resp.raise_for_status()
        if not resp.content:
            return None
        return resp.json()

    def window(self, game_id: str, starting_time: datetime | None = None) -> GameStats | None:
        payload = self._feed("window", game_id, starting_time)
        return parse_window(payload) if payload is not None else None

    def frames(self, game_id: str, starting_time: datetime | None = None) -> Window | None:
        """Frames from ~starting_time (10 s of them); the first window when no time is given.

        Asking past the end of a game returns its final frames; nothing is returned before it loads.
        """
        payload = self._feed("window", game_id, starting_time)
        return parse_frames(payload) if payload is not None else None

    def detail_frames(self, game_id: str, starting_time: datetime) -> list[tuple[datetime, dict[int, dict]]]:
        payload = self._feed("details", game_id, starting_time)
        return parse_detail_frames(payload) if payload is not None else []

    def final_stats(self, game_id: str, now: datetime) -> GameStats | None:
        """Latest frames for a game. Asking past the end of a game returns its final frames."""
        first = self.window(game_id)
        if first is None or first.first_frame_at is None:
            return None
        probe = min(now - timedelta(seconds=30), first.first_frame_at + timedelta(hours=3))
        if probe <= first.first_frame_at:
            return first
        try:
            latest = self.window(game_id, probe)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            return first  # the feed hasn't reached that time yet (broadcast delay): not finished, try next cycle
        return latest if latest is not None and latest.last_frame_at is not None else first
