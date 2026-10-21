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
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from rift.config import Settings
from rift.display import player_name, team_name
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
# Offered for new games (D-023). First dragon element and dragon soul are no longer offered; existing ones
# still lock and settle from the timeline like the rest.
OFFERED_OBJECTIVES = ("first_blood", "first_tower", "baron_before")
RETIRED_OBJECTIVES = tuple(k for k in OBJECTIVE_KINDS if k not in OFFERED_OBJECTIVES)
KINDS = (*OBJECTIVE_KINDS, "lane_duel")
LINES = [x + 0.5 for x in range(14, 45)]
# Kill lines stay clear of what the first three minutes have already settled: at least 5 kills above the
# game's kill count so far (D-024).
KILL_LINE_FLOOR = LINES[0]
KILL_LINE_MARGIN = 5


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
    reference_samples: list[tuple[str | None, str, str | None, float, float]] = field(default_factory=list)
    champion_samples: list[tuple[str, str, str, float, float]] = field(default_factory=list)



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
        champions = {str(p.get("player_id") or p.get("name")): p.get("champion")
                     for p in (tl.get("participants") or {}).values()}
        for pid, line in player_lines(g).items():
            for stat in STATS:
                if line[stat] is None or not line["role"]:
                    continue
                data.player.setdefault(pid, defaultdict(list))[stat].append(float(line[stat]))
                data.role.setdefault(line["role"], defaultdict(list))[stat].append(float(line[stat]))
                if champions.get(pid):
                    data.champion_samples.append((line["role"], champions[pid], stat, float(line[stat]), 1.0))
    for what in ("blood", "tower"):
        n = took[(what, "n")]
        # Shrink toward a coin flip; first objectives only lean slightly toward the eventual winner.
        data.winner_took_first[what] = (took[(what, "w")] + 5) / (n + 10)
    # Historical feed finals support kills only. They do not establish objective events,
    # damage share or CS15; missing telemetry must never become a zero or "no soul".
    from rift.reference import observations
    for g, weight in observations(session, season):
        if isinstance(g, Game):
            continue
        for p in g.stats.get("players", []):
            role, pid, value = p.get("role"), p.get("player_id"), p.get("kills")
            if role not in ROLES or value is None:
                continue
            data.reference_samples.append((pid, role, p.get("champion"), float(value), weight))
    return data


# ------------------------------------------------------------------ objectives (open with each game)


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
            [OutcomeSpec("A", team_name(a.code, a.name), p), OutcomeSpec("B", team_name(b.code, b.name), 1 - p)], {"game_index": idx}))
    early = (data.early_baron + 1) / (data.games + 2)
    specs.append(MarketSpec(
        f"baron_before:{key}:{idx}", "baron_before", "GAME", "OBJECTIVES", f"Game {idx} Baron before 25:00",
        f"Yes if either team takes Baron before 25:00 of game time in Game {idx}. No if the first Baron comes "
        f"later or never. {when} {void}",
        close_at, "timeline_rates_v1", "EXPERIMENTAL",
        [OutcomeSpec("YES", "Yes", early), OutcomeSpec("NO", "No", 1 - early)], {"game_index": idx}))
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
    return _display_players(session, fixture, out)


def _display_players(session: Session, fixture: Fixture, lineup: dict[str, dict[str, dict]]) -> dict:
    """Drop the team prefix livestats puts on player names ("GEN Kiin" -> "Kiin")."""
    codes = [t.code for t in (session.get(Team, fixture.team_a_id), session.get(Team, fixture.team_b_id)) if t]
    return {side: {role: {**p, "name": player_name(p.get("name"), codes)} for role, p in roles.items()}
            for side, roles in lineup.items()}


