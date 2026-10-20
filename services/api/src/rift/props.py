"""Players & game markets: objectives, lane duels and any-line kill totals (builders plan, phase 3).

All of these settle from the per-game livestats timeline (rift.timeline) and HOLD until it is complete.
Objective markets open with each game alongside its winner market. Duels and alternative kill lines are
created on demand when someone taps them, like champion markets: one template key per game and choice,
shared by every player.

Models (EXPERIMENTAL) use what this Worlds has shown so far:
- First blood / first tower: how often the game's winner also took that first, mixed with the Elo game
  probability. Dragon type, soul and early Baron: observed frequencies with add-one smoothing.
- Duels: each player's tournament average and spread for the stat, shrunk toward their role's average,
  compared with a normal approximation. Exact ties void, so integer stats are priced on P(win | no tie).
"""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from rift.config import Settings
from rift.domain.pricing import price
from rift.markets import MIN_DRAFT_GAMES, MarketSpec, OutcomeSpec, TournamentStats, _nb_cdf, upsert_market
from rift.models import Fixture, Game, Market, Season, Team

DRAGONS = ("infernal", "ocean", "mountain", "cloud", "hextech", "chemtech")
EARLY_BARON_S = 25 * 60
ROLES = ("top", "jungle", "mid", "bottom", "support")
STATS = {
    "kills": ("More kills", True),
    "cs15": ("More CS at 15:00", True),
    "damage": ("Higher damage share", False),
}
SHRINK_GAMES = 3  # pseudo-games of the role average added to each player's own record
OBJECTIVE_KINDS = ("first_blood", "first_tower", "first_dragon_type", "baron_before", "dragon_soul")
KINDS = (*OBJECTIVE_KINDS, "lane_duel")
LINES = [x + 0.5 for x in range(14, 45)]


class PropsError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# ------------------------------------------------------------------ tournament data


@dataclass
class TimelineData:
    games: int = 0
    winner_took_first: dict[str, float] = field(default_factory=dict)  # "blood"/"tower" -> share
    first_dragon: Counter = field(default_factory=Counter)
    soul: Counter = field(default_factory=Counter)  # type or "none"
    early_baron: int = 0
    player: dict[str, dict[str, list[float]]] = field(default_factory=dict)  # player_id -> stat -> values
    role: dict[str, dict[str, list[float]]] = field(default_factory=dict)  # role -> stat -> values


def _complete_games(session: Session, season: Season) -> list[Game]:
    return list(session.execute(
        select(Game).join(Fixture, Fixture.id == Game.fixture_id)
        .where(Fixture.season_id == season.id, Game.timeline_complete.is_(True))
    ).scalars())


def player_lines(game: Game) -> dict[str, dict]:
    """player_id -> {role, team_id, name, kills, cs15, damage} for one completed game (None where unknown)."""
    tl = game.timeline or {}
    team_of = {"blue": game.blue_team_id, "red": game.red_team_id}
    at15 = ((tl.get("at_15") or {}).get("players")) or {}
    out = {}
    for pid, p in (tl.get("participants") or {}).items():
        final = (tl.get("final") or {}).get(pid) or {}
        out[str(p.get("player_id") or p.get("name"))] = {
            "role": p.get("role"), "name": p.get("name"), "team_id": str(team_of.get(p.get("side")) or ""),
            "kills": final.get("kills"), "cs15": (at15.get(pid) or {}).get("cs"), "damage": final.get("damage_share"),
        }
    return out


def timeline_data(session: Session, season: Season) -> TimelineData:
    data = TimelineData()
    took = Counter()
    for g in _complete_games(session, season):
        tl = g.timeline or {}
        firsts = tl.get("firsts") or {}
        data.games += 1
        for what in ("blood", "tower"):
            first = firsts.get(what)
            if first and g.winner_team_id is not None:
                took[(what, "n")] += 1
                took[(what, "w")] += int(first.get("team_id") == str(g.winner_team_id))
        if firsts.get("dragon"):
            data.first_dragon[firsts["dragon"].get("type")] += 1
        data.soul[tl.get("soul") or "none"] += 1
        baron = firsts.get("baron")
        data.early_baron += int(bool(baron) and baron["at_s"] < EARLY_BARON_S)
        for pid, line in player_lines(g).items():
            for stat in STATS:
                if line[stat] is None or not line["role"]:
                    continue
                data.player.setdefault(pid, defaultdict(list))[stat].append(float(line[stat]))
                data.role.setdefault(line["role"], defaultdict(list))[stat].append(float(line[stat]))
    for what in ("blood", "tower"):
        n = took[(what, "n")]
        # Shrink toward a coin flip; first objectives only lean slightly toward the eventual winner.
        data.winner_took_first[what] = (took[(what, "w")] + 5) / (n + 10)
    return data


