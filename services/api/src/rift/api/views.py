"""Read models for the web client. Pure functions of the database; no business rules here."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from rift.calls import Call, calls
from rift.config import get_settings
from rift.display import relabel, team_name
from rift.domain.money import partial_return, refund_return, winning_return
from rift.markets import game_index, series_close
from rift.models import (
    Fixture,
    Game,
    LedgerEntry,
    Market,
    MarketResult,
    Outcome,
    Reaction,
    Season,
    Selection,
    SwissCall,
    Team,
    Ticket,
    User,
    Wallet,
)
from rift.placement import cancel_refund
from rift.props import early_state, early_window, phase
from rift.timeline import burned_champions

CENT = Decimal("0.01")


def team_view(team: Team | None) -> dict | None:
    if team is None:
        return None
    return {"id": str(team.id), "code": team.code, "name": team_name(team.code, team.name), "image_url": team.image_url,
            "region": team.region}


def outcome_view(o: Outcome) -> dict:
    return {"id": str(o.id), "code": o.code, "label": o.label,
            "odds": str(o.odds.quantize(CENT)) if o.odds is not None else None,
            "odds_version": o.odds_version,
            "probability": float(o.probability) if o.probability is not None else None}


def provisional_closes(db: Session, markets: list[Market]) -> dict[uuid.UUID, str]:
    """Markets whose close_at is only a backstop, and what really closes them, so the client says so instead of
    counting down: "game" (3:00 of game time, its game not loaded yet), "draft" (the series going live, D-037) or
    "next" (a later game's market while the game before it plays: its own draft, D-043)."""
    fixture_ids = {m.fixture_id for m in markets if m.fixture_id}
    if not fixture_ids:
        return {}
    fixtures = {f.id: f for f in db.execute(select(Fixture).where(Fixture.id.in_(fixture_ids))).scalars()}
    games = list(db.execute(select(Game).where(Game.fixture_id.in_(fixture_ids))).scalars())
    started = {(g.fixture_id, g.game_index) for g in games if g.started_at is not None}
    ended = {(g.fixture_id, g.game_index) for g in games if g.ended_at is not None or g.state == "completed"}
    out = {}
    for m in markets:
        f = fixtures.get(m.fixture_id)
        if f is None:
            continue
        idx = m.params.get("game_index", 1)
        if (m.params.get("through_draft") or m.params.get("early")) and (m.fixture_id, idx) not in started:
            out[m.id] = "game"
        elif f.status == "LIVE" and idx > 1 and (m.fixture_id, idx - 1) not in ended:
            out[m.id] = "next"  # D-043: open while the game before plays; closes at its own draft
        elif f.status == "SCHEDULED" and m.close_at >= series_close(f):
            out[m.id] = "draft"
    return out


def market_view(m: Market, outcomes: list[Outcome], result: MarketResult | None = None, call: Call | None = None,
                close_known: bool | str = True) -> dict:
    """close_known: True, or the rule that really closes it ("game" / "draft") when close_at is a backstop."""
    return {
        "id": str(m.id), "kind": m.kind, "scope": m.scope, "category": m.category, "title": m.title,
        "rules": m.rules_text, "state": m.state, "state_reason": m.state_reason, "close_at": m.close_at.isoformat(),
        "close_known": close_known is True,
        "close_rule": close_known if isinstance(close_known, str) else None,
        "confidence": m.confidence, "model": m.model_key, "params": m.params,
        "outcomes": [outcome_view(o) for o in sorted(outcomes, key=lambda o: o.sort)],
        "result": ({"void": result.void, "winning_codes": result.winning_codes, "reason": result.reason,
                    "revision": result.revision} if result else None),
        # The result as soon as the data shows it, before it pays (D-032); None once settled.
        "call": call.view() if call and not result else None,
    }


def _outcomes_by_market(db: Session, market_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Outcome]]:
    out: dict[uuid.UUID, list[Outcome]] = defaultdict(list)
    if market_ids:
        for o in db.execute(select(Outcome).where(Outcome.market_id.in_(market_ids))).scalars():
            out[o.market_id].append(o)
    return out


def _latest_results(db: Session, market_ids: list[uuid.UUID]) -> dict[uuid.UUID, MarketResult]:
    out = {}
    if market_ids:
        for r in db.execute(select(MarketResult).where(MarketResult.market_id.in_(market_ids))
                            .order_by(MarketResult.revision)).scalars():
            out[r.market_id] = r
    return out


