"""Read models for the web client. Pure functions of the database; no business rules here."""

import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rift.display import relabel, team_name
from rift.domain.money import partial_return, winning_return
from rift.markets import game_index
from rift.models import (
    Fixture,
    Game,
    LedgerEntry,
    Market,
    MarketResult,
    Outcome,
    Season,
    Selection,
    Team,
    Ticket,
    User,
    Wallet,
)
from rift.props import early_state, early_window
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


def market_view(m: Market, outcomes: list[Outcome], result: MarketResult | None = None) -> dict:
    return {
        "id": str(m.id), "kind": m.kind, "scope": m.scope, "category": m.category, "title": m.title,
        "rules": m.rules_text, "state": m.state, "state_reason": m.state_reason, "close_at": m.close_at.isoformat(),
        "confidence": m.confidence, "model": m.model_key, "params": m.params,
        "outcomes": [outcome_view(o) for o in sorted(outcomes, key=lambda o: o.sort)],
        "result": ({"void": result.void, "winning_codes": result.winning_codes, "reason": result.reason,
                    "revision": result.revision} if result else None),
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
                    "featured": market_view(featured, outcomes[featured.id], results.get(featured.id))
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
    return {**fixture_view(fixture, teams),
            "games": games_view(fixture, _games(db, fixture), markets, now),
            "markets": [market_view(m, outcomes[m.id], results.get(m.id)) for m in markets]}


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
            opens_when = f"When Game {idx - 1} ends" if idx > 1 else (
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
            # Duels and kill lines: UPCOMING until the game loads, OPEN until 3:00 or first blood, then CLOSED.
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
        .where(Selection.user_id == user.id, Selection.market_id.in_(list(markets)))
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


def wallet_summary(db: Session, wallet: Wallet) -> dict:
    open_stake = db.execute(select(func.coalesce(func.sum(Selection.stake_rc), 0)).where(
        Selection.user_id == wallet.user_id, Selection.status == "OPEN")).scalar()
    sums = dict(db.execute(select(LedgerEntry.kind, func.sum(LedgerEntry.gross_rc))
                           .where(LedgerEntry.wallet_id == wallet.id).group_by(LedgerEntry.kind)).all())
    granted = int(sums.get("GRANT_OPENING", 0) + sums.get("GRANT_MATCH_DAY", 0))
    settled_stake = db.execute(select(func.coalesce(func.sum(Selection.stake_rc), 0)).where(
        Selection.user_id == wallet.user_id, Selection.status != "OPEN")).scalar()
    settled_return = db.execute(select(func.coalesce(func.sum(Selection.return_rc), 0)).where(
        Selection.user_id == wallet.user_id, Selection.status != "OPEN")).scalar()
    return {"available_rc": wallet.available_rc, "open_stake_rc": int(open_stake),
            "recovery_due_rc": wallet.recovery_due_rc, "granted_rc": granted,
            "realized_net_rc": int(settled_return) - int(settled_stake)}


def ledger_view(db: Session, wallet: Wallet, limit: int = 100) -> list[dict]:
    rows = db.execute(select(LedgerEntry).where(LedgerEntry.wallet_id == wallet.id)
                      .order_by(LedgerEntry.id.desc()).limit(limit)).scalars()
    return [{"id": e.id, "kind": e.kind, "amount_rc": e.gross_rc, "available_delta_rc": e.available_delta,
             "memo": e.memo, "created_at": e.created_at.isoformat()} for e in rows]


def void_reason(s: Selection, m: Market, result: MarketResult | None) -> str | None:
    """Why a pick was void, in a few plain words for My Picks."""
    if s.status != "VOID":
        return None
    if result is None or not result.void:  # the market settled, but this pick came in after the real cutoff
        return "Placed after first blood or 3:00" if (m.params or {}).get("early") else "Placed after the start"
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
            "market_title": relabel(s.rules_snapshot.get("title"), named),
            "outcome_label": relabel(s.rules_snapshot.get("outcome"), named),
            "market_state": m.state, "market_state_reason": m.state_reason, "settled_revision": s.settled_revision,
            "void_reason": void_reason(s, m, results.get(m.id)),
            "swiss_record": swiss.get(m.params.get("team"), "0-0") if m.kind == "swiss_record" else None,
            "accepted_at": tickets[s.ticket_id].accepted_at.isoformat(),
            "settled_at": s.settled_at.isoformat() if s.settled_at else None,
            "event": fixture_view(f, teams) if f else None,
        })
    return out


def my_selections(db: Session, user: User, state: str | None) -> list[dict]:
    q = select(Selection).where(Selection.user_id == user.id)
    if state == "open":
        q = q.where(Selection.status == "OPEN")
    elif state == "settled":
        q = q.where(Selection.status != "OPEN")
    q = q.join(Ticket, Ticket.id == Selection.ticket_id).order_by(Ticket.accepted_at.desc())
    return selection_rows(db, list(db.execute(q).scalars()))


def standings(db: Session, season: Season) -> list[dict]:
    wallets = list(db.execute(select(Wallet).where(Wallet.season_id == season.id)).scalars())
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_([w.user_id for w in wallets]))).scalars()}
    rows = []
    for w in wallets:
        summary = wallet_summary(db, w)
        record = dict(db.execute(select(Selection.status, func.count()).where(Selection.user_id == w.user_id)
                                 .group_by(Selection.status)).all())
        rows.append({"user": {"id": str(w.user_id), "handle": users[w.user_id].handle,
                              "display_name": users[w.user_id].display_name}, **summary,
                     "won": record.get("WON", 0) + record.get("PARTIAL", 0), "lost": record.get("LOST", 0)})
    rows.sort(key=lambda r: -r["available_rc"])
    for i, r in enumerate(rows):
        r["rank"] = 1 + sum(1 for o in rows if o["available_rc"] > r["available_rc"])
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
         .where(Market.season_id == season.id, Market.state != "OPEN", Market.state != "SUSPENDED"))
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