# ------------------------------------------------------------------ objectives (open with each game)


def _smoothed(counts: Counter, keys) -> dict[str, float]:
    total = sum(counts[k] for k in keys) + len(keys)
    return {k: (counts[k] + 1) / total for k in keys}


def objective_specs(fixture: Fixture, idx: int, a: Team, b: Team, q: float, data: TimelineData,
                    close_at: datetime, when: str) -> list[MarketSpec]:
    if data.games < MIN_DRAFT_GAMES:
        return []
    key, specs = fixture.provider_id, []
    void = f"Settles from the game's live data; void if Game {idx} is not played."
    for kind, what, title in (("first_blood", "blood", "First blood"), ("first_tower", "tower", "First tower")):
        w = data.winner_took_first[what]
        p = q * w + (1 - q) * (1 - w)
        specs.append(MarketSpec(
            f"{kind}:{key}:{idx}", kind, "GAME", "OBJECTIVES", f"Game {idx} {title.lower()}",
            f"Team that gets {title.lower()} in Game {idx}. {when} {void}",
            close_at, "timeline_rates_v1", "EXPERIMENTAL",
            [OutcomeSpec("A", a.name, p), OutcomeSpec("B", b.name, 1 - p)], {"game_index": idx}))
    dragon = _smoothed(data.first_dragon, DRAGONS)
    specs.append(MarketSpec(
        f"first_dragon_type:{key}:{idx}", "first_dragon_type", "GAME", "OBJECTIVES", f"Game {idx} first dragon",
        f"Element of the first dragon taken in Game {idx}, by either team. Void if no dragon is taken. {when} {void}",
        close_at, "timeline_rates_v1", "EXPERIMENTAL",
        [OutcomeSpec(t, t.capitalize(), dragon[t]) for t in DRAGONS], {"game_index": idx}))
    early = (data.early_baron + 1) / (data.games + 2)
    specs.append(MarketSpec(
        f"baron_before:{key}:{idx}", "baron_before", "GAME", "OBJECTIVES", f"Game {idx} Baron before 25:00",
        f"Yes if either team takes Baron before 25:00 of game time in Game {idx}. No if the first Baron comes "
        f"later or never. {when} {void}",
        close_at, "timeline_rates_v1", "EXPERIMENTAL",
        [OutcomeSpec("YES", "Yes", early), OutcomeSpec("NO", "No", 1 - early)], {"game_index": idx}))
    soul = _smoothed(data.soul, (*DRAGONS, "none"))
    specs.append(MarketSpec(
        f"dragon_soul:{key}:{idx}", "dragon_soul", "GAME", "OBJECTIVES", f"Game {idx} dragon soul",
        f"Element of the dragon soul claimed in Game {idx}, or No soul if nobody claims one. {when} {void}",
        close_at, "timeline_rates_v1", "EXPERIMENTAL",
        [OutcomeSpec(t.upper() if t == "none" else t, "No soul" if t == "none" else t.capitalize(), soul[t])
         for t in (*DRAGONS, "none")], {"game_index": idx}))
    return specs


# ------------------------------------------------------------------ lane duels (on demand)


def lineups(session: Session, fixture: Fixture) -> dict[str, dict[str, dict]]:
    """side ("A"/"B") -> role -> {player_id, name}: each team's lineup from its most recent played game."""
    out: dict[str, dict[str, dict]] = {}
    for side, team_id in (("A", fixture.team_a_id), ("B", fixture.team_b_id)):
        games = session.execute(
            select(Game).where(Game.timeline.is_not(None), (Game.blue_team_id == team_id) | (Game.red_team_id == team_id))
            .order_by(Game.started_at.desc().nullslast()).limit(3)
        ).scalars().all()
        for g in games:
            lines = {pid: line for pid, line in player_lines(g).items() if line["team_id"] == str(team_id)}
            roles = {line["role"]: {"player_id": pid, "name": line["name"]} for pid, line in lines.items()}
            if set(roles) >= set(ROLES):
                out[side] = roles
                break
        if side not in out:  # hasn't played at Worlds yet: its latest regional starting five
            team = session.get(Team, team_id)
            players = (team.lineup or {}).get("players") or {}
            if set(players) >= set(ROLES):
                out[side] = players
    return out


def _player_estimate(data: TimelineData, pid: str, role: str, stat: str) -> tuple[float, float] | None:
    role_vals = data.role.get(role, {}).get(stat) or []
    if len(role_vals) < 5:
        return None
    rmean = sum(role_vals) / len(role_vals)
    rvar = sum((v - rmean) ** 2 for v in role_vals) / (len(role_vals) - 1)
    own = data.player.get(pid, {}).get(stat) or []
    mean = (sum(own) + SHRINK_GAMES * rmean) / (len(own) + SHRINK_GAMES)
    # A floor keeps a short, uniform sample from pricing near-certainties: one kill or 0.01 damage share.
    return mean, max(rvar, 1.0 if STATS[stat][1] else 1e-4)


