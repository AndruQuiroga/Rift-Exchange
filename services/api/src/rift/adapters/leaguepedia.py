"""Leaguepedia Cargo adapter (secondary source: bans + game-winner cross-check, D-009).

Anonymous Cargo queries are aggressively rate-limited, so the real client logs in with a BotPassword.
Until credentials exist the adapter runs in `mock` mode and reports *no data*: ban markets stay off and
nothing is ever settled from invented values.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from rift.config import Settings

API = "https://lol.fandom.com/api.php"
# Leaguepedia's ScoreboardGames declaration stores aggregate bans here, not PicksAndBansS7.
GAME_FIELDS = ("SG.Team1, SG.Team2, SG.WinTeam, SG.N_GameInMatch, SG.DateTime_UTC, "
               "SG.Team1Bans__full=Team1Bans, SG.Team2Bans__full=Team2Bans, SG.Gamelength_Number=Gamelength")
# Pick order lives in PicksAndBansS7 (fields per its Cargo declaration, checked via action=cargofields),
# joined on the shared GameId. Team1 is blue side in both tables; blue makes the first pick. PB's own team
# names come back so a row whose sides disagree with the scoreboard is rejected rather than trusted.
DRAFT_TABLES = "ScoreboardGames=SG, PicksAndBansS7=PB"
DRAFT_JOIN = "SG.GameId=PB.GameId"
DRAFT_FIELDS = GAME_FIELDS + ", PB.Team1=PBTeam1, PB.Team2=PBTeam2, " + ", ".join(
    f"PB.Team{t}{kind}{i}" for t in (1, 2) for kind in ("Pick", "Role") for i in range(1, 6))
ROLES = {"top": "top", "jungle": "jungle", "mid": "mid", "bot": "bottom", "bottom": "bottom", "adc": "bottom",
         "support": "support"}


@dataclass
class LeaguepediaDraft:
    """One game's pick order: champion display names in pick order, with the role each was played in."""

    team1_picks: list[str]
    team2_picks: list[str]
    team1_roles: list[str | None]
    team2_roles: list[str | None]
# Verified against the October 2026 Play-In scoreboards. No fuzzy team matching.
PROVIDER_TEAM_NAMES = {"Cloud9 Kia": "Cloud9"}


@dataclass
class LeaguepediaGame:
    team1: str
    team2: str
    winner: int  # 1 or 2
    game_in_series: int
    played_at: datetime
    team1_bans: list[str]
    team2_bans: list[str]
    draft: LeaguepediaDraft | None = None  # filled by series_drafts only; None when PB has no full draft
    length_s: int | None = None  # official game time (pauses excluded), when editors have filled it in


class LeaguepediaSource:
    available = False

    def series_games(self, team_a: str, team_b: str, on: datetime) -> list[LeaguepediaGame] | None:
        return None

    def series_drafts(self, team_a: str, team_b: str, on: datetime) -> list[LeaguepediaGame] | None:
        """Like series_games, plus each game's pick order. A separate query, so a failure here (or a wrong
        join) can never cost the winner cross-check."""
        return None


class MockLeaguepedia(LeaguepediaSource):
    """Stand-in until a bot account exists. Tests may preload games keyed by (team_a, team_b)."""

    def __init__(self, games: dict[tuple[str, str], list[LeaguepediaGame]] | None = None):
        self.games = games or {}
        self.available = bool(self.games)
        self.calls = 0

    def series_games(self, team_a, team_b, on):
        self.calls += 1
        return self.games.get((team_a, team_b)) or self.games.get((team_b, team_a))

    def series_drafts(self, team_a, team_b, on):
        return self.series_games(team_a, team_b, on)


