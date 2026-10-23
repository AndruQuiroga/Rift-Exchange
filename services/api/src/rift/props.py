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

Early-window markets (game load to 3:00) follow the game as it plays (D-028): first to 5 kills, kill lines,
the team gold lead and gold duels are re-priced from the latest livestats frame each worker poll, and record
which frame they were priced on. A pick accepted after a kill that frame had not shown yet is void.
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
from rift.markets import (
    MIN_DRAFT_GAMES,
    MarketSpec,
    OutcomeSpec,
    TournamentStats,
    _nb_cdf,
    tournament_stats,
    upsert_market,
)
from rift.models import Fixture, Game, Market, Season, Team

DRAGONS = ("infernal", "ocean", "mountain", "cloud", "hextech", "chemtech")
EARLY_BARON_S = 25 * 60
ROLES = ("top", "jungle", "mid", "bottom", "support")
STATS = {
    "kills": ("More kills", True),
    "cs15": ("More CS at 15:00", True),
    "damage": ("Higher damage share", False),
    "gold15": ("More gold at 15:00", True),
}
# Duels offered for new games (D-025): gold at 15:00 only. Kills, CS and damage duels already placed still
# settle as before.
OFFERED_STATS = ("gold15",)
# A lead smaller than this is a tie, and ties void.
TIE_MARGIN = {"gold15": 700}
TEAM_GOLD_TIE = 700  # the team gold lead at 15:00 uses the same tie band
SHRINK_GAMES = 3  # pseudo-games of the role average added to each player's own record
OBJECTIVE_KINDS = ("first_blood", "first_tower", "first_dragon_type", "baron_before", "dragon_soul")
# Team races in the early window (D-025): open from game load to 3:00, settled from the timeline.
EARLY_TEAM_KINDS = ("five_kills", "gold_lead_15", "first_dragon")
# Offered for new games (D-023). First dragon element and dragon soul are no longer offered; existing ones
# still lock and settle from the timeline like the rest.
OFFERED_OBJECTIVES = ("first_blood", "first_tower", "baron_before")
RETIRED_OBJECTIVES = tuple(k for k in OBJECTIVE_KINDS if k not in OFFERED_OBJECTIVES)
KINDS = (*OBJECTIVE_KINDS, *EARLY_TEAM_KINDS, "lane_duel")
LINES = [x + 0.5 for x in range(14, 45)]
# Kill lines stay clear of what the first three minutes have already settled: at least 5 kills above the
# game's kill count so far (D-024).
KILL_LINE_FLOOR = LINES[0]
KILL_LINE_MARGIN = 5
# Only lines whose both sides price at 10.00 or shorter are offered: the tails rest on a few dozen games.
KILL_LINE_MAX_ODDS = Decimal("10.00")


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
    gold15_gaps: list[int] = field(default_factory=list)  # team gold difference at 15:00, one per game
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
            "gold15": (at15.get(pid) or {}).get("gold"),
        }
    return out


def gold15_lead(game: Game) -> tuple[str | None, int] | None:
    """(team_id ahead at 15:00, gold gap), team_id None on a dead heat; None without a 15:00 frame."""
    tl = game.timeline or {}
    at15 = ((tl.get("at_15") or {}).get("players")) or {}
    team_of = {"blue": game.blue_team_id, "red": game.red_team_id}
    gold = Counter()
    for pid, p in (tl.get("participants") or {}).items():
        if (at15.get(pid) or {}).get("gold") is None:
            return None
        gold[str(team_of.get(p.get("side")) or "")] += at15[pid]["gold"]
    if len(gold) != 2:
        return None
    (lead, g1), (_, g2) = gold.most_common(2)
    return (None if g1 == g2 else lead), g1 - g2