def duel_probability(data: TimelineData, a: dict, b: dict, role: str, stat: str) -> float | None:
    """P(A beats B | no exact tie). None when there isn't enough data to price it."""
    ea, eb = _player_estimate(data, a["player_id"], role, stat), _player_estimate(data, b["player_id"], role, stat)
    if ea is None or eb is None:
        return None
    mu, sd = ea[0] - eb[0], math.sqrt(ea[1] + eb[1])

    def cdf(x: float) -> float:
        return 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))

    if STATS[stat][1]:  # whole numbers: a difference within half a unit is a tie, and ties void
        win, lose = 1 - cdf(0.5), cdf(-0.5)
    else:
        win, lose = 1 - cdf(0.0), cdf(0.0)
    return win / (win + lose) if win + lose > 1e-9 else 0.5


def duels(session: Session, season: Season, fixture: Fixture, game_index: int, settings: Settings) -> dict:
    from rift.draft import game_market_window

    window = game_market_window(session, fixture, game_index)
    lineup = lineups(session, fixture)
    data = timeline_data(session, season)
    rows = []
    for role in ROLES:
        a, b = lineup.get("A", {}).get(role), lineup.get("B", {}).get(role)
        if not a or not b:
            continue
        odds = {}
        for stat in STATS:
            p = duel_probability(data, a, b, role, stat)
            pa = _px(p, settings)
            pb = _px(1 - p, settings) if p is not None else None
            odds[stat] = {"A": pa, "B": pb}
        rows.append({"role": role, "a": a, "b": b, "odds": odds})
    return {"game_index": game_index, "open": window is not None and window.state == "OPEN",
            "close_at": window.close_at.isoformat() if window else None,
            "stats": [{"id": k, "label": v[0]} for k, v in STATS.items()], "duels": rows}


def _px(p: float | None, settings: Settings) -> str | None:
    if p is None:
        return None
    o = price(p, min_probability=Decimal(settings.min_probability), max_odds=Decimal(settings.max_decimal_odds))
    return str(o) if o is not None else None


def _open_window(session: Session, fixture: Fixture, game_index: int, now: datetime) -> Market:
    from rift.draft import game_market_window

    window = game_market_window(session, fixture, game_index)
    if window is None or window.state != "OPEN" or window.close_at <= now:
        raise PropsError("NOT_OPEN", f"Game {game_index} picks are not open.")
    return window


def ensure_duel(session: Session, season: Season, fixture: Fixture, game_index: int, role: str, stat: str,
                settings: Settings, now: datetime) -> Market:
    if role not in ROLES or stat not in STATS:
        raise PropsError("BAD_DUEL", "Unknown role or stat.")
    window = _open_window(session, fixture, game_index, now)
    lineup = lineups(session, fixture)
    a, b = lineup.get("A", {}).get(role), lineup.get("B", {}).get(role)
    if not a or not b:
        raise PropsError("NO_LINEUP", "Lineups for this duel are not known yet.")
    p = duel_probability(timeline_data(session, season), a, b, role, stat)
    if p is None:
        raise PropsError("NOT_OFFERED", "Not enough data to price this duel yet.")
    label = STATS[stat][0]
    spec = MarketSpec(
        f"lane_duel:{fixture.provider_id}:{game_index}:{role}:{stat}:{a['player_id']}:{b['player_id']}",
        "lane_duel", "GAME", "PLAYERS", f"Game {game_index} {role}: {a['name']} vs {b['name']}",
        f"{label}: {a['name']} or {b['name']} in Game {game_index}. An exact tie is void. Void if either player "
        f"doesn't play Game {game_index}{', or if the game ends before 15:00' if stat == 'cs15' else ''}. Settles "
        "from the game's live data.",
        window.close_at, "player_normal_v1", "EXPERIMENTAL",
        [OutcomeSpec("A", a["name"], p), OutcomeSpec("B", b["name"], 1 - p)],
        {"game_index": game_index, "role": role, "stat": stat, "a_player": a["player_id"], "b_player": b["player_id"]})
    market = upsert_market(session, season, fixture, spec, settings, now)
    if market is None:
        raise PropsError("NOT_OPEN", f"Game {game_index} picks are not open.")
    return market


# ------------------------------------------------------------------ kill lines (on demand)


