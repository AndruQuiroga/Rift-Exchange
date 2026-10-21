"""Invite-only accounts with opaque session cookies (docs/spec/05 Flow A)."""

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from rift import grants
from rift.models import AuditEvent, Invite, Season, Session, User


class AuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_invite(db: DbSession, role: str = "PLAYER") -> str:
    code = secrets.token_urlsafe(9)
    db.add(Invite(code_hash=digest(code), role=role))
    db.add(AuditEvent(actor="cli", action="invite.created", entity_type="invite", entity_id=digest(code)[:12],
                      data={"role": role}))
    return code


def _free_handle(db: DbSession, name: str) -> str:
    """An internal, unique handle made from the chosen name ("Andru Q" -> "andru_q", then "andru_q2", ...)."""
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:18] or "player"
    base = base if len(base) >= 2 else f"{base}_p"
    taken = set(db.execute(select(User.handle).where(User.handle.like(f"{base}%"))).scalars())
    handle, n = base, 2
    while handle in taken:
        handle, n = f"{base}{n}", n + 1
    return handle


def redeem_invite(db: DbSession, season: Season, code: str, name: str, now: datetime,
                  session_days: int) -> tuple[User, str]:
    invite = db.execute(select(Invite).where(Invite.code_hash == digest(code.strip())).with_for_update()
                        ).scalar_one_or_none()
    if invite is None or invite.used_by is not None:
        raise AuthError("INVITE_INVALID", "That invite link is invalid or has already been used.")
    name = " ".join(name.split())
    if not 2 <= len(name) <= 32:
        raise AuthError("NAME_INVALID", "Names are 2–32 characters.")
    if db.execute(select(User).where(User.display_name.ilike(name))).scalar_one_or_none():
        raise AuthError("NAME_TAKEN", "Someone in the league already uses that name.")
    handle = _free_handle(db, name)
    user = User(handle=handle, display_name=name, role=invite.role)
    db.add(user)
    db.flush()
    invite.used_by, invite.used_at = user.id, now
    grants.join_season(db, season, user.id, now)
    db.add(AuditEvent(actor=handle, action="invite.redeemed", entity_type="user", entity_id=str(user.id)))
    return user, start_session(db, user.id, now, session_days)


def start_session(db: DbSession, user_id: uuid.UUID, now: datetime, session_days: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(Session(token_hash=digest(token), user_id=user_id, expires_at=now + timedelta(days=session_days)))
    return token


def user_for_token(db: DbSession, token: str | None, now: datetime) -> User | None:
    if not token:
        return None
    row = db.get(Session, digest(token))
    if row is None or row.expires_at <= now:
        return None
    return db.get(User, row.user_id)