def timeline_data(session: Session, season: Season) -> TimelineData:
    data = TimelineData()
    took = Counter()
    for g in _complete_games(session, season):
        tl = g.timeline or {}
        firsts = tl.get("firsts") or {}
        data.games += 1
        for what in ("blood", "tower", "dragon", "five_kills"):
            first = firsts.get(what)
            if first and first.get("team_id") and g.winner_team_id is not None:
                took[(what, "n")] += 1
                took[(what, "w")] += int(first.get("team_id") == str(g.winner_team_id))
        lead = gold15_lead(g)
        if lead:
            data.gold15_gaps.append(lead[1])
        if lead and lead[0] and lead[1] >= TEAM_GOLD_TIE and g.winner_team_id is not None:
            took[("gold15", "n")] += 1
            took[("gold15", "w")] += int(lead[0] == str(g.winner_team_id))
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
    for what in ("blood", "tower", "dragon", "five_kills", "gold15"):
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
        sooner = " Closes at the first kill if that comes sooner." if kind == "first_blood" else ""
        specs.append(MarketSpec(
            f"{kind}:{key}:{idx}", kind, "GAME", "OBJECTIVES", f"Game {idx} {title.lower()}",
            f"Team that gets {title.lower()} in Game {idx}. {when}{sooner} {void}",
            close_at, "timeline_rates_v1", "EXPERIMENTAL",
            [OutcomeSpec("A", team_name(a.code, a.name), p), OutcomeSpec("B", team_name(b.code, b.name), 1 - p)],
            {"game_index": idx, "through_draft": True}))
    early = (data.early_baron + 1) / (data.games + 2)
    specs.append(MarketSpec(
        f"baron_before:{key}:{idx}", "baron_before", "GAME", "OBJECTIVES", f"Game {idx} Baron before 25:00",
        f"Yes if either team takes Baron before 25:00 of game time in Game {idx}. No if the first Baron comes "
        f"later or never. {when} {void}",
        close_at, "timeline_rates_v1", "EXPERIMENTAL",
        [OutcomeSpec("YES", "Yes", early), OutcomeSpec("NO", "No", 1 - early)], {"game_index": idx, "through_draft": True}))
    return specs


# ------------------------------------------------------------------ live state (early window)

GOLD_STEP = 250  # gold gaps are priced in steps of this, so prices move on real swings, not every frame
CLOCK_STEP_S = 30
AT_15_S = 15 * 60
RACE_TO = 5
EARLY_KILLS_PER_MIN = 0.25  # assumed kill rate in the first minutes, taken off the expected rest of the game
DEFAULT_GOLD15_SD = 2500.0  # team gold gap spread at 15:00 until enough games have a 15:00 frame
LIVE_KINDS = ("five_kills", "gold_lead_15", "lane_duel", "total_kills_game")
LIVE_NOTE = ("The price follows the game as it plays; a pick accepted after a kill the price hadn't seen yet "
             "is void.")


@dataclass
class LiveState:
    at: datetime | None  # feed time of the frame these numbers come from
    clock_s: int
    kills: dict[str, int]  # "A"/"B"
    gold_gap: int  # team A minus team B, rounded to GOLD_STEP
    player_gold: dict[str, int]  # player_id -> gold

    @property
    def clock(self) -> int:
        return self.clock_s // CLOCK_STEP_S * CLOCK_STEP_S

    @property
    def remaining(self) -> float:
        """Share of the first fifteen minutes still to play."""
        return max(1 - self.clock / AT_15_S, 0.05)

    def stamp(self) -> dict:
        return {"priced_at": self.at.isoformat()} if self.at else {}


def _step(value: float, step: int) -> int:
    return int(round(value / step) * step)


def live_state(fixture: Fixture, game: Game | None) -> LiveState | None:
    """The latest livestats numbers for a loaded game, by fixture side. None before it loads."""
    if game is None or game.started_at is None:
        return None
    from rift.adapters.lolesports import parse_time

    tl = game.timeline or {}
    live = tl.get("live") or {}
    a_blue = game.blue_team_id == fixture.team_a_id
    side = {"blue": "A" if a_blue else "B", "red": "B" if a_blue else "A", "A": "A", "B": "B"}
    kills, gold = {"A": 0, "B": 0}, {"A": 0, "B": 0}
    for k, v in (live.get("kills") or {}).items():
        if k in side:
            kills[side[k]] += int(v or 0)
    for k, v in (live.get("gold") or {}).items():
        if k in side:
            gold[side[k]] += int(v or 0)
    participants = tl.get("participants") or {}
    player_gold = {str(participants[pid].get("player_id") or participants[pid].get("name")): int(g)
                   for pid, g in (live.get("players") or {}).items() if pid in participants and g is not None}
    return LiveState(parse_time(live["at"]) if live.get("at") else None, int(live.get("clock_s") or 0), kills,
                     _step(gold["A"] - gold["B"], GOLD_STEP), player_gold)


