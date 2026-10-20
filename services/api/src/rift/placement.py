"""Quote → ticket flow (docs/spec/09_API_CONTRACTS.md). The server never trusts client odds or balances."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rift import ledger
from rift.domain.money import partial_return, winning_return
from rift.models import Fixture, Market, OutboxEvent, Outcome, Quote, Selection, Ticket, Wallet


class PlacementError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass
class QuoteItem:
    outcome_id: uuid.UUID
    stake_rc: int


def _wallet(session: Session, season_id: uuid.UUID, user_id: uuid.UUID) -> Wallet:
    wallet = session.execute(
        select(Wallet).where(Wallet.season_id == season_id, Wallet.user_id == user_id)
    ).scalar_one_or_none()
    if wallet is None:
        raise PlacementError("NOT_A_MEMBER", "You have not joined this season.")
    return wallet


def _check_open(session: Session, market: Market, outcome: Outcome, now: datetime) -> None:
    if market.params.get("early"):
        from rift.props import early_window

        fixture = session.get(Fixture, market.fixture_id)
        if fixture is None or not early_window(session, fixture, market.params["game_index"], now).open:
            raise PlacementError("MARKET_CLOSED", "This early-game window has closed.",
                                 {"market_id": str(market.id)})
    if market.state != "OPEN" or market.close_at <= now:
        raise PlacementError("MARKET_CLOSED", "This prediction is no longer open.",
                             {"market_id": str(market.id), "closed_at": market.close_at.isoformat()})
    if outcome.odds_version == 0 or outcome.odds is None:
        raise PlacementError("OUTCOME_UNAVAILABLE", "This outcome is not currently offered.",
                             {"outcome_id": str(outcome.id)})


def create_quote(session: Session, *, season_id: uuid.UUID, user_id: uuid.UUID, items: list[QuoteItem],
                 now: datetime, ttl_seconds: int) -> dict:
    if not items:
        raise PlacementError("EMPTY_SLIP", "Add at least one pick.")
    if any(i.stake_rc <= 0 for i in items):
        raise PlacementError("INVALID_STAKE", "Stakes must be whole RC above zero.")
    outcome_ids = [i.outcome_id for i in items]
    if len(set(outcome_ids)) != len(outcome_ids):
        raise PlacementError("DUPLICATE_OUTCOME", "Each outcome can appear once per slip.")
    rows = session.execute(
        select(Outcome, Market).join(Market, Market.id == Outcome.market_id)
        .where(Outcome.id.in_(outcome_ids), Market.season_id == season_id)
    ).all()
    found = {o.id: (o, m) for o, m in rows}
    missing = [str(i) for i in outcome_ids if i not in found]
    if missing:
        raise PlacementError("UNKNOWN_OUTCOME", "One of these picks no longer exists.", {"outcome_ids": missing})
    markets_seen: set[uuid.UUID] = set()
    out_items = []
    for item in items:
        outcome, market = found[item.outcome_id]
        if market.id in markets_seen:
            raise PlacementError("CONFLICTING_PICKS", "Choose one outcome per market on a slip.",
                                 {"market_id": str(market.id)})
        markets_seen.add(market.id)
        _check_open(session, market, outcome, now)
        out_items.append({
            "outcome_id": str(outcome.id), "market_id": str(market.id), "stake_rc": item.stake_rc,
            "odds": str(outcome.odds.quantize(Decimal("0.01"))), "odds_version": outcome.odds_version,
            "potential_return_rc": winning_return(item.stake_rc, outcome.odds),
            "partial_return_rc": partial_return(item.stake_rc, outcome.odds, market.params["consolation"])
            if market.params.get("consolation") else None,
            "market_title": market.title, "outcome_label": outcome.label,
        })
    total = sum(i.stake_rc for i in items)
    wallet = _wallet(session, season_id, user_id)
    quote = Quote(user_id=user_id, season_id=season_id, items=out_items, total_stake_rc=total,
                  expires_at=now + timedelta(seconds=ttl_seconds))
    session.add(quote)
    session.flush()
    return quote_view(quote, wallet.available_rc)


def quote_view(quote: Quote, available_rc: int) -> dict:
    return {
        "quote_id": str(quote.id),
        "expires_at": quote.expires_at.isoformat(),
        "total_stake_rc": quote.total_stake_rc,
        "available_rc": available_rc,
        "available_after_rc": available_rc - quote.total_stake_rc,
        "conditional_return_if_all_win_rc": sum(i["potential_return_rc"] for i in quote.items),
        "items": quote.items,
    }


def accept_ticket(session: Session, *, season_id: uuid.UUID, user_id: uuid.UUID, quote_id: uuid.UUID,
                  confirm_odds_versions: dict[str, int], idempotency_key: str,
                  now: datetime) -> tuple[Ticket, bool]:
    """Atomically validate and accept. Returns (ticket, created). Replays return the original ticket."""
    if not idempotency_key or len(idempotency_key) > 100:
        raise PlacementError("BAD_IDEMPOTENCY_KEY", "A valid Idempotency-Key header is required.")
    existing = _existing_ticket(session, season_id, user_id, idempotency_key)
    if existing:
        return existing, False

    quote = session.execute(
        select(Quote).where(Quote.id == quote_id, Quote.user_id == user_id, Quote.season_id == season_id)
        .with_for_update()
    ).scalar_one_or_none()
    if quote is None:
        raise PlacementError("UNKNOWN_QUOTE", "That quote was not found.")
    used = session.execute(select(Ticket).where(Ticket.quote_id == quote.id)).scalar_one_or_none()
    if used is not None:
        if used.idempotency_key == idempotency_key:
            return used, False
        raise PlacementError("QUOTE_USED", "That quote has already been placed.")

    # Lock order: markets (by id) → wallet. Settlement uses the same order.
    market_ids = sorted({uuid.UUID(i["market_id"]) for i in quote.items})
    markets = {m.id: m for m in session.execute(
        select(Market).where(Market.id.in_(market_ids)).order_by(Market.id).with_for_update(read=True)
    ).scalars()}
    outcomes = {o.id: o for o in session.execute(
        select(Outcome).where(Outcome.id.in_([uuid.UUID(i["outcome_id"]) for i in quote.items]))
    ).scalars()}

    changed = []
    for item in quote.items:
        outcome = outcomes[uuid.UUID(item["outcome_id"])]
        market = markets[uuid.UUID(item["market_id"])]
        _check_open(session, market, outcome, now)
        confirmed = confirm_odds_versions.get(item["outcome_id"])
        if outcome.odds_version != item["odds_version"] or confirmed != item["odds_version"]:
            changed.append(item["outcome_id"])
    if changed:
        # The caller re-quotes in a fresh transaction (this one rolls back) and returns both versions.
        raise PlacementError("ODDS_CHANGED", "Odds changed. Review the new prices.",
                             {"outcome_ids": changed, "previous_items": quote.items})
    if quote.expires_at <= now:
        raise PlacementError("QUOTE_EXPIRED", "That quote expired. Review the current prices.")

    wallet = ledger.lock_wallet(session, _wallet(session, season_id, user_id).id)
    if quote.total_stake_rc > wallet.available_rc:
        raise PlacementError("INSUFFICIENT_CREDITS",
                             f"Available {wallet.available_rc:,} RC; your slip needs {quote.total_stake_rc:,} RC.",
                             {"available_rc": wallet.available_rc, "required_rc": quote.total_stake_rc})

    ticket = Ticket(user_id=user_id, season_id=season_id, quote_id=quote.id, idempotency_key=idempotency_key,
                    total_stake_rc=quote.total_stake_rc, accepted_at=now)
    session.add(ticket)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        # A concurrent request with the same key won the race; return its ticket.
        winner = _existing_ticket(session, season_id, user_id, idempotency_key)
        if winner is None:
            raise
        return winner, False
    for item in quote.items:
        market = markets[uuid.UUID(item["market_id"])]
        outcome = outcomes[uuid.UUID(item["outcome_id"])]
        session.add(Selection(
            ticket_id=ticket.id, user_id=user_id, market_id=market.id, outcome_id=outcome.id,
            stake_rc=item["stake_rc"], odds=outcome.odds, odds_version=outcome.odds_version,
            rule_version=market.rule_version,
            rules_snapshot={"title": market.title, "rules": market.rules_text, "kind": market.kind,
                            "params": market.params, "outcome": outcome.label, "outcome_code": outcome.code,
                            "close_at": market.close_at.isoformat()},
        ))
    ledger.debit_stake(session, wallet, amount_rc=quote.total_stake_rc, key=f"stake:{ticket.id}",
                       ref_id=str(ticket.id), memo=f"{len(quote.items)} pick(s)")
    session.add(OutboxEvent(type="ticket.accepted", entity_id=str(ticket.id), user_id=user_id, payload={}))
    session.flush()
    return ticket, True


def _existing_ticket(session: Session, season_id: uuid.UUID, user_id: uuid.UUID, key: str) -> Ticket | None:
    return session.execute(
        select(Ticket).where(Ticket.user_id == user_id, Ticket.season_id == season_id,
                             Ticket.idempotency_key == key)
    ).scalar_one_or_none()