def _player_estimate(data: TimelineData, pid: str, role: str, stat: str,
                     champion: str | None = None) -> tuple[float, float] | None:
    from rift.champions import champion_key
    role_samples = [(v, 1.0) for v in data.role.get(role, {}).get(stat, [])]
    own = [(v, 1.0) for v in data.player.get(pid, {}).get(stat, [])]
    champion_samples = [(value, weight) for lane, champ, key, value, weight in data.champion_samples
                        if lane == role and key == stat and champion
                        and champion_key(champ) == champion_key(champion)]
    if stat == "kills":
        for player, lane, champ, value, weight in data.reference_samples:
            if lane != role:
                continue
            role_samples.append((value, weight))
            if player and str(player) == pid:
                own.append((value, weight))
            if champion and champ and champion_key(champ) == champion_key(champion):
                champion_samples.append((value, weight))
    mass = sum(w for _, w in role_samples)
    if mass < 5:
        return None
    rmean = sum(v * w for v, w in role_samples) / mass
    rvar = sum(w * (v - rmean) ** 2 for v, w in role_samples) / max(mass - 1, 1)
    # Champion conditioning is optional and shrinks heavily toward role until coverage is adequate.
    cmass = sum(w for _, w in champion_samples)
    if cmass >= 3:
        rmean = (sum(v * w for v, w in champion_samples) + 6 * rmean) / (cmass + 6)
    mean = (sum(v * w for v, w in own) + SHRINK_GAMES * rmean) / (sum(w for _, w in own) + SHRINK_GAMES)
    return mean, max(rvar, 1.0 if STATS[stat][1] else 1e-4)


def duel_probability(data: TimelineData, a: dict, b: dict, role: str, stat: str) -> float | None:
    """P(A beats B | no exact tie). None when there isn't enough data to price it."""
    ea = _player_estimate(data, a["player_id"], role, stat, a.get("champion"))
    eb = _player_estimate(data, b["player_id"], role, stat, b.get("champion"))
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


# ------------------------------------------------------------------ early-game window
#
# Duels and kill lines need the champions, which only exist once the game loads (the feed has no live
# champion select). They open on the game's first livestats frame and close at 3:00 of game time; an early
# kill no longer closes them (D-024). Times are the feed's own frame timestamps, so a pick accepted after
# the real cutoff is voided at settlement.

EARLY_WINDOW = timedelta(minutes=3)
EARLY_KINDS = ("lane_duel", "total_kills_game")


@dataclass
class EarlyWindow:
    open: bool
    state: str  # UPCOMING / OPEN / CLOSED
    opens_when: str | None
    close_at: datetime | None
    game: Game | None


def early_cutoff(game: Game) -> datetime | None:
    """3:00 of game time, as wall time from the feed's frames."""
    if game.started_at is None:
        return None
    return game.started_at + EARLY_WINDOW


def early_window(session: Session, fixture: Fixture, game_index: int, now: datetime) -> EarlyWindow:
    game = session.execute(select(Game).where(Game.fixture_id == fixture.id, Game.game_index == game_index)
                           ).scalar_one_or_none()
    return early_state(fixture, game, game_index, now)


def early_state(fixture: Fixture, game: Game | None, game_index: int, now: datetime) -> EarlyWindow:
    """early_window for a game row already in hand."""
    loaded = game is not None and game.started_at is not None and bool((game.timeline or {}).get("participants"))
    if not loaded:
        if fixture.status == "COMPLETED" or (game is not None and game.state in ("completed", "unneeded")):
            return EarlyWindow(False, "CLOSED", None, None, game)
        return EarlyWindow(False, "UPCOMING", f"When Game {game_index} loads, champions locked in", None, game)
    cutoff = early_cutoff(game)
    if now < game.started_at:
        return EarlyWindow(False, "UPCOMING", f"When Game {game_index} loads, champions locked in", None, game)
    if game.state in ("completed", "unneeded") or game.ended_at is not None or now >= cutoff:
        return EarlyWindow(False, "CLOSED", None, cutoff, game)
    return EarlyWindow(True, "OPEN", None, cutoff, game)


def game_lineup(game: Game, fixture: Fixture) -> dict[str, dict[str, dict]]:
    """side ("A"/"B") -> role -> {player_id, name, champion} from the game's first frame."""
    code = {str(fixture.team_a_id): "A", str(fixture.team_b_id): "B"}
    team_of = {"blue": str(game.blue_team_id), "red": str(game.red_team_id)}
    out: dict[str, dict[str, dict]] = {}
    for p in ((game.timeline or {}).get("participants") or {}).values():
        side = code.get(team_of.get(p.get("side"), ""))
        if side and p.get("role") in ROLES:
            out.setdefault(side, {})[p["role"]] = {"player_id": str(p.get("player_id") or p.get("name")),
                                                   "name": p.get("name"), "champion": p.get("champion")}
    return _display_players(object_session(fixture), fixture, out)