def race_probability(share: float, need_a: int, need_b: int) -> float:
    """P(A scores need_a more kills before B scores need_b), each kill A's with probability `share`."""
    return sum(math.comb(need_a - 1 + j, j) * share**need_a * (1 - share) ** j for j in range(need_b))


def _solve(f, target: float, lo: float, hi: float) -> float:
    """x in [lo, hi] with f(x) = target, for an increasing f (bisection)."""
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < target else (lo, mid)
    return (lo + hi) / 2


def five_kills_probability(p0: float, state: LiveState | None) -> float | None:
    """P(A first to five kills) given the kills so far; p0 is the price at 0-0. None once it's decided."""
    if state is None:
        return p0
    ka, kb = state.kills["A"], state.kills["B"]
    if ka >= RACE_TO or kb >= RACE_TO:
        return None
    share = _solve(lambda r: race_probability(r, RACE_TO, RACE_TO), p0, 0.01, 0.99)
    return race_probability(share, RACE_TO - ka, RACE_TO - kb)


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _lead_probability(mu: float, sd: float, band: float) -> float:
    """P(gap > band | |gap| >= band) for gap ~ N(mu, sd): a lead inside the band is a tie and voids."""
    win, lose = 1 - _phi((band - mu) / sd), _phi((-band - mu) / sd)
    return win / (win + lose) if win + lose > 1e-12 else (1.0 if mu > 0 else 0.0)


def gold_gap_sd(data: TimelineData) -> float:
    gaps = data.gold15_gaps
    return math.sqrt(sum(g * g for g in gaps) / len(gaps)) if len(gaps) >= 5 else DEFAULT_GOLD15_SD


def gold_lead_probability(p0: float, sd15: float, state: LiveState | None) -> float:
    """P(A leads by 700+ at 15:00 | no tie): the pre-game drift over what's left of the fifteen minutes, plus
    the gap now, with the spread of what's left to play."""
    if state is None:
        return p0
    mu0 = _solve(lambda m: _lead_probability(m, sd15, TEAM_GOLD_TIE), p0, -3 * sd15, 3 * sd15)
    rest = state.remaining
    return _lead_probability(mu0 * rest + state.gold_gap, sd15 * math.sqrt(rest), TEAM_GOLD_TIE)


def priced_before_a_kill(params: dict, game: Game | None, accepted_at: datetime) -> bool:
    """A live price records the frame it was computed from; a kill after that frame and no later than the
    pick's acceptance means the price was stale, so the pick is void."""
    if not params.get("priced_at") or game is None:
        return False
    from rift.adapters.lolesports import parse_time

    priced = parse_time(params["priced_at"])
    return any(priced < parse_time(k["at"]) <= accepted_at for k in (game.timeline or {}).get("kills_at") or [])


def early_team_specs(fixture: Fixture, idx: int, a: Team, b: Team, q: float, data: TimelineData,
                     close_at: datetime, state: LiveState | None = None) -> list[MarketSpec]:
    """First to 5 kills, gold lead at 15:00 and first dragon for a loaded game: one row each, A or B."""
    if data.games < MIN_DRAFT_GAMES:
        return []
    key = fixture.provider_id
    open_note = "Open from game load until 3:00 of game time; a pick accepted after that is void."
    rows = (
        ("five_kills", "five_kills", "First to 5 kills",
         "Team that reaches 5 kills first. Void if neither does, or both in the same moment."),
        ("gold_lead_15", "gold15", "Gold lead at 15:00",
         ("Team with more total gold at 15:00 of game time. A gap under 700 gold is a tie and void, as is a game "
         "that ends before 15:00.")),
        ("first_dragon", "dragon", "First dragon",
         "Team that takes the first dragon, any element. Void if no dragon is taken."),
    )
    specs = []
    for kind, what, title, rules in rows:
        w = data.winner_took_first.get(what, 0.5)
        p = q * w + (1 - q) * (1 - w)
        params, note, model = {"game_index": idx, "early": True}, "", "timeline_rates_v1"
        if kind in LIVE_KINDS and state is not None:
            p = (five_kills_probability(p, state) if kind == "five_kills"
                 else gold_lead_probability(p, gold_gap_sd(data), state))
            params, note, model = {**params, **state.stamp()}, f" {LIVE_NOTE}", "timeline_rates_live_v1"
        if p is None:  # the race is already won: nothing left to price
            continue
        specs.append(MarketSpec(
            f"{kind}:{key}:{idx}", kind, "GAME", "OBJECTIVES", f"Game {idx} {title.lower()}",
            f"{rules} {open_note}{note} Settles from the game's live data; void if Game {idx} is not played.",
            close_at, model, "EXPERIMENTAL",
            [OutcomeSpec("A", team_name(a.code, a.name), p), OutcomeSpec("B", team_name(b.code, b.name), 1 - p)],
            params))
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