def fixture_view(f: Fixture, teams: dict[uuid.UUID, Team]) -> dict:
    return {
        "id": str(f.id), "stage": f.stage, "best_of": f.best_of, "scheduled_at": f.scheduled_at.isoformat(),
        "local_date": f.local_date.isoformat(), "status": f.status,
        "team_a": team_view(teams.get(f.team_a_id)), "team_b": team_view(teams.get(f.team_b_id)),
        "score": [f.team_a_wins, f.team_b_wins],
        "winner": "A" if f.winner_team_id and f.winner_team_id == f.team_a_id else
                  "B" if f.winner_team_id and f.winner_team_id == f.team_b_id else None,
    }


def _teams(db: Session, ids) -> dict[uuid.UUID, Team]:
    ids = {i for i in ids if i}
    return {t.id: t for t in db.execute(select(Team).where(Team.id.in_(ids))).scalars()} if ids else {}


def _early_open(db: Session, fixture: Fixture, now: datetime | None) -> bool:
    """Whether duels and kill lines can be picked right now (the loaded game's first minutes)."""
    if now is None or fixture.status != "LIVE":
        return False
    game = current_game(_games(db, fixture))
    return bool(game and early_window(db, fixture, game.game_index, now).open)


def events(db: Session, season: Season, date: str | None, stage: str | None,
           now: datetime | None = None) -> list[dict]:
    q = select(Fixture).where(Fixture.season_id == season.id).order_by(Fixture.scheduled_at)
    if date:
        q = q.where(Fixture.local_date == datetime.fromisoformat(date).date())
    if stage:
        q = q.where(Fixture.stage == stage)
    fixtures = list(db.execute(q).scalars())
    teams = _teams(db, [t for f in fixtures for t in (f.team_a_id, f.team_b_id)])
    markets = list(db.execute(select(Market).where(Market.fixture_id.in_([f.id for f in fixtures]))).scalars()) \
        if fixtures else []
    outcomes = _outcomes_by_market(db, [m.id for m in markets])
    results = _latest_results(db, [m.id for m in markets])
    provisional = provisional_closes(db, markets)
    by_fixture: dict[uuid.UUID, list[Market]] = defaultdict(list)
    for m in markets:
        by_fixture[m.fixture_id].append(m)
    out = []
    for f in fixtures:
        fm = by_fixture.get(f.id, [])
        featured = next((m for m in fm if m.kind == "series_winner"), None)
        out.append({**fixture_view(f, teams),
                    "market_count": len(fm),
                    "categories": sorted({m.category for m in fm if m.state == "OPEN"}),
                    "early_open": _early_open(db, f, now),
                    "close_at": featured.close_at.isoformat() if featured else None,
                    "featured": market_view(featured, outcomes[featured.id], results.get(featured.id),
                                            close_known=provisional.get(featured.id, True))
                    if featured else None})
    return out


def event_detail(db: Session, fixture: Fixture, now: datetime) -> dict:
    teams = _teams(db, [fixture.team_a_id, fixture.team_b_id])
    markets = list(db.execute(select(Market).where(Market.fixture_id == fixture.id).order_by(Market.created_at))
                   .scalars())
    outcomes = _outcomes_by_market(db, [m.id for m in markets])
    results = _latest_results(db, [m.id for m in markets])
    order = {"WINNER": 0, "DRAFT": 1, "PROPS": 2}
    markets.sort(key=lambda m: (order.get(m.category, 9), m.created_at))
    called = calls(db, markets, _settle_delay())
    provisional = provisional_closes(db, markets)
    lanes = {i: phase(db, fixture, i, now).name for i in range(1, fixture.best_of + 1)}
    return {**fixture_view(fixture, teams),
            "games": [{**g, "lanes": lanes[g["index"]]} for g in games_view(fixture, _games(db, fixture), markets, now)],
            "markets": [market_view(m, outcomes[m.id], results.get(m.id), called.get(m.id),
                                    close_known=provisional.get(m.id, True)) for m in markets]}


def _games(db: Session, fixture: Fixture) -> list[Game]:
    return list(db.execute(select(Game).where(Game.fixture_id == fixture.id).order_by(Game.game_index)).scalars())


def _side(fixture: Fixture, team_id) -> str | None:
    return "A" if team_id and team_id == fixture.team_a_id else "B" if team_id and team_id == fixture.team_b_id \
        else None


