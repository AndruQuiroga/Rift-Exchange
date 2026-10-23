"""Champion grid: price any champion for one game, on demand (docs/spec builders plan, Markets & pricing).

The grid can't pre-create every champion x scope x game, so it reads indicative prices from tournament
rates and creates a market only when someone taps a champion. Every market is an ordinary YES/NO market:
same template key for everyone, versioned odds, frozen at acceptance.

Scopes: `picked` (either team), `A`/`B` (that team, optionally in one role), `banned` (either team bans it)
and `first` (the game's first pick). Picks settle from livestats; bans and pick order only exist where
Leaguepedia data was stored (rift.ingest.sync_drafts), so those scopes are offered only once at least
MIN_DRAFT_RECORDS games have it: with fewer, a rate is a guess and the scope is withheld (null odds).

Model (EXPERIMENTAL): P(picked in a game) is the champion's share of verified Worlds games it appeared in.
Fearless removes earlier picks from the pool, so the remaining champions' rates are scaled up by the share
of picks (or bans) the burned champions used to take; first-pick shares are renormalised over the champions
left. Team rates shrink each team's own record toward half the global rate (a team makes five of the ten
picks), because a team has only a handful of games; role rates do the same per role.

Burned champions are not offered in any scope, including `banned`: they can't be picked, so nobody spends
a ban on them and a "banned" market on one is a certain NO.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from rift.champions import champion_key
from rift.config import Settings
from rift.display import team_name
from rift.domain.pricing import price
from rift.markets import MarketSpec, OutcomeSpec, champion_label, next_game, upsert_market
from rift.models import Fixture, Game, Market, Season, Team
from rift.timeline import burned_champions

SCOPES = ("picked", "A", "B", "banned", "first")
ROLES = ("top", "jungle", "mid", "bottom", "support")
ROLE_LABEL = {"top": "top", "jungle": "jungle", "mid": "mid", "bottom": "bot lane", "support": "support"}
TEAM_PRIOR_GAMES = 6  # pseudo-games of the global rate added to each team's own record
MIN_DRAFT_RECORDS = 10  # games with Leaguepedia bans / pick order before those scopes are priced
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
    role_games: dict[str, Counter] = field(default_factory=dict)  # champion -> role -> games played there
    team_roles: dict[str, Counter] = field(default_factory=dict)  # team_id -> (champion, role) -> games
    ban_games: int = 0  # games with stored bans
    banned: dict[str, float] = field(default_factory=dict)  # champion -> share of those games it was banned
    first_games: int = 0  # games with stored pick order
    first: dict[str, float] = field(default_factory=dict)  # champion -> share of those games it went first
    names: dict[str, str] = field(default_factory=dict)  # champion_key -> the name used above

    def name(self, champ: str) -> str | None:
        return self.names.get(champion_key(champ))


def tournament_rates(session: Session, season: Season) -> Rates:
    from rift.reference import observations
    rows = [(g.stats, g.stats_complete, g.bans, weight) for g, weight in observations(session, season)]
    names: dict[str, str] = {}

    def canon(champ: str) -> str:
        # Livestats spellings come first (stats rows are folded before bans), so they win.
        return names.setdefault(champion_key(champ), champ)

    picked, roles, role_games = Counter(), {}, {}
    team_games, team_picks, team_roles = Counter(), {}, {}
    n = 0
    for stats, complete, _bans, weight in rows:
        if not complete or not stats:
            continue
        n += weight
        players = [dict(p, champion=canon(p["champion"])) for p in stats["players"]]
        for champ in {p["champion"] for p in players}:
            picked[champ] += weight
        for p in players:
            roles.setdefault(p["champion"], Counter())[p["role"]] += weight
            if p.get("team_id"):
                team_picks.setdefault(p["team_id"], Counter())[p["champion"]] += weight
                team_roles.setdefault(p["team_id"], Counter())[(p["champion"], p["role"])] += weight
        for champ, role in {(p["champion"], p["role"]) for p in players}:
            role_games.setdefault(champ, Counter())[role] += weight
        for team_id in {p.get("team_id") for p in players if p.get("team_id")}:
            team_games[team_id] += weight
    banned, first = Counter(), Counter()
    ban_games = first_games = 0
    for _stats, _complete, bans, weight in rows:
        if not bans or "blue" not in bans:
            continue
        ban_games += weight
        for champ in {canon(c) for c in bans["blue"] + bans["red"]}:
            banned[champ] += weight
        if bans.get("first_pick"):
            first_games += weight
            first[canon(bans["first_pick"])] += weight
    return Rates(games=n, picked={c: k / n for c, k in picked.items()} if n else {},
                 role={c: r.most_common(1)[0][0] for c, r in roles.items()},
                 team_games=team_games, team_picks=team_picks, role_games=role_games, team_roles=team_roles,
                 ban_games=ban_games, banned={c: k / ban_games for c, k in banned.items()} if ban_games else {},
                 first_games=first_games, first={c: k / first_games for c, k in first.items()} if first_games else {},
                 names=names)


# First pick is graded as blue side's first pick from Leaguepedia. That is unverified against real 2026
# drafts (a "first selection" rule would let red pick first), so the scope stays off until it is checked.
FIRST_PICK_VERIFIED = False


def offered_scopes(rates: Rates) -> list[str]:
    return ["picked", "A", "B"] + (["banned"] if rates.ban_games >= MIN_DRAFT_RECORDS else []) + (
        ["first"] if FIRST_PICK_VERIFIED and rates.first_games >= MIN_DRAFT_RECORDS else [])


def burned(session: Session, fixture: Fixture, game_index: int) -> list[str]:
    """Champions already played in earlier games of this series (Fearless: unavailable now)."""
    games = list(session.execute(select(Game).where(Game.fixture_id == fixture.id)).scalars())
    return sorted(burned_champions(games, fixture.best_of).get(game_index, []))


@dataclass
class DraftWindow:
    open: bool
    close_at: datetime | None


def draft_window(session: Session, fixture: Fixture, game_index: int, now: datetime) -> DraftWindow:
    """When this game's champion calls can be made: they close before its draft starts (D-026), unlike the
    winner markets that stay open through it. Game 1 closes at the series start (or once the series is live);
    Game N opens when Game N-1 ends and closes NEXT_GAME_WINDOW later, before Game N's draft."""
    if game_index == 1:
        return DraftWindow(fixture.status == "SCHEDULED" and now < fixture.scheduled_at, fixture.scheduled_at)
    games = list(session.execute(select(Game).where(Game.fixture_id == fixture.id)).scalars())
    nxt = next_game(fixture, games)
    if nxt is None or nxt[0] != game_index:
        return DraftWindow(False, None)
    return DraftWindow(now < nxt[1], nxt[1])


