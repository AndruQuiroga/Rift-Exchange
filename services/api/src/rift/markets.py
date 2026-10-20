"""Market templates, model pricing and odds versioning (docs/spec/03_MARKET_CATALOG.md).

Markets are created and re-priced automatically from canonical fixtures and model outputs (D-008, D-013).
Accepted selections keep their frozen odds; only OPEN markets are re-priced, each change is a new version.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from rift.config import Settings
from rift.domain.pricing import (
    normalise,
    price,
    series_score_distribution,
    series_win_probability,
    total_games_distribution,
)
from rift.models import AuditEvent, Fixture, Game, Market, OddsSnapshot, OutboxEvent, Outcome, Season, Team
from rift.ratings import EloModel
from rift.simulate import FuturesProbabilities

MIN_DRAFT_GAMES = 15


@dataclass
class OutcomeSpec:
    code: str
    label: str
    probability: float


@dataclass
class MarketSpec:
    template_key: str
    kind: str
    scope: str
    category: str
    title: str
    rules_text: str
    close_at: datetime
    model_key: str
    confidence: str
    outcomes: list[OutcomeSpec]
    params: dict


@dataclass
class TournamentStats:
    """Draft and kill tendencies observed in completed Worlds games with verified stats."""

    games: int
    pick_rate: dict[str, float]
    kill_totals: list[int]
    timeline: object | None = None  # rift.props.TimelineData: objective rates and player lines


def tournament_stats(session: Session, season: Season) -> TournamentStats:
    rows = session.execute(
        select(Game.stats).join(Fixture, Fixture.id == Game.fixture_id)
        .where(Fixture.season_id == season.id, Game.stats_complete.is_(True))
    ).scalars().all()
    counts: dict[str, int] = {}
    totals = []
    for stats in rows:
        for champ in {p["champion"] for p in stats["players"]}:
            counts[champ] = counts.get(champ, 0) + 1
        totals.append(sum(p["kills"] for p in stats["players"]))
    n = len(rows)
    from rift.props import timeline_data  # props builds on this module's market specs

    return TournamentStats(games=n, pick_rate={c: k / n for c, k in counts.items()} if n else {}, kill_totals=totals,
                           timeline=timeline_data(session, season))


def _nb_cdf(k: int, mean: float, var: float) -> float:
    """P(X <= k) for a negative binomial (method of moments), Poisson if not over-dispersed."""
    if var <= mean:
        return sum(math.exp(-mean) * mean**i / math.factorial(i) for i in range(k + 1))
    r = mean * mean / (var - mean)
    p = r / (r + mean)
    total = 0.0
    for i in range(k + 1):
        total += math.exp(math.lgamma(i + r) - math.lgamma(r) - math.lgamma(i + 1) + r * math.log(p)
                          + i * math.log(1 - p))
    return total


def champion_label(champ: str) -> str:
    special = {"MonkeyKing": "Wukong", "JarvanIV": "Jarvan IV", "LeeSin": "Lee Sin", "XinZhao": "Xin Zhao",
               "MissFortune": "Miss Fortune", "TwistedFate": "Twisted Fate", "AurelionSol": "Aurelion Sol",
               "TahmKench": "Tahm Kench", "DrMundo": "Dr. Mundo", "MasterYi": "Master Yi", "KSante": "K'Sante",
               "RekSai": "Rek'Sai", "KaiSa": "Kai'Sa", "Kaisa": "Kai'Sa", "Belveth": "Bel'Veth", "Chogath": "Cho'Gath",
               "Khazix": "Kha'Zix", "Velkoz": "Vel'Koz", "Nunu": "Nunu & Willump", "RenataGlasc": "Renata Glasc"}
    return special.get(champ, champ)


NEXT_GAME_WINDOW = timedelta(minutes=7)  # Game N markets close this long after Game N-1 ends (draft ~10 min)


def kills_line(stats: TournamentStats) -> str | None:
    if stats.games < MIN_DRAFT_GAMES:
        return None
    return str(math.floor(sum(stats.kill_totals) / len(stats.kill_totals)) + 0.5)


def game_specs(fixture: Fixture, idx: int, a: Team, b: Team, q: float, stats: TournamentStats, close_at: datetime,
               confidence: str, line: str | None = None) -> list[MarketSpec]:
    """Markets scoped to one game. `line` pins a kills line already offered so a moving mean never forks it."""
    key = fixture.provider_id
    when = ("Locks at the scheduled series start." if idx == 1 else
            f"Opens when Game {idx - 1} ends; locks 7 minutes later or when Game {idx} starts, whichever is first.")
    specs = []
    if fixture.best_of > 1:
        specs.append(MarketSpec(
            f"game_winner:{key}:{idx}", "game_winner", "GAME", "WINNER", f"Game {idx} winner",
            f"Winner of Game {idx} of this series. {when} Void if Game {idx} is not played.",
            close_at, "elo_v1", confidence,
            [OutcomeSpec("A", a.name, q), OutcomeSpec("B", b.name, 1 - q)], {"game_index": idx}))
    line = line or kills_line(stats)
    if line is not None and stats.games >= MIN_DRAFT_GAMES:
        mean = sum(stats.kill_totals) / len(stats.kill_totals)
        var = sum((k - mean) ** 2 for k in stats.kill_totals) / max(len(stats.kill_totals) - 1, 1)
        under = _nb_cdf(int(float(line)), mean, var)
        specs.append(MarketSpec(
            f"total_kills_game:{key}:{idx}:{line}", "total_kills_game", "GAME", "PROPS",
            f"Game {idx} total kills {line}",
            f"Combined kills by both teams in Game {idx}. Over means {int(float(line)) + 1} or more. {when} "
            f"Requires verified final game stats; void if Game {idx} is not played.",
            close_at, "negbin_tournament_v1", "EXPERIMENTAL",
            [OutcomeSpec("OVER", f"Over {line}", 1 - under), OutcomeSpec("UNDER", f"Under {line}", under)],
            {"game_index": idx, "line": line}))
    if stats.timeline is not None:
        from rift.props import objective_specs

        specs.extend(objective_specs(fixture, idx, a, b, q, stats.timeline, close_at, when))
    return specs


def next_game(fixture: Fixture, games: list[Game]) -> tuple[int, datetime] | None:
    """The game whose markets are open between games: (index, close_at), or None.

    Game N (N >= 2) opens once Game N-1's end is observed with its time known (the schedule says completed,
    or its final livestats frame is in), only while the series can still reach Game N. The series score
    must agree with the completed games; a game seen ending in livestats before the score counts it opens
    the next game only if that game is reachable whoever won.
    """
    need = fixture.best_of // 2 + 1
    if fixture.best_of == 1 or fixture.status != "LIVE":
        return None
    done = sorted((g for g in games if g.state == "completed" or (g.ended_at is not None and g.state != "unneeded")),
                  key=lambda g: g.game_index)
    n = len(done) + 1
    if not done or [g.game_index for g in done] != list(range(1, n)) or n > fixture.best_of:
        return None
    scored = sum(1 for g in done if g.state == "completed")
    unscored = len(done) - scored
    a, b = fixture.team_a_wins, fixture.team_b_wins
    if a + b != scored or unscored > 1 or max(a, b) + unscored >= need:
        return None
    nxt = next((g for g in games if g.game_index == n), None)
    if nxt is not None and (nxt.state != "unstarted" or nxt.started_at is not None):
        return None
    if done[-1].ended_at is None:
        return None
    return n, done[-1].ended_at + NEXT_GAME_WINDOW


def fixture_specs(fixture: Fixture, a: Team, b: Team, model: EloModel, stats: TournamentStats,
                  confidence: str, lines: dict[int, str] | None = None) -> list[MarketSpec]:
    q = model.game_probability(a.id, b.id)
    bo = fixture.best_of
    key = fixture.provider_id
    fmt = f"Bo{bo}"
    specs = [MarketSpec(
        f"series_winner:{key}", "series_winner", "SERIES", "WINNER", "Match winner",
        f"Settles on the official {fmt} series winner. Locks at the scheduled start. Void if the series is "
        "cancelled or not completed.",
        fixture.scheduled_at, "elo_v1", confidence,
        [OutcomeSpec("A", a.name, series_win_probability(q, bo)),
         OutcomeSpec("B", b.name, 1 - series_win_probability(q, bo))], {})]
    if bo > 1:
        dist = series_score_distribution(q, bo)
        order = sorted(dist, key=lambda s: (-(s[0] > s[1]), -(s[0] - s[1])))
        specs.append(MarketSpec(
            f"series_score:{key}", "series_score", "SERIES", "WINNER", "Exact series score",
            f"Settles on the final {fmt} score (games won). Void if the series is not completed.",
            fixture.scheduled_at, "elo_v1_independent_games", confidence,
            [OutcomeSpec(f"{x}-{y}", f"{a.code if x > y else b.code} {max(x, y)}–{min(x, y)}", dist[(x, y)])
             for x, y in order], {}))
        totals = total_games_distribution(q, bo)
        specs.append(MarketSpec(
            f"total_games:{key}", "total_games", "SERIES", "WINNER", "Games played",
            f"Number of games played in the {fmt}. Void if the series is not completed.",
            fixture.scheduled_at, "elo_v1_independent_games", confidence,
            [OutcomeSpec(str(n), f"{n} games", p) for n, p in sorted(totals.items())], {}))
    specs.extend(game_specs(fixture, 1, a, b, q, stats, fixture.scheduled_at, confidence, (lines or {}).get(1)))

    # Champion markets are created on demand from the champion grid (rift.draft), not pre-picked here.
    return specs


def futures_specs(season: Season, fixtures: list[Fixture], teams: dict, sim: FuturesProbabilities) -> list[MarketSpec]:
    swiss_start = min((f.scheduled_at for f in fixtures if f.stage == "Swiss"), default=None)
    qf_start = min((f.scheduled_at for f in fixtures if f.stage == "Quarterfinals"), default=None)
    specs = []
    if qf_start:
        champ = normalise({str(t): max(p, 1e-9) for t, p in sim.champion.items()})
        specs.append(MarketSpec(
            "tournament_winner", "tournament_winner", "TOURNAMENT", "FUTURES", "Worlds 2026 champion",
            "Settles on the winner of the Worlds 2026 final. Locks when the quarterfinals begin.",
            qf_start, "elo_v1_bracket_sim", "EXPERIMENTAL",
            [OutcomeSpec(teams[t].provider_id, teams[t].name, champ[str(t)])
             for t in sorted(sim.champion, key=lambda t: -sim.champion[t])], {}))
    if swiss_start:
        for t, p in sorted(sim.advance.items(), key=lambda kv: -kv[1]):
            team = teams[t]
            specs.append(MarketSpec(
                f"swiss_record:{team.provider_id}", "swiss_record", "STAGE", "FUTURES",
                f"{team.name} Swiss record",
                f"Pick {team.name}'s final Swiss record. Exact record pays the full price. Right side but wrong "
                "record (advanced, or eliminated) pays a quarter of the full return. Locks before the first "
                "Swiss match.",
                swiss_start, "elo_v1_bracket_sim_record", "EXPERIMENTAL",
                swiss_record_outcomes(sim.records[t]),
                {"team": team.provider_id, "consolation": str(SWISS_CONSOLATION)}))
    return specs


SWISS_RECORDS = ("3-0", "3-1", "3-2", "2-3", "1-3", "0-3")
SWISS_CONSOLATION = Decimal("0.25")


def swiss_side(record: str) -> str:
    return "ADVANCE" if record.startswith("3") else "OUT"


def swiss_record_outcomes(dist: dict[str, float]) -> list[OutcomeSpec]:
    """Price each record so exact pays odds and same-side pays odds x consolation at fair value.

    odds = 1 / (P(exact) + c * P(same side, other record)), expressed as the effective probability
    the generic pricer turns into odds.
    """
    c = float(SWISS_CONSOLATION)
    out = []
    for r in SWISS_RECORDS:
        exact = dist.get(r, 0.0)
        side = sum(p for k, p in dist.items() if k != r and swiss_side(k) == swiss_side(r))
        out.append(OutcomeSpec(r, r.replace("-", "–"), exact + c * side if exact > 0 else 0.0))
    return out


def upsert_market(session: Session, season: Season, fixture: Fixture | None, spec: MarketSpec,
                  settings: Settings, now: datetime) -> Market | None:
    market = session.execute(
        select(Market).where(Market.season_id == season.id, Market.template_key == spec.template_key)
    ).scalar_one_or_none()
    if market is None:
        if spec.close_at <= now:
            return None
        market = Market(season_id=season.id, fixture_id=fixture.id if fixture else None,
                        template_key=spec.template_key, kind=spec.kind, scope=spec.scope, category=spec.category,
                        title=spec.title, rules_text=spec.rules_text, params=spec.params, model_key=spec.model_key,
                        confidence=spec.confidence, close_at=spec.close_at, state="OPEN")
        session.add(market)
        session.flush()
    elif market.state != "OPEN":
        return market
    else:
        market.close_at = spec.close_at  # follows reschedules; lock_due() closes anything now past due
        market.confidence = spec.confidence
    reprice(session, market, spec, settings)
    return market


def reprice(session: Session, market: Market, spec: MarketSpec, settings: Settings) -> bool:
    existing = {o.code: o for o in session.execute(select(Outcome).where(Outcome.market_id == market.id)).scalars()}
    changed = False
    for i, os in enumerate(spec.outcomes):
        odds = price(os.probability, min_probability=Decimal(settings.min_probability),
                     max_odds=Decimal(settings.max_decimal_odds))
        outcome = existing.get(os.code)
        is_new = outcome is None
        if is_new:
            outcome = Outcome(market_id=market.id, code=os.code, label=os.label, sort=i, odds_version=0)
            session.add(outcome)
            session.flush()
        outcome.label, outcome.sort = os.label, i
        if is_new or outcome.odds != odds:
            version = session.execute(
                select(OddsSnapshot.version).where(OddsSnapshot.outcome_id == outcome.id)
                .order_by(OddsSnapshot.version.desc()).limit(1)
            ).scalar_one_or_none() or 0
            prob = Decimal(str(round(os.probability, 8)))
            session.add(OddsSnapshot(outcome_id=outcome.id, version=version + 1, odds=odds, probability=prob,
                                     model_key=spec.model_key))
            outcome.odds = odds
            outcome.probability = prob
            outcome.odds_version = version + 1 if odds is not None else 0
            changed = True
    if changed:
        session.add(OutboxEvent(type="market.odds_updated", entity_id=str(market.id), payload={}))
        session.flush()
    return changed


def retire_kind(session: Session, kind: str, reason: str, template_prefix: str | None = None) -> int:
    """Stop offering a market family. Accepted picks stay valid; markets lock and settle as before."""
    q = select(Market).where(Market.kind == kind, Market.state == "OPEN")
    if template_prefix:
        q = q.where(Market.template_key.startswith(template_prefix))
    rows = session.execute(q.with_for_update()).scalars().all()
    for m in rows:
        m.state, m.state_reason = "SUSPENDED", reason
        session.add(AuditEvent(actor="system", action="market.suspended", entity_type="market",
                               entity_id=str(m.id), data={"reason": reason}))
    session.flush()
    return len(rows)


def pinned_lines(session: Session, fixture: Fixture) -> dict[int, str]:
    """Kill lines already offered per game index, so re-pricing keeps one market per game."""
    rows = session.execute(select(Market.params).where(Market.fixture_id == fixture.id,
                                                       Market.kind == "total_kills_game")).scalars()
    return {p["game_index"]: p["line"] for p in rows if "game_index" in p and "line" in p}


def game_index(market: Market) -> int | None:
    idx = (market.params or {}).get("game_index") if market.scope == "GAME" else None
    return idx if isinstance(idx, int) else None


def lock_due(session: Session, now: datetime) -> int:
    """Lock markets at their cutoff, or earlier when what they predict has started.

    Series markets and Game 1 lock the moment the series is live. A Game N (N >= 2) market opens while the
    series is live, so it locks only at its own cutoff, when its game is seen in progress, or when the
    series is over.
    """
    locked: dict = {}
    for m in session.execute(
        select(Market).where(Market.state.in_(("OPEN", "SUSPENDED")), Market.close_at <= now).with_for_update()
    ).scalars():
        locked[m.id] = (m, f"Locked before Game {game_index(m)} draft" if (game_index(m) or 0) > 1 else
                        "Locked at series start" if m.fixture_id else "Locked")
    live = session.execute(
        select(Market, Fixture).join(Fixture, Fixture.id == Market.fixture_id)
        .where(Market.state == "OPEN", Fixture.status.in_(("LIVE", "COMPLETED")))
        .with_for_update(of=Market)
    ).all()
    fixture_ids = {f.id for _m, f in live}
    games = {(g.fixture_id, g.game_index): g for g in session.execute(select(Game).where(
        Game.fixture_id.in_(fixture_ids))).scalars()} if fixture_ids else {}
    for m, f in live:
        idx = game_index(m)
        g = games.get((f.id, idx))
        if idx is None or idx == 1:
            reason = "Locked at series start"
        elif g is not None and (g.state in ("inProgress", "completed") or g.started_at is not None):
            reason = f"Locked at Game {idx} start"
        elif f.status != "LIVE" or (g is not None and g.state == "unneeded"):
            reason = "Series over"
        else:
            continue
        locked.setdefault(m.id, (m, reason))
    for m, reason in locked.values():
        m.state, m.state_reason = "LOCKED", reason
        session.add(OutboxEvent(type="market.locked", entity_id=str(m.id), payload={}))
    session.flush()
    return len(locked)