def games_view(fixture: Fixture, games: list[Game], markets: list[Market], now: datetime) -> list[dict]:
    """Every game slot of the series with its betting window.

    OPEN: its markets take picks now. UPCOMING: they open later (`opens_when`). LOCKED: picks closed, game not
    finished. DONE: played. NOT_NEEDED: the series ended (or is decided) before this game.
    """
    by_index = {g.game_index: g for g in games}
    burned = burned_champions(games, fixture.best_of)
    need = fixture.best_of // 2 + 1
    decided = fixture.status == "COMPLETED" or max(fixture.team_a_wins, fixture.team_b_wins) >= need
    out = []
    for idx in range(1, fixture.best_of + 1):
        g = by_index.get(idx)
        scoped = [m for m in markets if game_index(m) == idx or (idx == 1 and game_index(m) is None)]
        open_ = [m for m in scoped if m.state == "OPEN" and m.close_at > now]
        played = g is not None and (g.state in ("inProgress", "completed") or g.started_at is not None)
        if g is not None and g.state == "completed":
            window = "DONE"
        elif fixture.status == "POSTPONED" and not played:
            window = "UPCOMING"
        elif (g is not None and g.state == "unneeded") or (not played and (decided or fixture.status == "CANCELED")):
            window = "NOT_NEEDED"
        elif open_:
            window = "OPEN"
        elif played or scoped or (idx == 1 and fixture.status != "SCHEDULED"):
            window = "LOCKED"
        else:
            window = "UPCOMING"
        opens_when = None
        if window == "UPCOMING":
            opens_when = f"When Game {idx - 1} starts" if idx > 1 else (
                "When both teams are known" if not (fixture.team_a_id and fixture.team_b_id) else None)
        closes = min((m.close_at for m in open_), default=None)
        early = early_state(fixture, g, idx, now)
        out.append({
            "index": idx, "state": g.state if g else "unstarted",
            "started_at": g.started_at.isoformat() if g and g.started_at else None,
            "ended_at": g.ended_at.isoformat() if g and g.ended_at else None,
            "winner": _side(fixture, g.winner_team_id) if g else None,
            "window": window, "opens_when": opens_when,
            "closes_at": closes.isoformat() if closes else None,
            # Duels and kill lines: UPCOMING until the game loads, OPEN until 3:00, then CLOSED.
            "early": early.state,
            "burned_champions": burned[idx],
        })
    return out


def _a_side(fixture: Fixture, game: Game | None) -> str | None:
    """Which side team A plays on in this game; None unless both sides are known and consistent."""
    if game is None or fixture.team_a_id is None or fixture.team_b_id is None:
        return None
    if (game.blue_team_id, game.red_team_id) == (fixture.team_a_id, fixture.team_b_id):
        return "blue"
    if (game.blue_team_id, game.red_team_id) == (fixture.team_b_id, fixture.team_a_id):
        return "red"
    return None


def _pair(a_side: str | None, by_side: dict | None) -> list | None:
    """[team A, team B] from a {blue, red} mapping."""
    if a_side is None or not by_side:
        return None
    return [by_side.get(a_side), by_side.get("red" if a_side == "blue" else "blue")]


def current_game(games: list[Game]) -> Game | None:
    """The game in progress, else the most recently started one."""
    live = [g for g in games if g.state == "inProgress" or (g.started_at and g.ended_at is None
                                                             and g.state != "completed")]
    if live:
        return max(live, key=lambda g: g.game_index)
    started = [g for g in games if g.started_at is not None or g.state == "completed"]
    return max(started, key=lambda g: g.game_index) if started else None


