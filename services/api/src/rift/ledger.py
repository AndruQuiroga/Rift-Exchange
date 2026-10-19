"""Wallet journal. Every balance change goes through post(); callers hold the wallet row lock."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rift.models import LedgerEntry, OutboxEvent, Wallet


class InsufficientCredits(Exception):
    def __init__(self, available_rc: int, required_rc: int):
        super().__init__(f"available {available_rc} < required {required_rc}")
        self.available_rc = available_rc
        self.required_rc = required_rc


def lock_wallet(session: Session, wallet_id: uuid.UUID) -> Wallet:
    return session.execute(select(Wallet).where(Wallet.id == wallet_id).with_for_update()).scalar_one()


def lock_wallets(session: Session, wallet_ids: set[uuid.UUID]) -> dict[uuid.UUID, Wallet]:
    """Lock in a deterministic order (by id) to avoid deadlocks between concurrent settlements."""
    rows = session.execute(
        select(Wallet).where(Wallet.id.in_(wallet_ids)).order_by(Wallet.id).with_for_update()
    ).scalars()
    return {w.id: w for w in rows}


def entry_exists(session: Session, idempotency_key: str) -> bool:
    return (
        session.execute(select(LedgerEntry.id).where(LedgerEntry.idempotency_key == idempotency_key)).first()
        is not None
    )


def credit(session: Session, wallet: Wallet, *, kind: str, amount_rc: int, key: str, ref_type: str,
           ref_id: str, memo: str = "") -> LedgerEntry:
    """Add credits. Outstanding correction recovery is repaid first."""
    if amount_rc <= 0:
        raise ValueError("credit amount must be positive")
    recovered = min(amount_rc, wallet.recovery_due_rc)
    wallet.recovery_due_rc -= recovered
    wallet.available_rc += amount_rc - recovered
    return _append(session, wallet, kind, amount_rc, amount_rc - recovered, -recovered, key, ref_type, ref_id,
                   memo)


def debit_stake(session: Session, wallet: Wallet, *, amount_rc: int, key: str, ref_id: str,
                memo: str = "") -> LedgerEntry:
    if amount_rc <= 0:
        raise ValueError("stake must be positive")
    if amount_rc > wallet.available_rc:
        raise InsufficientCredits(wallet.available_rc, amount_rc)
    wallet.available_rc -= amount_rc
    return _append(session, wallet, "STAKE", -amount_rc, -amount_rc, 0, key, "ticket", ref_id, memo)


def reverse(session: Session, wallet: Wallet, *, amount_rc: int, key: str, ref_type: str, ref_id: str,
            memo: str) -> LedgerEntry:
    """Claw back a previously credited amount. Never drives available below zero (spec 08 §Corrections)."""
    if amount_rc <= 0:
        raise ValueError("reversal amount must be positive")
    from_available = min(amount_rc, wallet.available_rc)
    wallet.available_rc -= from_available
    wallet.recovery_due_rc += amount_rc - from_available
    return _append(session, wallet, "REVERSAL", -amount_rc, -from_available, amount_rc - from_available, key,
                   ref_type, ref_id, memo)


def _append(session: Session, wallet: Wallet, kind: str, gross: int, available_delta: int, recovery_delta: int,
            key: str, ref_type: str, ref_id: str, memo: str) -> LedgerEntry:
    entry = LedgerEntry(wallet_id=wallet.id, kind=kind, gross_rc=gross, available_delta=available_delta,
                        recovery_delta=recovery_delta, idempotency_key=key, ref_type=ref_type, ref_id=ref_id,
                        memo=memo)
    session.add(entry)
    session.add(OutboxEvent(type="wallet.changed", entity_id=str(wallet.id), user_id=wallet.user_id,
                            payload={"kind": kind}))
    session.flush()
    return entry


def reconcile(session: Session) -> list[dict]:
    """Return wallets whose cached balance disagrees with the journal (should always be empty)."""
    rows = session.execute(
        select(Wallet.id, Wallet.available_rc, Wallet.recovery_due_rc,
               func.coalesce(func.sum(LedgerEntry.available_delta), 0),
               func.coalesce(func.sum(LedgerEntry.recovery_delta), 0))
        .outerjoin(LedgerEntry, LedgerEntry.wallet_id == Wallet.id)
        .group_by(Wallet.id)
    ).all()
    return [
        {"wallet_id": str(r[0]), "cached": (r[1], r[2]), "journal": (int(r[3]), int(r[4]))}
        for r in rows if (r[1], r[2]) != (int(r[3]), int(r[4]))
    ]
