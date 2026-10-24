"""Quote → ticket flow (docs/spec/09_API_CONTRACTS.md). The server never trusts client odds or balances."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rift import ledger
from rift.domain.money import partial_return, winning_return
from rift.domain.pricing import AFTER_DRAFT_RATE
from rift.models import Fixture, Market, OutboxEvent, Outcome, Quote, Selection, Ticket, Wallet


class PlacementError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


KNOCKOUT_STAGES = ("Quarterfinals", "Semifinals", "Finals")


def stake_cap(session: Session, market: Market, cap_rc: int) -> int | None:
    """The most one player may stake on this market in total, or None when it is uncapped.

    Capped: everything in the Swiss stage, and anything you can still pick after seeing the draft (game
    winners, objectives, early-window races, duels and kill lines). From the quarterfinals, predictions that
    close before the draft (series winner, exact score, champion calls) are uncapped for catch-up plays.
    """
    fixture = session.get(Fixture, market.fixture_id) if market.fixture_id else None
    after_draft = bool(market.params.get("through_draft") or market.params.get("early"))
    if fixture is not None and fixture.stage in KNOCKOUT_STAGES and not after_draft:
        return None
    return cap_rc


def _check_cap(session: Session, market: Market, user_id: uuid.UUID, stake_rc: int, cap_rc: int) -> None:
    cap = stake_cap(session, market, cap_rc)
    if cap is None:
        return
    placed = session.execute(select(func.coalesce(func.sum(Selection.stake_rc), 0)).where(
        Selection.market_id == market.id, Selection.user_id == user_id,
        Selection.status.notin_(("VOID", "CANCELLED")))).scalar()
    room = max(cap - int(placed), 0)
    if stake_rc > room:
        raise PlacementError(
            "STAKE_LIMIT",
            f"{market.title}: {cap:,} RC total limit across all bets on this market. "
            f"You already have {int(placed):,} RC staked; you can add {room:,} RC more.",
            {"market_id": str(market.id), "market_title": market.title, "cap_rc": cap,
             "placed_rc": int(placed), "max_stake_rc": room, "requested_stake_rc": stake_rc})


def _check_caps(session: Session, items: list[tuple[Market, int]], user_id: uuid.UUID, cap_rc: int) -> None:
    violations = []
    for market, stake in items:
        try:
            _check_cap(session, market, user_id, stake, cap_rc)
        except PlacementError as error:
            if error.code != "STAKE_LIMIT":
                raise
            violations.append({**error.details, "message": error.message})
    if violations:
        message = violations[0]["message"] if len(violations) == 1 else \
            f"{len(violations)} picks exceed their market's total stake limit. No bets were placed."
        raise PlacementError("STAKE_LIMIT", message, {**violations[0], "violations": violations})


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
    if market.kind == "swiss_record":
        raise PlacementError("USE_RECORD_CARD", "Swiss record calls are free: make them on the record card.",
                             {"market_id": str(market.id)})
    if market.params.get("early"):
        from rift.props import early_window

        fixture = session.get(Fixture, market.fixture_id)
        if fixture is None or not early_window(session, fixture, market.params["game_index"], now).open:
            raise PlacementError("MARKET_CLOSED", "This early-game window has closed.",
                                 {"market_id": str(market.id)})
    if market.params.get("through_draft") and market.fixture_id is not None:
        from rift.props import market_cutoff, market_game

        cutoff = market_cutoff(market, market_game(session, market))
        if cutoff is not None and now >= cutoff:  # the game passed 3:00 before the worker locked it
            raise PlacementError("MARKET_CLOSED", "First blood has happened, so this prediction is closed."
                                 if market.kind == "first_blood" and cutoff < market_game(session, market).started_at
                                 + timedelta(minutes=3) else "This prediction closed at 3:00 of the game.",
                                 {"market_id": str(market.id), "closed_at": cutoff.isoformat()})
    if market.state != "OPEN" or market.close_at <= now:
        raise PlacementError("MARKET_CLOSED", "This prediction is no longer open.",
                             {"market_id": str(market.id), "closed_at": market.close_at.isoformat()})
    if outcome.odds_version == 0 or outcome.odds is None:
        raise PlacementError("OUTCOME_UNAVAILABLE", "This outcome is not currently offered.",
                             {"outcome_id": str(outcome.id)})


def create_quote(session: Session, *, season_id: uuid.UUID, user_id: uuid.UUID, items: list[QuoteItem],
                 now: datetime, ttl_seconds: int, stake_cap_rc: int | None = None) -> dict:
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
        _check_blind_held(session, market, user_id)
        out_items.append({
            "outcome_id": str(outcome.id), "market_id": str(market.id), "stake_rc": item.stake_rc,
            "odds": str(outcome.odds.quantize(Decimal("0.01"))), "odds_version": outcome.odds_version,
            "potential_return_rc": winning_return(item.stake_rc, outcome.odds),
            "partial_return_rc": partial_return(item.stake_rc, outcome.odds, market.params["consolation"])
            if market.params.get("consolation") else None,
            "market_title": market.title, "outcome_label": outcome.label,
        })
    if stake_cap_rc is not None:
        _check_caps(session, [(found[i.outcome_id][1], i.stake_rc) for i in items], user_id, stake_cap_rc)
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
                  now: datetime, stake_cap_rc: int | None = None) -> tuple[Ticket, bool]:
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
        _check_blind_held(session, market, user_id)
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
    if stake_cap_rc is not None:  # under the wallet lock, so two slips at once can't both use the same room
        _check_caps(session, [(markets[uuid.UUID(i["market_id"])], i["stake_rc"]) for i in quote.items],
                    user_id, stake_cap_rc)
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


def timeline_market(market: Market) -> bool:
    """A game market on the D-040 timeline: blind before the draft, after-draft from game load to 3:00."""
    return bool(market.fixture_id and (market.params.get("blind") or market.params.get("early")
                                       or market.params.get("through_draft")))


def family(market: Market) -> tuple:
    """Blind and after-draft markets that predict the same thing (D-040): one bet per person across them.
    Kill lines share one family per game whatever the line; duels one per lane and stat."""
    p = market.params
    return (market.fixture_id, p.get("game_index"), market.kind,
            p.get("role") if market.kind == "lane_duel" else None, p.get("stat") if market.kind == "lane_duel" else None)


def _check_blind_held(session: Session, market: Market, user_id: uuid.UUID) -> None:
    """An after-draft bet needs no open blind bet on the same thing: cancel it first (75% back)."""
    if not market.params.get("early"):
        return
    held = session.execute(select(Market).join(Selection, Selection.market_id == Market.id).where(
        Selection.user_id == user_id, Selection.status == "OPEN", Market.fixture_id == market.fixture_id,
        Market.kind == market.kind)).scalars().all()
    if any(m.params.get("blind") and family(m) == family(market) for m in held):
        raise PlacementError("CALLED_BLIND", "You already called this blind. Cancel that bet (75% back) to bet "
                             "with the draft known.", {"market_id": str(market.id)})


def cancel_refund(session: Session, sel: Selection, market: Market, now: datetime, decided: bool | None = None) -> int | None:
    """What cancelling this pick returns right now, or None when it can't be cancelled (D-038, D-040).

    Most markets: the whole stake, until they lock. Game markets on the blind / after-draft timeline: the whole
    stake before the draft starts, then 75% until 3:00 of the game (first blood: until the first kill), never
    once the data has decided them. decided: whether a result or live call exists, if the caller knows.
    """
    if sel.status != "OPEN" or sel.settled_revision:
        return None
    fixture = session.get(Fixture, market.fixture_id) if market.fixture_id else None
    if not timeline_market(market):
        follows_game = (market.params.get("game_index") or 1) > 1
        started = fixture is not None and fixture.status != "SCHEDULED" and not follows_game
        if market.state != "OPEN" or market.close_at <= now or started:
            return None
        return sel.stake_rc
    from rift.draft import draft_window
    from rift.props import market_cutoff, market_game

    if market.state not in ("OPEN", "LOCKED", "SUSPENDED") or fixture is None or             fixture.status not in ("SCHEDULED", "LIVE"):
        return None
    game = market_game(session, market)
    if game is not None and (game.state in ("completed", "unneeded") or game.ended_at is not None):
        return None
    cutoff = market_cutoff(market, game)
    if cutoff is not None and now >= cutoff:
        return None
    if decided is None:
        from rift.calls import calls

        decided = market.id in calls(session, [market], 0)
    if decided:
        return None
    before_draft = not market.params.get("early") and         draft_window(session, fixture, market.params.get("game_index", 1), now).open
    return sel.stake_rc if before_draft else int(Decimal(sel.stake_rc) * AFTER_DRAFT_RATE)


def cancel_selection(session: Session, *, season_id: uuid.UUID, user_id: uuid.UUID, selection_id: uuid.UUID,
                     now: datetime) -> Selection:
    """Take back a pick (D-038, D-040): see cancel_refund for when and how much comes back. It never settles."""
    sel = session.execute(select(Selection).where(Selection.id == selection_id).with_for_update()).scalar_one_or_none()
    if sel is None or sel.user_id != user_id:
        raise PlacementError("UNKNOWN_PICK", "That pick doesn't exist.")
    market = session.execute(select(Market).where(Market.id == sel.market_id).with_for_update()).scalar_one()
    if market.season_id != season_id:
        raise PlacementError("UNKNOWN_PICK", "That pick doesn't exist.")
    if sel.status != "OPEN" or sel.settled_revision:
        raise PlacementError("NOT_CANCELLABLE", "That pick is already settled or cancelled.")
    refund = cancel_refund(session, sel, market, now)
    if refund is None:
        raise PlacementError("MARKET_LOCKED", "This can't be cancelled any more, so the pick stands.")
    wallet = session.execute(select(Wallet).where(Wallet.season_id == season_id, Wallet.user_id == user_id)
                             ).scalar_one()
    wallet = ledger.lock_wallets(session, {wallet.id})[wallet.id]
    if refund:
        ledger.credit(session, wallet, kind="VOID_REFUND", amount_rc=refund, key=f"cancel:{sel.id}",
                      ref_type="selection", ref_id=str(sel.id),
                      memo=f"Cancelled: {sel.rules_snapshot.get('title', '')}"
                      + ("" if refund == sel.stake_rc else f" ({refund:,} of {sel.stake_rc:,} RC back)"))
    sel.status, sel.settled_at, sel.return_rc = "CANCELLED", now, refund
    session.add(OutboxEvent(type="ticket.accepted", entity_id=str(sel.ticket_id), user_id=user_id,
                            payload={"cancelled": str(sel.id)}))
    session.flush()
    return sel