def probabilities(rates: Rates, champ: str, fixture: Fixture, gone: list[str]) -> dict:
    """Scope -> probability for one champion, plus "roles": {side: {role: p}}. Empty when not offered."""
    gone_keys = {champion_key(c) for c in gone}
    if champion_key(champ) in gone_keys:
        return {}
    gone = [rates.names.get(k, k) for k in gone_keys]
    out: dict = {}
    scopes = offered_scopes(rates)
    if champ in rates.picked:
        # Each game has ten picks; the burned champions' expected share of them moves to the rest.
        lift = 1 / max(1 - sum(rates.picked.get(c, 0.0) for c in gone) / 10, 0.5)
        base = rates.picked[champ]
        out["picked"] = min(base * lift, MAX_P)
        out["roles"] = {}
        for side, team_id in (("A", fixture.team_a_id), ("B", fixture.team_b_id)):
            tid = str(team_id)
            n = rates.team_games[tid]
            own = rates.team_picks.get(tid, Counter())[champ]
            out[side] = min((own + TEAM_PRIOR_GAMES * base / 2) / (n + TEAM_PRIOR_GAMES) * lift, MAX_P)
            roles = {}
            for role, k in rates.role_games.get(champ, Counter()).items():
                if role not in ROLES:
                    continue
                own_role = rates.team_roles.get(tid, Counter())[(champ, role)]
                p = (own_role + TEAM_PRIOR_GAMES * k / rates.games / 2) / (n + TEAM_PRIOR_GAMES)
                roles[role] = min(p * lift, MAX_P)
            out["roles"][side] = roles
    if "banned" in scopes and champ in rates.banned:
        lift = 1 / max(1 - sum(rates.banned.get(c, 0.0) for c in gone) / 10, 0.5)
        out["banned"] = min(rates.banned[champ] * lift, MAX_P)
    if "first" in scopes and champ in rates.first:
        left = 1 - sum(rates.first.get(c, 0.0) for c in gone)
        out["first"] = min(rates.first[champ] / max(left, 0.5), MAX_P)
    return out


def _odds(p: float | None, settings: Settings) -> str | None:
    if p is None:
        return None
    o = price(p, min_probability=Decimal(settings.min_probability), max_odds=Decimal(settings.max_decimal_odds))
    return str(o) if o is not None else None


