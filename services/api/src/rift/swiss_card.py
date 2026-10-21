"""The free Swiss record card (docs/spec/16 D-020).

Each player calls a final Swiss record for any team, free. A call locks the price at the moment it is
made; the reward is 100 RC x that price, capped at 1,000 RC, for the exact record, and a quarter of that
for the right side (advanced or out) with the wrong record. Rows per record are capped at what the stage
can produce: two 3-0s, three of each record in between, two 0-3s.
"""

import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from rift import ledger
from rift.models import Market, OutboxEvent, Outcome, Season, Selection, SwissCall, Team, Ticket, Wallet

REWARD_BASE_RC = 100
REWARD_CAP_RC = 1000
PARTIAL_SHARE = Decimal("0.25")
SLOTS = {"3-0": 2, "3-1": 3, "3-2": 3, "2-3": 3, "1-3": 3, "0-3": 2}


class CardError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def exact_reward(odds: Decimal) -> int:
    return min(_round(Decimal(REWARD_BASE_RC) * Decimal(odds)), REWARD_CAP_RC)


def reward(odds: Decimal, result: str) -> int:
    if result == "WON":
        return exact_reward(odds)
    if result == "PARTIAL":
        return _round(exact_reward(odds) * PARTIAL_SHARE)
    return 0


def _markets(session: Session, season: Season) -> list[Market]:
    return list(session.execute(select(Market).where(Market.season_id == season.id,
                                                     Market.kind == "swiss_record")).scalars())


def _codes(session: Session, market_ids) -> dict[uuid.UUID, str]:
    return dict(session.execute(select(Outcome.id, Outcome.code).where(Outcome.market_id.in_(market_ids))).all())


def card(session: Session, season: Season, user_id: uuid.UUID, now: datetime) -> dict:
    from rift.api.views import swiss_records

    markets = {m.id: m for m in _markets(session, season)}
    calls = list(session.execute(select(SwissCall).where(SwissCall.user_id == user_id,
                                                         SwissCall.market_id.in_(markets))).scalars())
    codes = _codes(session, list(markets)) if markets else {}
    teams = list(session.execute(select(Team).where(Team.provider_id.in_(
        [m.params.get("team") for m in markets.values()]))).scalars()) if markets else []
    records = swiss_records(session, {season.id}, teams)
    close_at = min((m.close_at for m in markets.values()), default=None)
    return {
        "open": any(m.state == "OPEN" and m.close_at > now for m in markets.values()),
        "close_at": close_at.isoformat() if close_at else None,
        "reward": {"base_rc": REWARD_BASE_RC, "cap_rc": REWARD_CAP_RC, "partial_share": str(PARTIAL_SHARE)},
        "slots": SLOTS,
        "calls": [{
            "market_id": str(c.market_id), "outcome_id": str(c.outcome_id), "record": codes[c.outcome_id],
            "odds": str(Decimal(c.odds).quantize(Decimal("0.01"))), "status": c.status, "reward_rc": c.reward_rc,
            "exact_rc": exact_reward(c.odds), "partial_rc": reward(c.odds, "PARTIAL"),
            "swiss_record": records.get(markets[c.market_id].params.get("team"), "0-0"),
        } for c in calls],
    }


def _open_market(session: Session, season: Season, market_id: uuid.UUID, now: datetime) -> Market:
    market = session.get(Market, market_id)
    if market is None or market.season_id != season.id or market.kind != "swiss_record":
        raise CardError("NOT_FOUND", "That isn't a Swiss record call.")
    if market.state != "OPEN" or market.close_at <= now:
        raise CardError("CARD_LOCKED", "Record calls are locked.")
    return market


def set_call(session: Session, season: Season, user_id: uuid.UUID, market_id: uuid.UUID,
             outcome_id: uuid.UUID, now: datetime) -> SwissCall:
    """Make or change a call at the current price. A full record row refuses one more team."""
    market = _open_market(session, season, market_id, now)
    outcome = session.get(Outcome, outcome_id)
    if outcome is None or outcome.market_id != market.id or outcome.odds is None or outcome.odds_version == 0:
        raise CardError("OUTCOME_UNAVAILABLE", "That record isn't offered right now.")
    # One row per user and record: lock the user's calls so two quick taps can't both fill the last slot.
    mine = list(session.execute(select(SwissCall).where(SwissCall.user_id == user_id).with_for_update()).scalars())
    codes = _codes(session, {c.market_id for c in mine} | {market.id})
    taken = sum(1 for c in mine if c.market_id != market.id and codes.get(c.outcome_id) == outcome.code)
    if taken >= SLOTS[outcome.code]:
        raise CardError("ROW_FULL", f"You already have {SLOTS[outcome.code]} teams on "
                        f"{outcome.code.replace('-', chr(8211))}. Move one to free a slot.")
    call = next((c for c in mine if c.market_id == market.id), None)
    if call is None:
        call = SwissCall(user_id=user_id, market_id=market.id, outcome_id=outcome.id, odds=outcome.odds,
                         odds_version=outcome.odds_version, status="OPEN", reward_rc=0, settled_revision=0)
        session.add(call)
    else:
        call.outcome_id, call.odds, call.odds_version, call.updated_at = (outcome.id, outcome.odds,
                                                                          outcome.odds_version, now)
    session.flush()
    return call


