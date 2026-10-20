"""Leaguepedia Cargo adapter (secondary source: bans + game-winner cross-check, D-009).

Anonymous Cargo queries are aggressively rate-limited, so the real client logs in with a BotPassword.
Until credentials exist the adapter runs in `mock` mode and reports *no data*: ban markets stay off and
nothing is ever settled from invented values.
"""

from dataclasses import dataclass
from datetime import datetime

import httpx

from rift.config import Settings

API = "https://lol.fandom.com/api.php"


@dataclass
class LeaguepediaGame:
    team1: str
    team2: str
    winner: int  # 1 or 2
    game_in_series: int
    played_at: datetime
    team1_bans: list[str]
    team2_bans: list[str]


class LeaguepediaSource:
    available = False

    def series_games(self, team_a: str, team_b: str, on: datetime) -> list[LeaguepediaGame] | None:
        return None


class MockLeaguepedia(LeaguepediaSource):
    """Stand-in until a bot account exists. Tests may preload games keyed by (team_a, team_b)."""

    def __init__(self, games: dict[tuple[str, str], list[LeaguepediaGame]] | None = None):
        self.games = games or {}
        self.available = bool(self.games)

    def series_games(self, team_a, team_b, on):
        return self.games.get((team_a, team_b)) or self.games.get((team_b, team_a))


class LeaguepediaClient(LeaguepediaSource):
    available = True

    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.http = http or httpx.Client(timeout=30, headers={"User-Agent": "RiftExchange/0.1 (private league)"})
        self._login(settings.leaguepedia_bot_user, settings.leaguepedia_bot_password)

    def _login(self, user: str, password: str) -> None:
        token = self.http.get(API, params={"action": "query", "meta": "tokens", "type": "login",
                                           "format": "json"}).json()["query"]["tokens"]["logintoken"]
        result = self.http.post(API, data={"action": "login", "lgname": user, "lgpassword": password,
                                           "lgtoken": token, "format": "json"}).json()
        if result.get("login", {}).get("result") != "Success":
            raise RuntimeError(f"Leaguepedia login failed: {result}")

    def series_games(self, team_a, team_b, on):
        day = on.strftime("%Y-%m-%d")
        rows = self.http.get(API, params={
            "action": "cargoquery", "format": "json", "limit": 10,
            "tables": "ScoreboardGames=SG, PicksAndBansS7=PB",
            "join_on": "SG.GameId=PB.GameId",
            "fields": "SG.Team1, SG.Team2, SG.WinTeam, SG.N_GameInMatch, SG.DateTime_UTC, PB.Team1Bans, PB.Team2Bans",
            "where": (f'SG.DateTime_UTC >= "{day} 00:00:00" AND SG.DateTime_UTC <= "{day} 23:59:59" '
                      f'AND ((SG.Team1="{team_a}" AND SG.Team2="{team_b}") OR (SG.Team1="{team_b}" AND SG.Team2="{team_a}"))'),
        }).json()
        out = []
        for row in rows.get("cargoquery", []):
            r = row["title"]
            out.append(LeaguepediaGame(
                team1=r["Team1"], team2=r["Team2"], winner=1 if r["WinTeam"] == r["Team1"] else 2,
                game_in_series=int(r["N GameInMatch"]),
                played_at=datetime.fromisoformat(r["DateTime UTC"]),
                team1_bans=[b for b in (r.get("Team1Bans") or "").split(",") if b],
                team2_bans=[b for b in (r.get("Team2Bans") or "").split(",") if b],
            ))
        return out or None


def make_source(settings: Settings) -> LeaguepediaSource:
    if settings.leaguepedia_mode == "live" and settings.leaguepedia_bot_user:
        return LeaguepediaClient(settings)
    return MockLeaguepedia()