def grid(session: Session, season: Season, fixture: Fixture, game_index: int, settings: Settings,
         now: datetime) -> dict:
    if not 1 <= game_index <= fixture.best_of:
        raise DraftError("BAD_GAME", f"Game {game_index} is not part of this Bo{fixture.best_of}.")
    window = draft_window(session, fixture, game_index, now)
    rates = tournament_rates(session, season)
    gone = burned(session, fixture, game_index)
    seen = set(rates.picked) | set(rates.banned) | set(rates.first)
    order = sorted(seen, key=lambda c: (-rates.picked.get(c, 0.0), -rates.banned.get(c, 0.0), c))
    # Once the game has loaded its draft is known: mark every champion picked or not (D-032 live calls).
    game = session.execute(select(Game).where(Game.fixture_id == fixture.id, Game.game_index == game_index)
                           ).scalar_one_or_none()
    participants = ((game.timeline or {}).get("participants") or {}) if game else {}
    drafted = {champion_key(p["champion"]) for p in participants.values() if p.get("champion")}
    champs = []
    for champ in order:
        probs = probabilities(rates, champ, fixture, gone)
        if not probs:
            continue
        roles = probs.get("roles", {})
        champs.append({
            "champion": champ, "label": champion_label(champ), "role": rates.role.get(champ),
            "picked": (champion_key(champ) in drafted) if drafted else None,
            "odds": {k: _odds(probs.get(k), settings) for k in SCOPES},
            "roles": {side: {r: _odds(p, settings) for r, p in sorted(roles.get(side, {}).items(),
                                                                       key=lambda kv: ROLES.index(kv[0]))}
                      for side in ("A", "B")},
        })
    return {
        "game_index": game_index,
        "open": window.open,
        "close_at": window.close_at.isoformat() if window.close_at else None,
        "games_observed": rates.games,
        "scopes": offered_scopes(rates),
        "burned": [{"champion": c, "label": champion_label(c)} for c in gone],
        "drafted": [{"champion": p["champion"], "label": champion_label(p["champion"]), "role": p.get("role")}
                    for p in participants.values() if p.get("champion")],
        "champions": champs,
    }


def ensure_market(session: Session, season: Season, fixture: Fixture, game_index: int, champ: str, scope: str,
                  settings: Settings, now, role: str | None = None) -> Market:
    """Create (or re-price) the market for one tapped champion. Same template key for every player."""
    if scope not in SCOPES:
        raise DraftError("BAD_SCOPE", "Scope must be picked, A, B, banned or first.")
    if role is not None and (scope not in ("A", "B") or role not in ROLES):
        raise DraftError("BAD_ROLE", "A role needs scope A or B and one of top, jungle, mid, bottom, support.")
    window = draft_window(session, fixture, game_index, now)
    if not window.open:
        raise DraftError("NOT_OPEN", f"Game {game_index} draft picks are not open.")
    rates = tournament_rates(session, season)
    champ = rates.name(champ) or champ
    probs = probabilities(rates, champ, fixture, burned(session, fixture, game_index))
    p = probs.get("roles", {}).get(scope, {}).get(role) if role else probs.get(scope)
    if p is None:
        raise DraftError("NOT_OFFERED", "That champion is not offered for this game.")
    label, g = champion_label(champ), game_index
    params: dict = {"champion": champ, "game_index": g}
    key = f"{fixture.provider_id}:{g}:{champ}"
    if scope == "banned":
        kind, model, template = "champion_banned", "ban_rate_fearless_v1", f"champion_ban:{key}"
        title = f"{label} banned in Game {g}"
        rules = (f"Yes if either team bans {label} in Game {g}. Settles from the game's published draft record "
                 f"(Leaguepedia); held until it appears and void if it does not within "
                 f"{settings.hold_void_after_hours} hours, or if Game {g} is not played.")
    elif scope == "first":
        kind, model, template = "champion_first_pick", "first_pick_share_fearless_v1", f"champion_first_pick:{key}"
        title = f"{label} first pick in Game {g}"
        rules = (f"Yes if {label} is the first champion picked in Game {g} (blue side's first pick). Settles "
                 "from the game's published pick order (Leaguepedia); held until it appears and void if it does "
                 f"not within {settings.hold_void_after_hours} hours, or if Game {g} is not played.")
    else:
        kind, template = "champion_picked", f"champion_pick:{key}:{scope}" + (f":{role}" if role else "")
        model = "pick_rate_team_role_fearless_v1" if role else "pick_rate_team_fearless_v1"
        if scope == "picked":
            title, who = f"{label} picked in Game {g}", "either team"
        else:
            team = session.get(Team, fixture.team_a_id if scope == "A" else fixture.team_b_id)
            title, who = (f"{team.code} play {label} {ROLE_LABEL[role]} in Game {g}" if role else
                          f"{team.code} pick {label} in Game {g}"), team_name(team.code, team.name)
            params["side"] = scope
            if role:
                params["role"] = role
        where = f" in the {ROLE_LABEL[role]} role" if role else ""
        rules = (f"Yes if {label} is picked by {who}{where} in Game {g}. Fearless Draft: a champion played earlier "
                 f"in the series can't be picked again. Settles from the game's verified draft; void if Game {g} "
                 "is not played.")
    rules = f"{rules} Closes before the Game {g} draft."
    spec = MarketSpec(template, kind, "GAME", "DRAFT", title, rules, window.close_at, model, "EXPERIMENTAL",
                      [OutcomeSpec("YES", "Yes", p), OutcomeSpec("NO", "No", 1 - p)], params)
    market = upsert_market(session, season, fixture, spec, settings, now)
    if market is None:
        raise DraftError("NOT_OPEN", f"Game {game_index} draft picks are not open.")
    return market