def live_view(db: Session, fixture: Fixture, user: User) -> dict:
    """Live scoreboard from what the worker stored on the games (never the feed itself)."""
    games = _games(db, fixture)
    game = current_game(games)
    tl = (game.timeline or {}) if game else {}
    live = tl.get("live") or {}
    a_side = _a_side(fixture, game)
    events = []
    if game is not None:
        side_code = {a_side: "A", {"blue": "red", "red": "blue"}[a_side]: "B"} if a_side else {}
        firsts = tl.get("firsts") or {}
        for name, kind in (("blood", "first_blood"), ("tower", "first_tower"), ("inhibitor", "inhibitor")):
            ev = firsts.get(name)
            if ev:
                events.append({"type": kind, "team": side_code.get(ev["side"]), "at_s": ev["at_s"], "detail": None})
        for d in tl.get("dragons") or []:
            events.append({"type": "dragon", "team": side_code.get(d["side"]), "at_s": d["at_s"], "detail": d["type"]})
        for b in tl.get("barons") or []:
            events.append({"type": "baron", "team": side_code.get(b["side"]), "at_s": b["at_s"], "detail": None})
        events.sort(key=lambda e: e["at_s"])
    markets = {m.id: m for m in db.execute(select(Market).where(Market.fixture_id == fixture.id)).scalars()}
    selections = list(db.execute(
        select(Selection).join(Ticket, Ticket.id == Selection.ticket_id)
        .where(Selection.user_id == user.id, Selection.market_id.in_(list(markets)), Selection.status != "CANCELLED")
        .order_by(Ticket.accepted_at)).scalars()) if markets else []
    picks = []
    by_index = {g.game_index: g for g in games}
    for row, sel in zip(selection_rows(db, selections), selections, strict=True):
        picks.append({**row, "live": pick_progress(fixture, markets[sel.market_id], by_index)})
    return {
        "status": fixture.status, "game_index": game.game_index if game else None,
        "game_state": live.get("state"), "as_of": live.get("at"),
        "game_clock_s": live.get("clock_s"),
        "gold": _pair(a_side, live.get("gold")), "kills": _pair(a_side, live.get("kills")),
        "towers": _pair(a_side, live.get("towers")), "dragons": _pair(a_side, live.get("dragons")),
        "events": events, "my_picks": picks,
    }


def game_kills(game: Game | None) -> int | None:
    """Kills so far in a game: verified final stats, else the latest live frame."""
    if game is None:
        return None
    if game.stats_complete and game.stats:
        return sum(p["kills"] for p in game.stats["players"])
    kills = ((game.timeline or {}).get("live") or {}).get("kills")
    return sum(kills.values()) if kills else None


def pick_progress(fixture: Fixture, market: Market, games: dict[int, Game]) -> dict | None:
    if market.kind in ("series_winner", "series_score"):
        return {"score": [fixture.team_a_wins, fixture.team_b_wins]}
    if market.kind == "total_kills_game":
        line = market.params["line"]
        current = game_kills(games.get(market.params["game_index"]))
        if current is None:
            return {"current": None, "line": line, "needed": None}
        return {"current": current, "line": line, "needed": max(int(float(line)) + 1 - current, 0)}
    return None


def season_markets(db: Session, season: Season, category: str | None) -> list[dict]:
    q = select(Market).where(Market.season_id == season.id, Market.fixture_id.is_(None))
    if category:
        q = q.where(Market.category == category)
    markets = list(db.execute(q.order_by(Market.close_at, Market.title)).scalars())
    outcomes = _outcomes_by_market(db, [m.id for m in markets])
    results = _latest_results(db, [m.id for m in markets])
    keys = {m.params["team"] for m in markets if m.params.get("team")}
    teams = {t.provider_id: t for t in db.execute(select(Team).where(Team.provider_id.in_(keys))).scalars()} \
        if keys else {}
    return [{**market_view(m, outcomes[m.id], results.get(m.id)),
             "team": team_view(teams.get(m.params.get("team", "")))} for m in markets]


# Picks that count toward net: settled ones, and cancels that kept part of the stake (D-040, the 25% after the
# draft starts). A full refund nets zero; cancels from before D-040 recorded no return and stay out.
_COUNTED = (Selection.status != "OPEN", or_(Selection.status != "CANCELLED", Selection.return_rc > 0))


def wallet_summary(db: Session, wallet: Wallet) -> dict:
    open_stake = db.execute(select(func.coalesce(func.sum(Selection.stake_rc), 0)).where(
        Selection.user_id == wallet.user_id, Selection.status == "OPEN")).scalar()
    sums = dict(db.execute(select(LedgerEntry.kind, func.sum(LedgerEntry.gross_rc))
                           .where(LedgerEntry.wallet_id == wallet.id).group_by(LedgerEntry.kind)).all())
    granted = int(sums.get("GRANT_OPENING", 0) + sums.get("GRANT_MATCH_DAY", 0))
    settled_stake = db.execute(select(func.coalesce(func.sum(Selection.stake_rc), 0)).where(
        Selection.user_id == wallet.user_id, *_COUNTED)).scalar()
    settled_return = db.execute(select(func.coalesce(func.sum(Selection.return_rc), 0)).where(
        Selection.user_id == wallet.user_id, *_COUNTED)).scalar()
    rewards = db.execute(select(func.coalesce(func.sum(SwissCall.reward_rc), 0)).where(
        SwissCall.user_id == wallet.user_id)).scalar()
    return {"available_rc": wallet.available_rc, "open_stake_rc": int(open_stake),
            "recovery_due_rc": wallet.recovery_due_rc, "granted_rc": granted,
            "realized_net_rc": int(settled_return) - int(settled_stake) + int(rewards),
            "today_net_rc": today_net(db, wallet)}