def clear_call(session: Session, season: Season, user_id: uuid.UUID, market_id: uuid.UUID, now: datetime) -> None:
    _open_market(session, season, market_id, now)
    call = session.execute(select(SwissCall).where(SwissCall.user_id == user_id, SwissCall.market_id == market_id)
                           ).scalar_one_or_none()
    if call is not None:
        session.delete(call)
        session.flush()


def settle_calls(session: Session, market: Market, revision: int, winning: list[str], partial: set[str],
                 void: bool, wallets: dict[uuid.UUID, Wallet], now: datetime) -> None:
    """Pay (or correct) every call on a settled record market. `wallets` is keyed by user, already locked."""
    codes = _codes(session, [market.id])
    calls = session.execute(select(SwissCall).where(SwissCall.market_id == market.id)
                            .order_by(SwissCall.id).with_for_update()).scalars()
    for call in calls:
        code = codes[call.outcome_id]
        result = "VOID" if void else "WON" if code in winning else "PARTIAL" if code in partial else "LOST"
        new = reward(call.odds, result)
        wallet = wallets[call.user_id]
        if not (call.settled_revision > 0 and call.status == result):
            if call.settled_revision > 0 and call.reward_rc > 0:
                ledger.reverse(session, wallet, amount_rc=call.reward_rc, key=f"reverse-call:{call.id}:{revision}",
                               ref_type="swiss_call", ref_id=str(call.id), memo="Correction: reversed record call reward")
            if new > 0:
                ledger.credit(session, wallet, kind="REWARD", amount_rc=new, key=f"reward:{call.id}:{revision}",
                              ref_type="swiss_call", ref_id=str(call.id),
                              memo=f"{market.title} call{' (right side)' if result == 'PARTIAL' else ''}")
        call.status, call.reward_rc, call.settled_revision, call.settled_at = result, new, revision, now
        session.add(OutboxEvent(type="selection.settled", entity_id=str(call.id), user_id=call.user_id,
                                payload={"result": result, "revision": revision}))


def moved_to_card(sel: Selection) -> bool:
    """A staked record pick refunded when the card replaced staking. Settlement leaves these alone."""
    return sel.status == "VOID" and sel.settled_revision == 0


def convert_staked(session: Session, season: Season, now: datetime) -> int:
    """Refund open staked record picks and carry each call to the card at the price it was placed at.

    Only while calls are open. Idempotent: refunds are keyed per selection, and a team already on the card keeps its card call.
    Calls beyond a row's limit are refunded without a card call, earliest placement first.
    """
    markets = {m.id: m for m in _markets(session, season)}
    # Once calls lock, a staked pick settles as the bet it was.
    open_ids = [m.id for m in markets.values() if m.state == "OPEN"]
    if not open_ids:
        return 0
    rows = session.execute(
        select(Selection, Ticket.accepted_at).join(Ticket, Ticket.id == Selection.ticket_id)
        .where(Selection.market_id.in_(open_ids), Selection.status == "OPEN")
        .order_by(Ticket.accepted_at, Selection.id).with_for_update(of=Selection)
    ).all()
    if not rows:
        return 0
    codes = _codes(session, list(markets))
    users = {s.user_id for s, _ in rows}
    wallets = {w.user_id: w for w in session.execute(select(Wallet).where(Wallet.season_id == season.id,
                                                                          Wallet.user_id.in_(users))).scalars()}
    locked = ledger.lock_wallets(session, {w.id for w in wallets.values()})
    existing = list(session.execute(select(SwissCall).where(SwissCall.user_id.in_(users))).scalars())
    on_card = {(c.user_id, c.market_id) for c in existing}
    per_row: dict[tuple[uuid.UUID, str], int] = {}
    for c in existing:
        per_row[(c.user_id, codes[c.outcome_id])] = per_row.get((c.user_id, codes[c.outcome_id]), 0) + 1
    moved = 0
    for sel, _ in rows:
        code = codes[sel.outcome_id]
        if (sel.user_id, sel.market_id) not in on_card \
                and per_row.get((sel.user_id, code), 0) < SLOTS[code]:
            session.add(SwissCall(user_id=sel.user_id, market_id=sel.market_id, outcome_id=sel.outcome_id,
                                  odds=sel.odds, odds_version=sel.odds_version, status="OPEN", reward_rc=0,
                                  settled_revision=0))
            on_card.add((sel.user_id, sel.market_id))
            per_row[(sel.user_id, code)] = per_row.get((sel.user_id, code), 0) + 1
        ledger.credit(session, locked[wallets[sel.user_id].id], kind="VOID_REFUND", amount_rc=sel.stake_rc,
                      key=f"card-refund:{sel.id}", ref_type="selection", ref_id=str(sel.id),
                      memo=f"{sel.rules_snapshot.get('title', 'Swiss record')}: moved to the free record card")
        sel.status, sel.return_rc, sel.settled_at = "VOID", sel.stake_rc, now
        moved += 1
        session.add(OutboxEvent(type="selection.settled", entity_id=str(sel.id), user_id=sel.user_id,
                                payload={"result": "VOID", "revision": 0}))
    session.flush()
    return moved

