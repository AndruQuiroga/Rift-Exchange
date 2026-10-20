"""Read models for the web client. Pure functions of the database; no business rules here."""

import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rift.domain.money import partial_return, winning_return
from rift.models import (
    Fixture,
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

CENT = Decimal("0.01")


def team_view(team: Team | None) -> dict | None:
    if team is None:
        return None
    return {"id": str(team.id), "code": team.code, "name": team.name, "image_url": team.image_url,
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


def events(db: Session, season: Season, date: str | None, stage: str | None) -> list[dict]:
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
                    "close_at": featured.close_at.isoformat() if featured else None,
                    "featured": market_view(featured, outcomes[featured.id], results.get(featured.id))
                    if featured else None})
    return out


def event_detail(db: Session, fixture: Fixture) -> dict:
    teams = _teams(db, [fixture.team_a_id, fixture.team_b_id])
    markets = list(db.execute(select(Market).where(Market.fixture_id == fixture.id).order_by(Market.created_at))
                   .scalars())
    outcomes = _outcomes_by_market(db, [m.id for m in markets])
    results = _latest_results(db, [m.id for m in markets])
    order = {"WINNER": 0, "DRAFT": 1, "PROPS": 2}
    markets.sort(key=lambda m: (order.get(m.category, 9), m.created_at))
    return {**fixture_view(fixture, teams),
            "markets": [market_view(m, outcomes[m.id], results.get(m.id)) for m in markets]}


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


def selection_rows(db: Session, selections: list[Selection]) -> list[dict]:
    markets = {m.id: m for m in db.execute(select(Market).where(
        Market.id.in_({s.market_id for s in selections}))).scalars()} if selections else {}
    fixtures = {f.id: f for f in db.execute(select(Fixture).where(
        Fixture.id.in_({m.fixture_id for m in markets.values() if m.fixture_id}))).scalars()} if markets else {}
    teams = _teams(db, [t for f in fixtures.values() for t in (f.team_a_id, f.team_b_id)])
    tickets = {t.id: t for t in db.execute(select(Ticket).where(
        Ticket.id.in_({s.ticket_id for s in selections}))).scalars()} if selections else {}
    out = []
    for s in selections:
        m = markets[s.market_id]
        f = fixtures.get(m.fixture_id) if m.fixture_id else None
        out.append({
            "id": str(s.id), "ticket_id": str(s.ticket_id), "status": s.status, "stake_rc": s.stake_rc,
            "odds": str(s.odds.quantize(CENT)), "return_rc": s.return_rc,
            "potential_return_rc": winning_return(s.stake_rc, s.odds),
            "partial_return_rc": partial_return(s.stake_rc, s.odds, s.rules_snapshot["params"]["consolation"])
            if s.rules_snapshot.get("params", {}).get("consolation") else None,
            "market_title": s.rules_snapshot.get("title"), "outcome_label": s.rules_snapshot.get("outcome"),
            "market_state": m.state, "market_state_reason": m.state_reason, "settled_revision": s.settled_revision,
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


def activity(db: Session, season: Season, limit: int = 50) -> list[dict]:
    """Friends' picks, but only once the market has locked (A-010)."""
    q = (select(Selection).join(Market, Market.id == Selection.market_id)
         .join(Ticket, Ticket.id == Selection.ticket_id)
         .where(Market.season_id == season.id, Market.state != "OPEN", Market.state != "SUSPENDED")
         .order_by(Ticket.accepted_at.desc()).limit(limit))
    selections = list(db.execute(q).scalars())
    users = {u.id: u for u in db.execute(select(User)).scalars()}
    rows = selection_rows(db, selections)
    for row, sel in zip(rows, selections, strict=True):
        row["user"] = {"handle": users[sel.user_id].handle, "display_name": users[sel.user_id].display_name}
    return rows