def venue_day(season: Season, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Today on the venue's calendar, as match days are: [start, end)."""
    tz = ZoneInfo(season.timezone)
    now = now or datetime.now(UTC)
    start = datetime.combine(now.astimezone(tz).date(), datetime.min.time(), tz)
    return start, start + timedelta(days=1)


def today_net(db: Session, wallet: Wallet, now: datetime | None = None) -> int:
    """What your picks settled today won or lost (return minus stake), plus Swiss card rewards: the venue's
    calendar day, as match days are. Grants don't count; cancels only for what they kept."""
    start, end = venue_day(db.get(Season, wallet.season_id), now)
    picks = db.execute(select(func.coalesce(func.sum(Selection.return_rc - Selection.stake_rc), 0)).where(
        Selection.user_id == wallet.user_id, *_COUNTED,
        Selection.settled_at >= start, Selection.settled_at < end)).scalar()
    rewards = db.execute(select(func.coalesce(func.sum(SwissCall.reward_rc), 0)).where(
        SwissCall.user_id == wallet.user_id, SwissCall.settled_at >= start, SwissCall.settled_at < end)).scalar()
    return int(picks) + int(rewards)


def ledger_view(db: Session, wallet: Wallet, limit: int = 100) -> list[dict]:
    rows = db.execute(select(LedgerEntry).where(LedgerEntry.wallet_id == wallet.id)
                      .order_by(LedgerEntry.id.desc()).limit(limit)).scalars()
    return [{"id": e.id, "kind": e.kind, "amount_rc": e.gross_rc, "available_delta_rc": e.available_delta,
             "memo": e.memo, "created_at": e.created_at.isoformat()} for e in rows]


def void_reason(s: Selection, m: Market, result: MarketResult | None, accepted_at: datetime | None = None) -> str | None:
    """Why a pick was void, in a few plain words for My Picks."""
    if s.status != "VOID":
        return None
    if m.kind == "swiss_record" and s.settled_revision == 0:
        return "Moved to the free record card · stake refunded"
    if result is None or not result.void:  # the market settled, but this pick came in after the real cutoff
        if (s.rules_snapshot.get("params") or {}).get("priced_at") and result and accepted_at:
            cutoff = (result.evidence or {}).get("acceptance_cutoff")
            if cutoff and accepted_at < datetime.fromisoformat(cutoff):  # in time, but on a stale live price
                return "A kill came before the price caught up"
        return "Placed after 3:00" if (m.params or {}).get("early") else "Placed after the start"
    reason = result.reason or ""
    if "not played" in reason:
        return reason.replace(" was not played", " not played")
    if "tie" in reason.lower():
        return "Tie"
    if reason == "Series cancelled":
        return "Match cancelled"
    if "did not play" in reason:
        return "A player didn't play"
    if "15:00" in reason:
        return "Game ended before 15:00"
    if "elemental" in reason:
        return "No elemental dragon"
    return "No verified result"


def swiss_records(db: Session, season_ids: set, teams) -> dict[str, str]:
    """team provider id -> its Swiss record so far ("2-1"), from completed Swiss series."""
    if not season_ids:
        return {}
    by_id = {t.id: t.provider_id for t in teams}
    record: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for f in db.execute(select(Fixture).where(Fixture.season_id.in_(season_ids), Fixture.stage == "Swiss",
                                              Fixture.status == "COMPLETED")).scalars():
        if f.winner_team_id is None:
            continue
        loser = f.team_b_id if f.winner_team_id == f.team_a_id else f.team_a_id
        record[by_id.get(f.winner_team_id)][0] += 1
        record[by_id.get(loser)][1] += 1
    return {pid: f"{w}-{lo}" for pid, (w, lo) in record.items() if pid}


def selection_rows(db: Session, selections: list[Selection]) -> list[dict]:
    markets = {m.id: m for m in db.execute(select(Market).where(
        Market.id.in_({s.market_id for s in selections}))).scalars()} if selections else {}
    fixtures = {f.id: f for f in db.execute(select(Fixture).where(
        Fixture.id.in_({m.fixture_id for m in markets.values() if m.fixture_id}))).scalars()} if markets else {}
    teams = _teams(db, [t for f in fixtures.values() for t in (f.team_a_id, f.team_b_id)])
    named = db.execute(select(Team)).scalars().all() if selections else []  # futures picks have no fixture
    swiss = swiss_records(db, {m.season_id for m in markets.values() if m.kind == "swiss_record"}, named)
    results = _latest_results(db, list(markets))
    tickets = {t.id: t for t in db.execute(select(Ticket).where(
        Ticket.id.in_({s.ticket_id for s in selections}))).scalars()} if selections else {}
    called = calls(db, [markets[s.market_id] for s in selections if s.status == "OPEN"], _settle_delay())
    provisional = provisional_closes(db, list(markets.values()))
    codes = {o.id: o.code for o in db.execute(select(Outcome).where(
        Outcome.id.in_({s.outcome_id for s in selections}))).scalars()} if selections else {}
    now = datetime.now(UTC)
    out = []
    for s in selections:
        m = markets[s.market_id]
        f = fixtures.get(m.fixture_id) if m.fixture_id else None
        out.append({
            "id": str(s.id), "ticket_id": str(s.ticket_id), "market_id": str(s.market_id),
            "outcome_id": str(s.outcome_id), "status": s.status, "stake_rc": s.stake_rc,
            "odds": str(s.odds.quantize(CENT)), "return_rc": s.return_rc,
            "potential_return_rc": winning_return(s.stake_rc, s.odds),
            "partial_return_rc": partial_return(s.stake_rc, s.odds, s.rules_snapshot["params"]["consolation"])
            if s.rules_snapshot.get("params", {}).get("consolation") else None,
            "kind": m.kind,
            "market_title": relabel(s.rules_snapshot.get("title"), named),
            "outcome_label": relabel(s.rules_snapshot.get("outcome"), named),
            "market_state": m.state, "market_state_reason": m.state_reason, "settled_revision": s.settled_revision,
            "void_reason": void_reason(s, m, results.get(m.id), tickets[s.ticket_id].accepted_at),
            "swiss_record": swiss.get(m.params.get("team"), "0-0") if m.kind == "swiss_record" else None,
            "accepted_at": tickets[s.ticket_id].accepted_at.isoformat(),
            "settled_at": s.settled_at.isoformat() if s.settled_at else None,
            "event": fixture_view(f, teams) if f else None,
            # How this pick stands on the latest data, before it pays (D-032).
            "call": _pick_call(called.get(m.id), codes.get(s.outcome_id)) if s.status == "OPEN" else None,
            "close_at": m.close_at.isoformat(),
            "close_known": m.id not in provisional,
            "close_rule": provisional.get(m.id),
            # Its close follows the game (3:00 of game time) rather than a fixed time until the game loads.
            "closes_with_game": bool(m.params.get("through_draft") or m.params.get("early")),
            # What cancelling returns right now (D-038, D-040), or None when it can't be cancelled.
            "cancel_refund_rc": cancel_refund(db, s, m, now, decided=m.id in called) if s.status == "OPEN" else None,
            "after_draft": bool(m.params.get("early")),
        })
    return out


def _pick_call(call: Call | None, code: str | None) -> dict | None:
    if call is None:
        return None
    result = ("VOID" if call.void else "WON" if code in call.codes else "PARTIAL" if code in call.partial
              else "LOST")
    return {"result": result, "final": call.final, "reason": call.reason,
            "pays_at": call.pays_at.isoformat() if call.pays_at else None,
            "pending_refund": call.pending_refund and result == "LOST"}


def _settle_delay() -> int:
    return get_settings().settle_delay_seconds


def my_selections(db: Session, user: User, state: str | None) -> list[dict]:
    q = select(Selection).where(Selection.user_id == user.id)
    if state == "open":
        q = q.where(Selection.status == "OPEN")
    elif state == "settled":
        q = q.where(Selection.status != "OPEN")
    q = q.join(Ticket, Ticket.id == Selection.ticket_id).order_by(Ticket.accepted_at.desc())
    return selection_rows(db, list(db.execute(q).scalars()))


def _record(db: Session, season: Season, user_id: uuid.UUID, since: datetime | None = None,
            until: datetime | None = None) -> tuple[int, int]:
    """(won, lost) of this season's settled picks: a win returned more than its stake, a loss returned nothing.
    Voids, cancels and half-back pushes count as neither. since/until: settled in that window."""
    q = (select(Selection.status, Selection.stake_rc, Selection.return_rc)
         .join(Market, Market.id == Selection.market_id)
         .where(Market.season_id == season.id, Selection.user_id == user_id,
                Selection.status.in_(("WON", "PARTIAL", "LOST"))))
    if since is not None:
        q = q.where(Selection.settled_at >= since, Selection.settled_at < until)
    rows = db.execute(q).all()
    return (sum(1 for st, stake, ret in rows if st != "LOST" and ret > stake),
            sum(1 for st, _stake, _ret in rows if st == "LOST"))


def standings(db: Session, season: Season, now: datetime | None = None) -> list[dict]:
    """Everyone's season and today. Ranked by bankroll (available plus in play), so a big open bet doesn't drop
    you down the table; today_rank orders the same rows by today's net."""
    wallets = list(db.execute(select(Wallet).where(Wallet.season_id == season.id)).scalars())
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_([w.user_id for w in wallets]))).scalars()}
    start, end = venue_day(season, now)
    rows = []
    for w in wallets:
        summary = {**wallet_summary(db, w), "today_net_rc": today_net(db, w, now)}
        won, lost = _record(db, season, w.user_id)
        won_today, lost_today = _record(db, season, w.user_id, start, end)
        rows.append({"user": {"id": str(w.user_id), "handle": users[w.user_id].handle,
                              "display_name": users[w.user_id].display_name}, **summary,
                     "bankroll_rc": summary["available_rc"] + summary["open_stake_rc"],
                     "won": won, "lost": lost, "won_today": won_today, "lost_today": lost_today})
    rows.sort(key=lambda r: -r["bankroll_rc"])
    for i, r in enumerate(rows):
        r["rank"] = 1 + sum(1 for o in rows if o["bankroll_rc"] > r["bankroll_rc"])
        r["today_rank"] = 1 + sum(1 for o in rows if o["today_net_rc"] > r["today_net_rc"])
        r["index"] = i
    open_markets = db.execute(select(func.count()).select_from(Selection).where(Selection.status == "OPEN")).scalar()
    for r in rows:
        r["provisional"] = bool(open_markets)
    return rows


