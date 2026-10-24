"""Invite-only accounts with opaque session cookies (docs/spec/05 Flow A)."""

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from rift import grants
from rift.models import AuditEvent, Invite, Season, Session, SignInCode, SignInLink, User

# No 0/O or 1/I/L: codes are read off one screen and typed into another.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
DEVICE_CODE_TTL = timedelta(minutes=10)
ADMIN_CODE_TTL = timedelta(hours=24)


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


def create_sign_in_code(db: DbSession, user: User, now: datetime, ttl: timedelta = DEVICE_CODE_TTL,
                        actor: str | None = None) -> tuple[str, datetime]:
    """A one-time code ("K7MQ-2PXR") that signs another device into `user`. Replaces their unused codes."""
    db.execute(update(SignInCode).where(SignInCode.user_id == user.id, SignInCode.used_at.is_(None),
                                        SignInCode.expires_at > now).values(expires_at=now))
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    expires_at = now + ttl
    db.add(SignInCode(code_hash=digest(code), user_id=user.id, expires_at=expires_at))
    db.add(AuditEvent(actor=actor or user.handle, action="sign_in_code.created", entity_type="user",
                      entity_id=str(user.id), data={"minutes": int(ttl.total_seconds() // 60)}))
    return f"{code[:4]}-{code[4:]}", expires_at


def redeem_sign_in_code(db: DbSession, code: str, now: datetime, session_days: int) -> tuple[User, str]:
    normalized = re.sub(r"[^A-Z0-9]", "", code.upper())
    row = db.execute(select(SignInCode).where(SignInCode.code_hash == digest(normalized)).with_for_update()
                     ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise AuthError("CODE_INVALID",
                        "That code is wrong, used or expired. Make a new one on a signed-in device.")
    row.used_at = now
    user = db.get(User, row.user_id)
    db.add(AuditEvent(actor=user.handle, action="sign_in_code.redeemed", entity_type="user",
                      entity_id=str(user.id)))
    return user, start_session(db, user.id, now, session_days)


def revoke_sign_in_link(db: DbSession, user: User) -> None:
    # Serialize issuance/revocation for a member, including their first link.
    db.execute(select(User).where(User.id == user.id).with_for_update()).scalar_one()
    row = db.get(SignInLink, user.id)
    if row is not None:
        db.delete(row)
        db.flush()
    db.add(AuditEvent(actor="cli", action="sign_in_link.revoked", entity_type="user",
                      entity_id=str(user.id)))


def create_sign_in_link(db: DbSession, user: User) -> str:
    """Replace the member's permanent credential. Only its hash is stored."""
    revoke_sign_in_link(db, user)
    token = secrets.token_urlsafe(32)
    db.add(SignInLink(user_id=user.id, token_hash=digest(token)))
    db.add(AuditEvent(actor="cli", action="sign_in_link.created", entity_type="user",
                      entity_id=str(user.id)))
    return token


def redeem_sign_in_link(db: DbSession, token: str, now: datetime, session_days: int) -> tuple[User, str]:
    row = db.execute(select(SignInLink).where(SignInLink.token_hash == digest(token)).with_for_update()
                     ).scalar_one_or_none()
    if row is None:
        raise AuthError("LINK_INVALID", "That sign-in link is invalid or has been revoked. Ask the admin for a new one.")
    user = db.get(User, row.user_id)
    db.add(AuditEvent(actor=user.handle, action="sign_in_link.redeemed", entity_type="user",
                      entity_id=str(user.id)))
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