def _window_view(w: EarlyWindow) -> dict:
    return {"open": w.open, "state": w.state, "opens_when": w.opens_when,
            "close_at": w.close_at.isoformat() if w.close_at else None}


def duels(session: Session, season: Season, fixture: Fixture, game_index: int, settings: Settings,
          now: datetime) -> dict:
    w = early_window(session, fixture, game_index, now)
    rows = []
    # Before the game loads, show the expected matchups (last known lineups) without prices.
    lineup = lineups(session, fixture) if w.state == "UPCOMING" else game_lineup(w.game, fixture) if w.game else {}
    if lineup:
        data = timeline_data(session, season) if w.open else None
        for role in ROLES:
            a, b = lineup.get("A", {}).get(role), lineup.get("B", {}).get(role)
            if not a or not b:
                continue
            odds = {}
            for stat in STATS:
                p = duel_probability(data, a, b, role, stat) if data is not None else None
                odds[stat] = {"A": _px(p, settings), "B": _px(1 - p, settings) if p is not None else None}
            rows.append({"role": role, "a": a, "b": b, "odds": odds})
    return {"game_index": game_index, **_window_view(w),
            "stats": [{"id": k, "label": v[0]} for k, v in STATS.items()], "duels": rows}


def _px(p: float | None, settings: Settings) -> str | None:
    if p is None:
        return None
    o = price(p, min_probability=Decimal(settings.min_probability), max_odds=Decimal(settings.max_decimal_odds))
    return str(o) if o is not None else None


def _open_early(session: Session, fixture: Fixture, game_index: int, now: datetime) -> EarlyWindow:
    w = early_window(session, fixture, game_index, now)
    if not w.open:
        raise PropsError("NOT_OPEN", f"Game {game_index} early-game picks open when the game loads and close at "
                         "3:00.")
    return w


def ensure_duel(session: Session, season: Season, fixture: Fixture, game_index: int, role: str, stat: str,
                settings: Settings, now: datetime) -> Market:
    if role not in ROLES or stat not in STATS:
        raise PropsError("BAD_DUEL", "Unknown role or stat.")
    w = _open_early(session, fixture, game_index, now)
    lineup = game_lineup(w.game, fixture)
    a, b = lineup.get("A", {}).get(role), lineup.get("B", {}).get(role)
    if not a or not b:
        raise PropsError("NO_LINEUP", "This lane's players aren't in the game data yet.")
    p = duel_probability(timeline_data(session, season), a, b, role, stat)
    if p is None:
        raise PropsError("NOT_OFFERED", "Not enough data to price this duel yet.")
    label = STATS[stat][0]
    who_a, who_b = f"{a['name']} ({a['champion']})", f"{b['name']} ({b['champion']})"
    cs_note = ", as is a game that ends before 15:00" if stat == "cs15" else ""
    spec = MarketSpec(
        f"lane_duel:{fixture.provider_id}:{game_index}:{role}:{stat}:{a['player_id']}:{b['player_id']}",
        "lane_duel", "GAME", "PLAYERS", f"Game {game_index} {role}: {a['name']} vs {b['name']}",
        f"{label}: {who_a} or {who_b} in Game {game_index}. Open from game start until 3:00; a pick "
        f"accepted after that is void. An exact tie is void{cs_note}. Settles from the game's live data.",
        w.close_at, "player_champion_normal_v1", "EXPERIMENTAL",
        [OutcomeSpec("A", a["name"], p), OutcomeSpec("B", b["name"], 1 - p)],
        {"game_index": game_index, "role": role, "stat": stat, "a_player": a["player_id"], "b_player": b["player_id"],
         "a_champion": a["champion"], "b_champion": b["champion"], "early": True})
    market = upsert_market(session, season, fixture, spec, settings, now)
    if market is None:
        raise PropsError("NOT_OPEN", f"Game {game_index} early-game picks are closed.")
    return market


# ------------------------------------------------------------------ kill lines (early-game window)