def activity(db: Session, season: Season, limit: int = 50, fixture_id: uuid.UUID | None = None,
             exclude_user_id: uuid.UUID | None = None) -> list[dict]:
    """Friends' picks, but only once the market has locked (A-010). Optionally one match, without your own."""
    q = (select(Selection).join(Market, Market.id == Selection.market_id)
         .join(Ticket, Ticket.id == Selection.ticket_id)
         .where(Market.season_id == season.id, Market.state != "OPEN", Market.state != "SUSPENDED",
                Selection.status != "CANCELLED"))
    if fixture_id is not None:
        q = q.where(Market.fixture_id == fixture_id)
    if exclude_user_id is not None:
        q = q.where(Selection.user_id != exclude_user_id)
    q = q.order_by(Ticket.accepted_at.desc()).limit(limit)
    selections = list(db.execute(q).scalars())
    users = {u.id: u for u in db.execute(select(User)).scalars()}
    rows = selection_rows(db, selections)
    for row, sel in zip(rows, selections, strict=True):
        row["user"] = {"handle": users[sel.user_id].handle, "display_name": users[sel.user_id].display_name}
    return rows


def friends_pending(db: Session, season: Season, fixture_id: uuid.UUID, exclude_user_id: uuid.UUID) -> list[dict]:
    """Who else has picks on this match that are still hidden (A-010): a count each and when the first reveals."""
    rows = db.execute(
        select(Selection.user_id, func.count(Selection.id), func.min(Market.close_at))
        .join(Market, Market.id == Selection.market_id)
        .where(Market.season_id == season.id, Market.fixture_id == fixture_id,
               Market.state.in_(("OPEN", "SUSPENDED")), Selection.user_id != exclude_user_id,
               Selection.status != "CANCELLED")
        .group_by(Selection.user_id)).all()
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_([r[0] for r in rows]))).scalars()} \
        if rows else {}
    return sorted(({"user": {"handle": users[uid].handle, "display_name": users[uid].display_name},
                    "picks": n, "reveals_at": first.isoformat()} for uid, n, first in rows),
                  key=lambda r: r["user"]["display_name"])