def kill_lines(session: Session, fixture: Fixture, game_index: int, stats: TournamentStats, settings: Settings) -> dict:
    from rift.draft import game_market_window

    window = game_market_window(session, fixture, game_index)
    lines = []
    if stats.games >= MIN_DRAFT_GAMES:
        mean = sum(stats.kill_totals) / len(stats.kill_totals)
        var = sum((k - mean) ** 2 for k in stats.kill_totals) / max(len(stats.kill_totals) - 1, 1)
        for line in LINES:
            under = _nb_cdf(int(line), mean, var)
            over_px, under_px = _px(1 - under, settings), _px(under, settings)
            if over_px and under_px:
                lines.append({"line": str(line), "over": over_px, "under": under_px})
    return {"game_index": game_index, "open": window is not None and window.state == "OPEN",
            "close_at": window.close_at.isoformat() if window else None,
            "typical": str(math.floor(sum(stats.kill_totals) / len(stats.kill_totals)) + 0.5) if stats.kill_totals else None,
            "lines": lines}


def ensure_kill_line(session: Session, season: Season, fixture: Fixture, game_index: int, line: str,
                     stats: TournamentStats, settings: Settings, now: datetime) -> Market:
    from rift.markets import game_specs

    if float(line) not in LINES:
        raise PropsError("BAD_LINE", "Lines run from 14.5 to 44.5 kills.")
    window = _open_window(session, fixture, game_index, now)
    a, b = session.get(Team, fixture.team_a_id), session.get(Team, fixture.team_b_id)
    spec = next((s for s in game_specs(fixture, game_index, a, b, 0.5, stats, window.close_at, "EXPERIMENTAL",
                                       str(float(line))) if s.kind == "total_kills_game"), None)
    if spec is None or any(_px(o.probability, settings) is None for o in spec.outcomes):
        raise PropsError("NOT_OFFERED", "That kill line isn't offered.")
    market = upsert_market(session, season, fixture, spec, settings, now)
    if market is None:
        raise PropsError("NOT_OPEN", f"Game {game_index} picks are not open.")
    return market


# ------------------------------------------------------------------ grading


def grade(market: Market, fixture: Fixture, game: Game | None):
    from rift.settlement import PENDING, Grade

    idx = market.params["game_index"]
    ev = {"fixture": fixture.provider_id, "game_index": idx}
    if game is None or game.state in ("unstarted", "inProgress"):
        if fixture.status == "COMPLETED" or (game is not None and game.state == "unneeded"):
            return Grade("VOID", reason=f"Game {idx} was not played", evidence=ev)
        return PENDING
    if game.state == "unneeded":
        return Grade("VOID", reason=f"Game {idx} was not played", evidence=ev)
    if not game.timeline_complete:
        return Grade("HOLD", reason=f"Awaiting Game {idx} live data", evidence=ev)
    tl = game.timeline or {}
    firsts = tl.get("firsts") or {}
    side_code = {str(fixture.team_a_id): "A", str(fixture.team_b_id): "B"}
    kind = market.kind

    if kind in ("first_blood", "first_tower"):
        first = firsts.get("blood" if kind == "first_blood" else "tower")
        code = side_code.get((first or {}).get("team_id") or "")
        if code is None:
            return Grade("VOID", reason="No verified first for this game", evidence=ev)
        return Grade("RESULT", [code], f"{kind.replace('_', ' ').capitalize()} confirmed", {**ev, "at_s": first["at_s"]})
    if kind == "first_dragon_type":
        dragon = firsts.get("dragon")
        if not dragon or dragon.get("type") not in DRAGONS:
            return Grade("VOID", reason="No elemental first dragon", evidence=ev)
        return Grade("RESULT", [dragon["type"]], "First dragon confirmed", {**ev, "at_s": dragon["at_s"]})
    if kind == "baron_before":
        baron = firsts.get("baron")
        early = bool(baron) and baron["at_s"] < EARLY_BARON_S
        return Grade("RESULT", ["YES" if early else "NO"], "Baron timing confirmed",
                     {**ev, "at_s": baron["at_s"] if baron else None})
    if kind == "dragon_soul":
        soul = tl.get("soul")
        if soul is not None and soul not in DRAGONS:
            return Grade("HOLD", reason=f"Unknown soul type {soul}", evidence=ev)
        return Grade("RESULT", [soul or "NONE"], "Dragon soul confirmed", {**ev, "soul": soul})
    if kind == "lane_duel":
        lines = player_lines(game)
        a, b = lines.get(market.params["a_player"]), lines.get(market.params["b_player"])
        if a is None or b is None:
            return Grade("VOID", reason="A dueling player did not play this game", evidence=ev)
        stat = market.params["stat"]
        va, vb = a[stat], b[stat]
        if va is None or vb is None:
            return Grade("VOID", reason="Stat not available for this game (e.g. it ended before 15:00)", evidence=ev)
        if va == vb:
            return Grade("VOID", reason="Exact tie (void rule)", evidence={**ev, "values": [va, vb]})
        return Grade("RESULT", ["A" if va > vb else "B"], "Player stats confirmed", {**ev, "values": [va, vb]})
    return Grade("HOLD", reason=f"No grader for {kind}")