class LeaguepediaClient(LeaguepediaSource):
    available = True

    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        if not settings.leaguepedia_bot_user.strip() or not settings.leaguepedia_bot_password.strip():
            raise RuntimeError("Leaguepedia live mode requires both bot username and bot password")
        self.http = http or httpx.Client(timeout=30, headers={"User-Agent": "RiftExchange/0.1 (private league)"})
        self._team_names: dict[str, str] = {}
        # Log in on first use, so a provider outage cannot stop the worker from starting.
        self._credentials: tuple[str, str] | None = (settings.leaguepedia_bot_user,
                                                     settings.leaguepedia_bot_password)

    def _query(self, **params) -> dict:
        if self._credentials is not None:
            self._login(*self._credentials)
            self._credentials = None
        return self._request("GET", params=params)

    def _request(self, method: str, **kwargs) -> dict:
        response = self.http.request(method, API, **kwargs)
        response.raise_for_status()
        result = response.json()
        if "error" in result:
            # Provider responses can contain credentials or query details. Keep them out of logs.
            raise RuntimeError("Leaguepedia API returned an error; verify credentials and Cargo access")
        return result

    def _login(self, user: str, password: str) -> None:
        token = self._request("GET", params={"action": "query", "meta": "tokens", "type": "login",
                                           "format": "json"})["query"]["tokens"]["logintoken"]
        result = self._request("POST", data={"action": "login", "lgname": user, "lgpassword": password,
                                           "lgtoken": token, "format": "json"})
        if result.get("login", {}).get("result") != "Success":
            raise RuntimeError("Leaguepedia login failed; verify the generated bot login pair")

    def check_access(self) -> None:
        """Verify authenticated Cargo access and the tables used by this adapter, not worker liveness."""
        result = self._query(action="cargoquery", format="json", limit=1, tables="ScoreboardGames=SG",
                             fields=GAME_FIELDS, order_by="SG.DateTime_UTC DESC")
        if not result.get("cargoquery"):
            raise RuntimeError("Leaguepedia Cargo probe returned no game rows; coverage is unverified")
        self._parse_games(result["cargoquery"])

    @staticmethod
    def _quote(value: str) -> str:
        return '"' + value.replace('\\', '\\\\').replace('"', '""') + '"'

    def _canonical_team(self, name: str) -> str:
        if name not in self._team_names:
            lookup = PROVIDER_TEAM_NAMES.get(name, name)
            result = self._query(action="cargoquery", format="json", limit=2, tables="TeamRedirects=TR",
                                 fields="TR._pageName=Canonical", where=f"TR.AllName={self._quote(lookup)}")
            if "cargoquery" not in result:
                raise RuntimeError("Leaguepedia response is missing team redirect results")
            names = {r["title"]["Canonical"] for r in result["cargoquery"]}
            if len(names) > 1:
                raise RuntimeError("Leaguepedia team redirect is ambiguous")
            self._team_names[name] = next(iter(names), lookup)
        return self._team_names[name]

    def series_games(self, team_a, team_b, on):
        return self._series(team_a, team_b, on, tables="ScoreboardGames=SG", fields=GAME_FIELDS)

    def series_drafts(self, team_a, team_b, on):
        return self._series(team_a, team_b, on, tables=DRAFT_TABLES, fields=DRAFT_FIELDS, join_on=DRAFT_JOIN)

    def _series(self, team_a, team_b, on, **query):
        # Series can start early after a short preceding match, or finish on the
        # following UTC day. Keep the window tied
        # to its scheduled start, so a next-day rematch is not mixed into it.
        start = on.replace(tzinfo=UTC) if on.tzinfo is None else on.astimezone(UTC)
        lower = (start - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        upper = (start + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
        canonical_a, canonical_b = self._canonical_team(team_a), self._canonical_team(team_b)
        if canonical_a == canonical_b:
            raise RuntimeError("Leaguepedia fixture resolves both teams to the same identity")
        a, b = self._quote(canonical_a), self._quote(canonical_b)
        rows = self._query(
            action="cargoquery", format="json", limit=10, **query,
            where=(f'SG.DateTime_UTC >= "{lower}" AND SG.DateTime_UTC <= "{upper}" '
                   f'AND ((SG.Team1={a} AND SG.Team2={b}) OR (SG.Team1={b} AND SG.Team2={a}))'),
            order_by="SG.N_GameInMatch ASC",
        )
        if "cargoquery" not in rows:
            raise RuntimeError("Leaguepedia response is missing Cargo results")
        games = self._parse_games(rows["cargoquery"])
        # Cargo matches names case-insensitively, so map rows back the same way.
        names = {canonical_a.casefold(): team_a, canonical_b.casefold(): team_b}
        for game in games:
            team1, team2 = names.get(game.team1.casefold()), names.get(game.team2.casefold())
            if team1 is None or team2 is None:
                raise RuntimeError("Leaguepedia returned a game for an unexpected team")
            game.team1, game.team2 = team1, team2
        if len({g.game_in_series for g in games}) != len(games):
            raise RuntimeError("Leaguepedia returned ambiguous games for the fixture")
        return games or None

    @staticmethod
    def _parse_games(rows: list[dict]) -> list[LeaguepediaGame]:
        out = []
        for row in rows:
            r = row["title"]
            if r["WinTeam"] not in (r["Team1"], r["Team2"]):
                raise RuntimeError("Leaguepedia game has no recognized winner")
            out.append(LeaguepediaGame(
                team1=r["Team1"], team2=r["Team2"], winner=1 if r["WinTeam"] == r["Team1"] else 2,
                game_in_series=int(r["N GameInMatch"]),
                played_at=datetime.fromisoformat(r["DateTime UTC"]),
                team1_bans=[b for b in (r.get("Team1Bans") or "").split(",") if b],
                team2_bans=[b for b in (r.get("Team2Bans") or "").split(",") if b],
                draft=LeaguepediaClient._parse_draft(r) if "PBTeam1" in r else None,
                length_s=round(float(r["Gamelength"]) * 60) if r.get("Gamelength") else None,
            ))
        return out

    @staticmethod
    def _parse_draft(r: dict) -> LeaguepediaDraft | None:
        """Pick order from a joined PicksAndBansS7 row, or None when it is missing, partial or its sides
        do not match the scoreboard (an unjoined row comes back with empty PB fields)."""
        if (r.get("PBTeam1") or "").casefold() != r["Team1"].casefold() or \
                (r.get("PBTeam2") or "").casefold() != r["Team2"].casefold():
            return None
        picks = {t: [(r.get(f"Team{t}Pick{i}") or "").strip() for i in range(1, 6)] for t in (1, 2)}
        if not all(all(p) for p in picks.values()):
            return None
        roles = {t: [ROLES.get((r.get(f"Team{t}Role{i}") or "").strip().casefold()) for i in range(1, 6)]
                 for t in (1, 2)}
        return LeaguepediaDraft(picks[1], picks[2], roles[1], roles[2])


def make_source(settings: Settings) -> LeaguepediaSource:
    if settings.leaguepedia_mode == "live":
        return LeaguepediaClient(settings)
    return MockLeaguepedia()