# ------------------------------------------------------------------ rivals (D-034)

PHRASES = {"called_it": "Called it", "sweating": "You're sweating", "bold_call": "Bold call", "gg": "GG"}


def reactions_view(db: Session, fixture_id: uuid.UUID, limit: int = 40) -> list[dict]:
    rows = list(db.execute(select(Reaction).where(Reaction.fixture_id == fixture_id)
                           .order_by(Reaction.id.desc()).limit(limit)).scalars())
    if not rows:
        return []
    users = {u.id: u for u in db.execute(select(User).where(
        User.id.in_({r.from_user_id for r in rows} | {r.to_user_id for r in rows}))).scalars()}
    sels = {s.id: s for s in db.execute(select(Selection).where(
        Selection.id.in_({r.selection_id for r in rows}))).scalars()}
    person = lambda u: {"handle": u.handle, "display_name": u.display_name}
    return [{"id": r.id, "from": person(users[r.from_user_id]), "to": person(users[r.to_user_id]),
             "phrase": r.phrase, "text": PHRASES.get(r.phrase, r.phrase), "selection_id": str(r.selection_id),
             "pick": relabel(sels[r.selection_id].rules_snapshot.get("outcome"), []),
             "market": sels[r.selection_id].rules_snapshot.get("title"), "at": r.created_at.isoformat()}
            for r in rows]