def duel_probability(data: TimelineData, a: dict, b: dict, role: str, stat: str,
                     state: LiveState | None = None) -> float | None:
    """P(A beats B | no exact tie). None when there isn't enough data to price it. A gold duel in a live game
    adds the players' gold gap now to the expected rest of the fifteen minutes."""
    ea = _player_estimate(data, a["player_id"], role, stat, a.get("champion"))
    eb = _player_estimate(data, b["player_id"], role, stat, b.get("champion"))
    if ea is None or eb is None:
        return None
    mu, sd = ea[0] - eb[0], math.sqrt(ea[1] + eb[1])
    if stat == "gold15" and state is not None:
        ga, gb = state.player_gold.get(a["player_id"]), state.player_gold.get(b["player_id"])
        if ga is not None and gb is not None:
            rest = state.remaining
            mu, sd = mu * rest + _step(ga - gb, GOLD_STEP // 2), sd * math.sqrt(rest)

    def cdf(x: float) -> float:
        return 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))

    # A difference inside the tie band voids: whole numbers within half a unit, gold within 700.
    band = TIE_MARGIN.get(stat, 0.5 if STATS[stat][1] else 0.0)
    win, lose = 1 - cdf(band), cdf(-band)
    return win / (win + lose) if win + lose > 1e-9 else 0.5


# ------------------------------------------------------------------ early-game window
#
# Duels and kill lines need the champions, which only exist once the game loads (the feed has no live
# champion select). They open on the game's first livestats frame and close at 3:00 of game time; an early
# kill no longer closes them (D-024). Times are the feed's own frame timestamps, so a pick accepted after
# the real cutoff is voided at settlement.

EARLY_WINDOW = timedelta(minutes=3)
EARLY_KINDS = ("lane_duel", "total_kills_game", *EARLY_TEAM_KINDS)


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


def market_cutoff(market: Market, game: Game | None) -> datetime | None:
    """The real cutoff of an early-window or through-draft market once its game has loaded: 3:00 of game
    time, and first blood also at the first kill. None while the game hasn't loaded."""
    cutoff = early_cutoff(game) if game is not None else None
    if cutoff is not None and market.kind == "first_blood":
        blood = ((game.timeline or {}).get("firsts") or {}).get("blood")
        if blood:
            cutoff = min(cutoff, game.started_at + timedelta(seconds=blood["at_s"]))
    return cutoff


def market_game(session: Session, market: Market) -> Game | None:
    """The game a timed market belongs to (a Bo1's match winner: Game 1)."""
    return session.execute(select(Game).where(Game.fixture_id == market.fixture_id,
                                              Game.game_index == market.params.get("game_index", 1))
                           ).scalar_one_or_none()


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


# ------------------------------------------------------------------ blind vs after the draft
#
# Duels and kill lines are offered twice per game (D-031). Blind: before the draft, priced on the expected
# players and team history, closing with the champion calls before the draft starts (rift.draft.draft_window).
# After the draft: from the game's first frame, with champions, until 3:00 (the early window). They are
# separate markets, so a blind pick stands whatever champions are picked; a blind duel voids if either named
# player doesn't play. The draft itself has no betting: the feed shows no champion select, and anyone watching
# the broadcast would see it first.


@dataclass
class Phase:
    name: str  # BLIND / DRAFT (blind closed, waiting for the game to load) / LIVE / CLOSED / UPCOMING
    open: bool
    close_at: datetime | None
    early: EarlyWindow


