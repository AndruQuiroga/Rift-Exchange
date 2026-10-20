"""Champion grid: price any champion for one game, on demand (docs/spec builders plan, Markets & pricing).

The grid can't pre-create every champion x scope x game, so it reads indicative prices from tournament
pick rates and creates a market only when someone taps a champion. Every market is still an ordinary
`champion_picked` market: same template key for everyone, versioned odds, frozen at acceptance.

Model (EXPERIMENTAL): P(picked in a game) is the champion's share of verified Worlds games it appeared in.
Fearless removes earlier picks from the pool, so the remaining champions' rates are scaled up by the share
of picks the burned champions used to take. Team rates shrink each team's own record toward half the
global rate (a team makes five of the ten picks), because a team has only a handful of games.
"""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from rift.config import Settings
from rift.domain.pricing import price
from rift.markets import MarketSpec, OutcomeSpec, champion_label, upsert_market
from rift.models import Fixture, Game, Market, Season, Team

SCOPES = ("picked", "A", "B")
TEAM_PRIOR_GAMES = 6  # pseudo-games of the global rate added to each team's own record
MAX_P = 0.95


class DraftError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Rates:
    games: int
    picked: dict[str, float]  # champion -> share of games it was picked in (either team)
    role: dict[str, str]  # champion -> most common role
    team_games: Counter
    team_picks: dict[str, Counter]  # team_id -> champion -> games picked by that team


def tournament_rates(session: Session, season: Season) -> Rates:
    rows = session.execute(
        select(Game.stats).join(Fixture, Fixture.id == Game.fixture_id)
        .where(Fixture.season_id == season.id, Game.stats_complete.is_(True))
    ).scalars().all()
    picked, roles = Counter(), {}
    team_games, team_picks = Counter(), {}
    for stats in rows:
        players = stats["players"]
        for champ in {p["champion"] for p in players}:
            picked[champ] += 1
        for p in players:
            roles.setdefault(p["champion"], Counter())[p["role"]] += 1
            if p.get("team_id"):
                team_picks.setdefault(p["team_id"], Counter())[p["champion"]] += 1
        for team_id in {p.get("team_id") for p in players if p.get("team_id")}:
            team_games[team_id] += 1
    n = len(rows)
    return Rates(games=n, picked={c: k / n for c, k in picked.items()} if n else {},
                 role={c: r.most_common(1)[0][0] for c, r in roles.items()},
                 team_games=team_games, team_picks=team_picks)


def burned(session: Session, fixture: Fixture, game_index: int) -> list[str]:
    """Champions already played in earlier games of this series (Fearless: unavailable now)."""
    games = session.execute(select(Game).where(Game.fixture_id == fixture.id, Game.game_index < game_index,
                                               Game.stats_complete.is_(True))).scalars().all()
    return sorted({p["champion"] for g in games for p in g.stats["players"]})


def game_market_window(session: Session, fixture: Fixture, game_index: int) -> Market | None:
    """The market whose lock defines this game's betting window: series winner for Game 1, else that
    game's winner market, which opens when the previous game ends."""
    markets = session.execute(select(Market).where(Market.fixture_id == fixture.id)).scalars().all()
    if game_index == 1:
        return next((m for m in markets if m.kind == "series_winner"), None)
    return next((m for m in markets if m.kind == "game_winner" and m.params.get("game_index") == game_index), None)


def probabilities(rates: Rates, champ: str, fixture: Fixture, gone: list[str]) -> dict[str, float]:
    if champ in gone or champ not in rates.picked:
        return {}
    # Each game has ten picks; the burned champions' expected share of them moves to the rest.
    burned_share = sum(rates.picked.get(c, 0.0) for c in gone) / 10
    lift = 1 / max(1 - burned_share, 0.5)
    base = rates.picked[champ]
    out = {"picked": min(base * lift, MAX_P)}
    for side, team_id in (("A", fixture.team_a_id), ("B", fixture.team_b_id)):
        tid = str(team_id)
        own = rates.team_picks.get(tid, Counter())[champ]
        n = rates.team_games[tid]
        p = (own + TEAM_PRIOR_GAMES * base / 2) / (n + TEAM_PRIOR_GAMES)
        out[side] = min(p * lift, MAX_P)
    return out


def grid(session: Session, season: Season, fixture: Fixture, game_index: int, settings: Settings) -> dict:
    if not 1 <= game_index <= fixture.best_of:
        raise DraftError("BAD_GAME", f"Game {game_index} is not part of this Bo{fixture.best_of}.")
    window = game_market_window(session, fixture, game_index)
    rates = tournament_rates(session, season)
    gone = burned(session, fixture, game_index)
    champs = []
    for champ in sorted(rates.picked, key=lambda c: -rates.picked[c]):
        probs = probabilities(rates, champ, fixture, gone)
        if not probs:
            continue
        odds = {k: price(p, min_probability=Decimal(settings.min_probability),
                         max_odds=Decimal(settings.max_decimal_odds)) for k, p in probs.items()}
        champs.append({"champion": champ, "label": champion_label(champ), "role": rates.role.get(champ),
                       "odds": {k: str(v) if v is not None else None for k, v in odds.items()}})
    return {
        "game_index": game_index,
        "open": window is not None and window.state == "OPEN",
        "close_at": window.close_at.isoformat() if window else None,
        "games_observed": rates.games,
        "burned": [{"champion": c, "label": champion_label(c)} for c in gone],
        "champions": champs,
    }


def ensure_market(session: Session, season: Season, fixture: Fixture, game_index: int, champ: str, scope: str,
                  settings: Settings, now) -> Market:
    """Create (or re-price) the market for one tapped champion. Same template key for every player."""
    if scope not in SCOPES:
        raise DraftError("BAD_SCOPE", "Scope must be picked, A or B.")
    window = game_market_window(session, fixture, game_index)
    if window is None or window.state != "OPEN" or window.close_at <= now:
        raise DraftError("NOT_OPEN", f"Game {game_index} draft picks are not open.")
    rates = tournament_rates(session, season)
    probs = probabilities(rates, champ, fixture, burned(session, fixture, game_index))
    if scope not in probs:
        raise DraftError("NOT_OFFERED", "That champion is not offered for this game.")
    p = probs[scope]
    label = champion_label(champ)
    if scope == "picked":
        title, who = f"{label} picked in Game {game_index}", "either team"
    else:
        team = session.get(Team, fixture.team_a_id if scope == "A" else fixture.team_b_id)
        title, who = f"{team.code} pick {label} in Game {game_index}", team.name
    spec = MarketSpec(
        f"champion_pick:{fixture.provider_id}:{game_index}:{champ}:{scope}", "champion_picked", "GAME", "DRAFT",
        title,
        f"Yes if {label} is picked by {who} in Game {game_index}. Fearless Draft: a champion played earlier in "
        f"the series can't be picked again. Settles from the game's verified draft; void if Game {game_index} "
        "is not played.",
        window.close_at, "pick_rate_team_fearless_v1", "EXPERIMENTAL",
        [OutcomeSpec("YES", "Yes", p), OutcomeSpec("NO", "No", 1 - p)],
        {"champion": champ, "game_index": game_index, **({"side": scope} if scope != "picked" else {})})
    market = upsert_market(session, season, fixture, spec, settings, now)
    if market is None:
        raise DraftError("NOT_OPEN", f"Game {game_index} draft picks are not open.")
    return market