def match_table(db: Session, season: Season, fixture_id: uuid.UUID, viewer_id: uuid.UUID) -> list[dict]:
    """Everyone's standing on one match right now: settled results plus what the data has already decided.
    Friends' picks count only once their market locks (A-010); your own always do."""
    q = (select(Selection).join(Market, Market.id == Selection.market_id)
         .where(Market.season_id == season.id, Market.fixture_id == fixture_id, Selection.status != "CANCELLED",
                (Selection.user_id == viewer_id) | Market.state.notin_(("OPEN", "SUSPENDED"))))
    selections = list(db.execute(q).scalars())
    if not selections:
        return []
    rows = selection_rows(db, selections)
    users = {u.id: u for u in db.execute(select(User).where(
        User.id.in_({s.user_id for s in selections}))).scalars()}
    table: dict[uuid.UUID, dict] = {}
    for sel, row in zip(selections, rows, strict=True):
        t = table.setdefault(sel.user_id, {"staked": 0, "back": 0, "decided": 0, "riding": 0, "won": 0, "lost": 0,
                                           "partial": 0, "picks": 0, "riding_return": 0})
        t["staked"] += sel.stake_rc
        t["picks"] += 1
        result = sel.status if sel.status != "OPEN" else (row["call"] or {}).get("result")
        if result is None:
            t["riding"] += sel.stake_rc
            t["riding_return"] += row["potential_return_rc"]
            continue
        t["decided"] += sel.stake_rc
        terms = sel.rules_snapshot.get("params", {})
        if sel.status != "OPEN":
            back = sel.return_rc
        elif result == "WON":
            back = row["potential_return_rc"]
        elif result == "VOID":
            back = sel.stake_rc
        elif result == "PARTIAL":
            refund = terms.get("ban_refund") or terms.get("void_refund")
            back = refund_return(sel.stake_rc, refund) if refund else row["partial_return_rc"] or 0
        else:
            back = 0
        t["back"] += back
        key = {"WON": "won", "LOST": "lost", "PARTIAL": "partial"}.get(result)
        if key:
            t[key] += 1
    out = [{"user": {"handle": users[uid].handle, "display_name": users[uid].display_name},
            "you": uid == viewer_id, **t, "net": t["back"] - t["decided"],
            # If every undecided pick wins: what is back so far plus their full returns, minus everything staked.
            "potential": t["back"] + t["riding_return"] - t["staked"]} for uid, t in table.items()]
    out.sort(key=lambda r: (-r["net"], -r["staked"]))
    for i, r in enumerate(out):
        r["rank"] = i + 1
    return out