def phase(session: Session, fixture: Fixture, game_index: int, now: datetime) -> Phase:
    from rift.draft import draft_window

    w = early_window(session, fixture, game_index, now)
    if w.state != "UPCOMING":
        return Phase("LIVE" if w.open else "CLOSED", w.open, w.close_at, w)
    blind = draft_window(session, fixture, game_index, now)
    if blind.open:
        return Phase("BLIND", True, blind.close_at, w)
    if blind.close_at is None:
        return Phase("UPCOMING", False, None, w)  # a later game, before the previous one ends
    return Phase("DRAFT", False, None, w)


def _phase_view(ph: Phase) -> dict:
    opens = {"BLIND": None, "DRAFT": "When the game loads, champions locked in", "UPCOMING": ph.early.opens_when}
    return {"phase": ph.name, "open": ph.open, "state": "OPEN" if ph.open else ph.early.state,
            "opens_when": opens.get(ph.name), "close_at": ph.close_at.isoformat() if ph.close_at else None}


def duels(session: Session, season: Season, fixture: Fixture, game_index: int, settings: Settings,
          now: datetime) -> dict:
    ph = phase(session, fixture, game_index, now)
    w = ph.early
    rows = []
    # Until the game loads: the expected matchups (last known lineups), priced only while blind picks are open.
    loaded = ph.name in ("LIVE", "CLOSED") and w.game is not None
    lineup = game_lineup(w.game, fixture) if loaded else lineups(session, fixture)
    state = live_state(fixture, w.game) if ph.name == "LIVE" else None
    if lineup:
        data = timeline_data(session, season) if ph.open else None
        for role in ROLES:
            a, b = lineup.get("A", {}).get(role), lineup.get("B", {}).get(role)
            if not a or not b:
                continue
            odds = {}
            for stat in OFFERED_STATS:
                p = duel_probability(data, a, b, role, stat, state) if data is not None else None
                odds[stat] = {"A": _px(p, settings), "B": _px(1 - p, settings) if p is not None else None}
            rows.append({"role": role, "a": a, "b": b, "odds": odds})
    return {"game_index": game_index, **_phase_view(ph),
            "stats": [{"id": k, "label": STATS[k][0]} for k in OFFERED_STATS], "duels": rows}


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
    if role not in ROLES or stat not in OFFERED_STATS:
        raise PropsError("BAD_DUEL", "Unknown role or stat.")
    ph = phase(session, fixture, game_index, now)
    if ph.name == "BLIND":
        return _ensure_blind_duel(session, season, fixture, game_index, role, stat, ph.close_at, settings, now)
    if ph.name == "DRAFT":
        raise PropsError("NOT_OPEN", f"Game {game_index} is in its draft: duels reopen with champions when the "
                         "game loads.")
    w = _open_early(session, fixture, game_index, now)
    lineup = game_lineup(w.game, fixture)
    a, b = lineup.get("A", {}).get(role), lineup.get("B", {}).get(role)
    if not a or not b:
        raise PropsError("NO_LINEUP", "This lane's players aren't in the game data yet.")
    state = live_state(fixture, w.game)
    p = duel_probability(timeline_data(session, season), a, b, role, stat, state)
    if p is None:
        raise PropsError("NOT_OFFERED", "Not enough data to price this duel yet.")
    label = STATS[stat][0]
    who_a, who_b = f"{a['name']} ({a['champion']})", f"{b['name']} ({b['champion']})"
    tie_note = (f"A gap under {TIE_MARGIN[stat]:,} gold is a tie" if stat in TIE_MARGIN else "An exact tie is")
    at15_note = ", as is a game that ends before 15:00" if stat in ("cs15", "gold15") else ""
    spec = MarketSpec(
        f"lane_duel:{fixture.provider_id}:{game_index}:{role}:{stat}:{a['player_id']}:{b['player_id']}",
        "lane_duel", "GAME", "PLAYERS", f"Game {game_index} {role}: {a['name']} vs {b['name']}",
        f"{label}: {who_a} or {who_b} in Game {game_index}. Open from game start until 3:00; a pick "
        f"accepted after that is void. {LIVE_NOTE} {tie_note} void{at15_note}. Settles from the game's live data.",
        w.close_at, "player_champion_live_v1", "EXPERIMENTAL",
        [OutcomeSpec("A", a["name"], p), OutcomeSpec("B", b["name"], 1 - p)],
        {"game_index": game_index, "role": role, "stat": stat, "a_player": a["player_id"], "b_player": b["player_id"],
         "a_champion": a["champion"], "b_champion": b["champion"], "early": True,
         **(state.stamp() if state else {})})
    market = upsert_market(session, season, fixture, spec, settings, now)
    if market is None:
        raise PropsError("NOT_OPEN", f"Game {game_index} early-game picks are closed.")
    return market