def _kill_dist(stats: TournamentStats) -> tuple[float, float] | None:
    if stats.games < MIN_DRAFT_GAMES or not stats.kill_totals:
        return None
    mean = sum(stats.kill_totals) / len(stats.kill_totals)
    var = sum((k - mean) ** 2 for k in stats.kill_totals) / max(len(stats.kill_totals) - 1, 1)
    return mean, var


def kill_line_floor(game: Game | None) -> float:
    """The lowest kill line offered right now: at least 5 above the kills already scored."""
    from rift.api.views import game_kills

    return max(KILL_LINE_FLOOR, (game_kills(game) or 0) + KILL_LINE_MARGIN + 0.5)


def _kill_line_rows(dist: tuple[float, float] | None, settings: Settings, floor: float = KILL_LINE_FLOOR) -> list[dict]:
    rows = []
    if dist is None:
        return rows
    for line in (x for x in LINES if x >= floor):
        under = _nb_cdf(int(line), *dist)
        over_px, under_px = _px(1 - under, settings), _px(under, settings)
        if over_px and under_px:
            rows.append({"line": str(line), "over": over_px, "under": under_px})
    return rows


def kill_lines(session: Session, fixture: Fixture, game_index: int, stats: TournamentStats, settings: Settings,
               now: datetime) -> dict:
    w = early_window(session, fixture, game_index, now)
    dist = _kill_dist(stats)
    return {"game_index": game_index, **_window_view(w),
            "champions": game_lineup(w.game, fixture) if w.game else {},
            "typical": str(math.floor(dist[0]) + 0.5) if dist else None,
            "lines": _kill_line_rows(dist, settings, kill_line_floor(w.game)) if w.open else []}


def ensure_kill_line(session: Session, season: Season, fixture: Fixture, game_index: int, line: str,
                     stats: TournamentStats, settings: Settings, now: datetime) -> Market:
    if float(line) not in LINES:
        raise PropsError("BAD_LINE", "Lines run from 14.5 to 44.5 kills.")
    w = _open_early(session, fixture, game_index, now)
    if float(line) < (floor := kill_line_floor(w.game)):
        raise PropsError("BAD_LINE", f"Kill lines start at {floor} right now.")
    dist = _kill_dist(stats)
    if dist is None:
        raise PropsError("NOT_OFFERED", "Not enough games yet to price kill lines.")
    line = str(float(line))
    under = _nb_cdf(int(float(line)), *dist)
    if _px(under, settings) is None or _px(1 - under, settings) is None:
        raise PropsError("NOT_OFFERED", "That kill line isn't offered.")
    spec = MarketSpec(
        f"total_kills_game:{fixture.provider_id}:{game_index}:{line}", "total_kills_game", "GAME", "PROPS",
        f"Game {game_index} total kills {line}",
        f"Combined kills by both teams in Game {game_index}. Over means {int(float(line)) + 1} or more. Open from "
        "game start until 3:00; a pick accepted after that is void. Requires verified final game "
        f"stats; void if Game {game_index} is not played.",
        w.close_at, "negbin_early_v1", "EXPERIMENTAL",
        [OutcomeSpec("OVER", f"Over {line}", 1 - under), OutcomeSpec("UNDER", f"Under {line}", under)],
        {"game_index": game_index, "line": line, "early": True})
    market = upsert_market(session, season, fixture, spec, settings, now)
    if market is None:
        raise PropsError("NOT_OPEN", f"Game {game_index} early-game picks are closed.")
    return market


def tighten_early(session: Session, now: datetime) -> int:
    """Pull each open early-game market's cutoff in line with 3:00 of the game's recorded start."""
    rows = session.execute(select(Market).where(Market.kind.in_(EARLY_KINDS), Market.state == "OPEN",
                                                Market.fixture_id.is_not(None)).with_for_update()).scalars().all()
    changed = 0
    for m in rows:
        if not m.params.get("early"):
            continue
        game = session.execute(select(Game).where(Game.fixture_id == m.fixture_id,
                                                  Game.game_index == m.params["game_index"])).scalar_one_or_none()
        cutoff = early_cutoff(game) if game is not None else None
        if cutoff is not None and cutoff < m.close_at:
            m.close_at = cutoff
            changed += 1
    session.flush()
    return changed


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