def _ensure_blind_duel(session: Session, season: Season, fixture: Fixture, game_index: int, role: str, stat: str,
                       close_at: datetime, settings: Settings, now: datetime) -> Market:
    lineup = lineups(session, fixture)
    a, b = lineup.get("A", {}).get(role), lineup.get("B", {}).get(role)
    if not a or not b:
        raise PropsError("NO_LINEUP", "This lane's expected players aren't known yet.")
    p = duel_probability(timeline_data(session, season), a, b, role, stat)
    if p is None:
        raise PropsError("NOT_OFFERED", "Not enough data to price this duel yet.")
    label = STATS[stat][0]
    tie_note = (f"A gap under {TIE_MARGIN[stat]:,} gold is a tie" if stat in TIE_MARGIN else "An exact tie is")
    at15_note = ", as is a game that ends before 15:00" if stat in ("cs15", "gold15") else ""
    spec = MarketSpec(
        f"lane_duel:{fixture.provider_id}:{game_index}:{role}:{stat}:{a['player_id']}:{b['player_id']}:blind",
        "lane_duel", "GAME", "PLAYERS", f"Game {game_index} {role} (blind): {a['name']} vs {b['name']}",
        f"{label}: {a['name']} or {b['name']} in Game {game_index}, called before the draft whatever champions "
        f"they play. Closes before the draft starts. Void if either player doesn't play Game {game_index}. "
        f"{tie_note} void{at15_note}. Settles from the game's live data.",
        close_at, "player_blind_v1", "EXPERIMENTAL",
        [OutcomeSpec("A", a["name"], p), OutcomeSpec("B", b["name"], 1 - p)],
        {"game_index": game_index, "role": role, "stat": stat, "a_player": a["player_id"], "b_player": b["player_id"],
         "blind": True})
    market = upsert_market(session, season, fixture, spec, settings, now)
    if market is None:
        raise PropsError("NOT_OPEN", f"Game {game_index} blind picks are closed.")
    return market


# ------------------------------------------------------------------ kill lines (blind and early-game window)


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


def _line_offered(under: float, settings: Settings) -> bool:
    prices = (_px(under, settings), _px(1 - under, settings))
    return all(p is not None and Decimal(p) <= KILL_LINE_MAX_ODDS for p in prices)


def kill_under_probability(line: float, dist: tuple[float, float], state: LiveState | None) -> float:
    """P(total kills <= line): the kills so far plus a negative binomial for the rest of the game, whose mean
    drops by the kills the opening minutes usually bring."""
    if state is None:
        return _nb_cdf(int(line), *dist)
    mean, var = dist
    so_far = state.kills["A"] + state.kills["B"]
    if int(line) < so_far:
        return 0.0
    rest = max(mean - EARLY_KILLS_PER_MIN * state.clock / 60, 1.0)
    return _nb_cdf(int(line) - so_far, rest, var * rest / mean)


def _kill_line_rows(dist: tuple[float, float] | None, settings: Settings, floor: float = KILL_LINE_FLOOR,
                    state: LiveState | None = None) -> list[dict]:
    rows = []
    if dist is None:
        return rows
    for line in (x for x in LINES if x >= floor):
        under = kill_under_probability(line, dist, state)
        over_px, under_px = _px(1 - under, settings), _px(under, settings)
        if _line_offered(under, settings):
            rows.append({"line": str(line), "over": over_px, "under": under_px})
    return rows


def kill_lines(session: Session, fixture: Fixture, game_index: int, stats: TournamentStats, settings: Settings,
               now: datetime) -> dict:
    ph = phase(session, fixture, game_index, now)
    w = ph.early
    dist = _kill_dist(stats)
    rows = (_kill_line_rows(dist, settings, kill_line_floor(w.game), live_state(fixture, w.game))
            if ph.name == "LIVE" else _kill_line_rows(dist, settings) if ph.name == "BLIND" else [])
    return {"game_index": game_index, **_phase_view(ph),
            "champions": game_lineup(w.game, fixture) if w.game and ph.name in ("LIVE", "CLOSED") else {},
            "typical": str(math.floor(dist[0]) + 0.5) if dist else None, "lines": rows}


def ensure_kill_line(session: Session, season: Season, fixture: Fixture, game_index: int, line: str,
                     stats: TournamentStats, settings: Settings, now: datetime) -> Market:
    if float(line) not in LINES:
        raise PropsError("BAD_LINE", "Lines run from 14.5 to 44.5 kills.")
    ph = phase(session, fixture, game_index, now)
    if ph.name == "BLIND":
        dist = _kill_dist(stats)
        if dist is None:
            raise PropsError("NOT_OFFERED", "Not enough games yet to price kill lines.")
        under = kill_under_probability(float(line), dist, None)
        if not _line_offered(under, settings):
            raise PropsError("NOT_OFFERED", "That kill line isn't offered.")
        market = upsert_market(session, season, fixture, _kill_line_spec(
            fixture, game_index, str(float(line)), under, ph.close_at, None, blind=True), settings, now)
        if market is None:
            raise PropsError("NOT_OPEN", f"Game {game_index} blind picks are closed.")
        return market
    if ph.name == "DRAFT":
        raise PropsError("NOT_OPEN", f"Game {game_index} is in its draft: kill lines reopen when the game loads.")
    w = _open_early(session, fixture, game_index, now)
    if float(line) < (floor := kill_line_floor(w.game)):
        raise PropsError("BAD_LINE", f"Kill lines start at {floor} right now.")
    dist = _kill_dist(stats)
    if dist is None:
        raise PropsError("NOT_OFFERED", "Not enough games yet to price kill lines.")
    state = live_state(fixture, w.game)
    under = kill_under_probability(float(line), dist, state)
    if not _line_offered(under, settings):
        raise PropsError("NOT_OFFERED", "That kill line isn't offered.")
    market = upsert_market(session, season, fixture, _kill_line_spec(fixture, game_index, str(float(line)), under,
                                                                      w.close_at, state), settings, now)
    if market is None:
        raise PropsError("NOT_OPEN", f"Game {game_index} early-game picks are closed.")
    return market


def _kill_line_spec(fixture: Fixture, game_index: int, line: str, under: float, close_at: datetime,
                    state: LiveState | None, blind: bool = False) -> MarketSpec:
    if blind:
        return MarketSpec(
            f"total_kills_game:{fixture.provider_id}:{game_index}:{line}:blind", "total_kills_game", "GAME",
            "PROPS", f"Game {game_index} total kills {line} (blind)",
            f"Combined kills by both teams in Game {game_index}, called before the draft. Over means "
            f"{int(float(line)) + 1} or more. Closes before the draft starts. Requires verified final game stats; "
            f"void if Game {game_index} is not played.",
            close_at, "negbin_blind_v1", "EXPERIMENTAL",
            [OutcomeSpec("OVER", f"Over {line}", 1 - under), OutcomeSpec("UNDER", f"Under {line}", under)],
            {"game_index": game_index, "line": line, "blind": True})
    return MarketSpec(
        f"total_kills_game:{fixture.provider_id}:{game_index}:{line}", "total_kills_game", "GAME", "PROPS",
        f"Game {game_index} total kills {line}",
        f"Combined kills by both teams in Game {game_index}. Over means {int(float(line)) + 1} or more. Open from "
        f"game start until 3:00; a pick accepted after that is void. {LIVE_NOTE} Requires verified final game "
        f"stats; void if Game {game_index} is not played.",
        close_at, "negbin_live_v1", "EXPERIMENTAL",
        [OutcomeSpec("OVER", f"Over {line}", 1 - under), OutcomeSpec("UNDER", f"Under {line}", under)],
        {"game_index": game_index, "line": line, "early": True, **(state.stamp() if state else {})})


def tighten_early(session: Session, now: datetime) -> int:
    """Pull each open early-window or through-draft market's cutoff to 3:00 of its game (first blood: also
    the first kill) once the game has loaded."""
    rows = session.execute(select(Market).where(Market.state == "OPEN", Market.fixture_id.is_not(None))
                           .with_for_update()).scalars().all()
    changed = 0
    for m in rows:
        if not (m.params.get("early") or m.params.get("through_draft")):
            continue
        cutoff = market_cutoff(m, market_game(session, m))
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

    if kind == "gold_lead_15":
        lead = gold15_lead(game)
        if lead is None:
            return Grade("VOID", reason="No 15:00 gold (the game ended before 15:00)", evidence=ev)
        code = side_code.get(lead[0] or "")
        if code is None or lead[1] < TEAM_GOLD_TIE:
            return Grade("VOID", reason=f"Within {TEAM_GOLD_TIE:,} gold at 15:00 (void rule)", evidence={**ev, "gap": lead[1]})
        return Grade("RESULT", [code], "Gold lead at 15:00 confirmed", {**ev, "gap": lead[1]})
    if kind in ("first_blood", "first_tower", "first_dragon", "five_kills"):
        first = firsts.get({"first_blood": "blood", "first_tower": "tower", "first_dragon": "dragon",
                            "five_kills": "five_kills"}[kind])
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
        if abs(va - vb) < TIE_MARGIN.get(stat, 1e-9):
            reason = f"Within {TIE_MARGIN[stat]:,} gold (void rule)" if stat in TIE_MARGIN else "Exact tie (void rule)"
            return Grade("VOID", reason=reason, evidence={**ev, "values": [va, vb]})
        return Grade("RESULT", ["A" if va > vb else "B"], "Player stats confirmed", {**ev, "values": [va, vb]})
    return Grade("HOLD", reason=f"No grader for {kind}")


def open_early_team_markets(session: Session, season: Season, settings: Settings, model, now: datetime) -> int:
    """Open (and keep open until 3:00) the team races for every live game whose early window is open."""
    fixtures = session.execute(select(Fixture).where(
        Fixture.season_id == season.id, Fixture.status == "LIVE",
        Fixture.team_a_id.is_not(None), Fixture.team_b_id.is_not(None))).scalars().all()
    data, stats, count = None, None, 0
    for f in fixtures:
        for g in session.execute(select(Game).where(Game.fixture_id == f.id)).scalars():
            w = early_state(f, g, g.game_index, now)
            if not w.open:
                continue
            data = data or timeline_data(session, season)
            a, b = session.get(Team, f.team_a_id), session.get(Team, f.team_b_id)
            state = live_state(f, g)
            for spec in early_team_specs(f, g.game_index, a, b, model.game_probability(a.id, b.id), data, w.close_at,
                                         state):
                count += int(upsert_market(session, season, f, spec, settings, now) is not None)
            stats = stats or tournament_stats(session, season)
            reprice_live(session, season, f, g, w, stats, state, settings, now)
    return count


def reprice_live(session: Session, season: Season, fixture: Fixture, game: Game, w: EarlyWindow,
                 stats: TournamentStats, state: LiveState | None, settings: Settings, now: datetime) -> None:
    """Re-price the duels and kill lines already open on this game from the latest frame. A line the kills
    have overtaken keeps being priced (usually out of offer) rather than standing at a stale price."""
    lineup = game_lineup(game, fixture)
    for m in session.execute(select(Market).where(
            Market.fixture_id == fixture.id, Market.state == "OPEN",
            Market.kind.in_(("lane_duel", "total_kills_game")))).scalars().all():
        if m.params.get("game_index") != game.game_index or not m.params.get("early"):
            continue
        if m.kind == "total_kills_game":
            dist = _kill_dist(stats)
            if dist is not None:
                under = kill_under_probability(float(m.params["line"]), dist, state)
                upsert_market(session, season, fixture, _kill_line_spec(
                    fixture, game.game_index, m.params["line"], under, w.close_at, state), settings, now)
        elif m.params.get("stat") in OFFERED_STATS:
            role = m.params["role"]
            a, b = lineup.get("A", {}).get(role), lineup.get("B", {}).get(role)
            if a and b and (a["player_id"], b["player_id"]) == (m.params["a_player"], m.params["b_player"]):
                ensure_duel(session, season, fixture, game.game_index, role, m.params["stat"], settings, now)
