"""Results before payout (D-032): what the stored data already says about a market that has locked.

The page should show a result the moment it is known, while credits only move once the data has held steady
for the settle delay (D-014/D-030). Two kinds of call, neither of which writes anything:

- final: the settlement grader already returns a result; it pays once nothing has changed for the settle delay
  (`pays_at`). A correction before then moves it, exactly as settlement would.
- live: the game is still going but its live data has decided the market (first blood happened, the draft is
  known from the first frame, the kills passed the line). It confirms from the verified data after the game.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rift.champions import champion_key
from rift.models import Fixture, Game, Market

CALLABLE_STATES = ("LOCKED", "HOLD")


@dataclass
class Call:
    codes: list[str]
    void: bool
    reason: str
    final: bool
    pays_at: datetime | None = None
    partial: list[str] = field(default_factory=list)  # codes paid in part (a banned champion call: half back)
    pending_refund: bool = False  # not picked, and bans aren't known yet: it may still be half back

    def view(self) -> dict:
        return {"winning_codes": self.codes, "void": self.void, "reason": self.reason, "final": self.final,
                "pays_at": self.pays_at.isoformat() if self.pays_at else None, "partial_codes": self.partial,
                "pending_refund": self.pending_refund}


def calls(session: Session, markets: list[Market], settle_delay_s: int) -> dict[uuid.UUID, Call]:
    from rift.settlement import grade_market

    fixtures: dict[uuid.UUID, Fixture] = {}
    games: dict[uuid.UUID, dict[int, Game]] = {}
    stamps: dict[uuid.UUID, datetime | None] = {}
    out = {}
    for m in markets:
        if m.state not in CALLABLE_STATES or m.fixture_id is None:
            continue
        if m.fixture_id not in fixtures:
            fixtures[m.fixture_id] = session.get(Fixture, m.fixture_id)
            games[m.fixture_id] = {g.game_index: g for g in session.execute(
                select(Game).where(Game.fixture_id == m.fixture_id)).scalars()}
            last_game = session.execute(select(func.max(Game.data_changed_at)).where(
                Game.fixture_id == m.fixture_id)).scalar()
            moved = [t for t in (fixtures[m.fixture_id].data_changed_at, last_game) if t]
            stamps[m.fixture_id] = max(moved) if moved else None
        grade = grade_market(session, m)
        if grade.status in ("RESULT", "VOID"):
            stamp = stamps[m.fixture_id]
            out[m.id] = Call(sorted(grade.winning_codes), grade.status == "VOID", grade.reason, True,
                             stamp + timedelta(seconds=settle_delay_s) if stamp else None,
                             partial=sorted(grade.partial_codes))
            continue
        game = games[m.fixture_id].get(m.params.get("game_index", 1))
        call = live_call(m, fixtures[m.fixture_id], game) if game is not None else None
        if call is not None:
            out[m.id] = call
    return out


def live_call(market: Market, fixture: Fixture, game: Game) -> Call | None:
    """A provisional result from the game's live timeline, or None while it is still open."""
    from rift.props import EARLY_BARON_S, TEAM_GOLD_TIE, TIE_MARGIN, gold15_lead, player_lines

    tl = game.timeline or {}
    participants = tl.get("participants") or {}
    if not participants:
        return None
    side_code = {str(fixture.team_a_id): "A", str(fixture.team_b_id): "B"}
    team_of = {"blue": str(game.blue_team_id), "red": str(game.red_team_id)}
    firsts = tl.get("firsts") or {}
    kind, p = market.kind, market.params

    def called(codes: list[str], reason: str) -> Call:
        return Call(codes, False, reason, False)

    if kind == "champion_picked" and market.scope == "GAME":
        side, role = p.get("side"), p.get("role")
        team_id = str(fixture.team_a_id if side == "A" else fixture.team_b_id) if side else None
        if team_id is not None and team_id not in team_of.values():
            return None  # sides not known yet
        picked = {champion_key(x["champion"]) for x in participants.values() if x.get("champion")
                  and (team_id is None or team_of.get(x.get("side")) == team_id)
                  and (role is None or x.get("role") == role)}
        if champion_key(p["champion"]) in picked:
            return called(["YES"], "Draft seen when the game loaded")
        if p.get("ban_refund"):
            return Call(["NO"], False, "Not picked; half back if it was banned (bans confirm after the game)", False,
                        pending_refund=True)
        return called(["NO"], "Draft seen when the game loaded")
    if kind in ("first_blood", "first_tower", "first_dragon", "five_kills"):
        first = firsts.get({"first_blood": "blood", "first_tower": "tower", "first_dragon": "dragon",
                            "five_kills": "five_kills"}[kind])
        code = side_code.get((first or {}).get("team_id") or "")
        return called([code], f"{kind.replace('_', ' ').capitalize()} seen live") if code else None
    if kind == "first_dragon_type":
        dragon = firsts.get("dragon")
        return called([dragon["type"]], "First dragon seen live") if dragon and dragon.get("type") else None
    if kind == "baron_before":
        baron, clock = firsts.get("baron"), (tl.get("live") or {}).get("clock_s") or 0
        if baron:
            return called(["YES" if baron["at_s"] < EARLY_BARON_S else "NO"], "Baron seen live")
        return called(["NO"], "No baron by 25:00") if clock >= EARLY_BARON_S else None
    if kind == "gold_lead_15":
        lead = gold15_lead(game) if tl.get("at_15") else None
        if lead is None:
            return None
        code = side_code.get(lead[0] or "")
        if code is None or lead[1] < TEAM_GOLD_TIE:
            return Call([], True, f"Within {TEAM_GOLD_TIE:,} gold at 15:00 (void rule)", False)
        return called([code], "Gold at 15:00 seen live")
    if kind == "lane_duel" and p.get("stat") == "gold15" and tl.get("at_15"):
        lines = player_lines(game)
        a, b = lines.get(p["a_player"]), lines.get(p["b_player"])

        def no_result(reason: str) -> Call:
            if p.get("void_refund"):  # D-036: half back for both sides
                return Call([], False, f"{reason}: half back", False, partial=["A", "B"])
            return Call([], True, reason, False)

        if a is None or b is None:
            return no_result("A dueling player did not play this game")
        if a["gold15"] is None or b["gold15"] is None:
            return None
        if abs(a["gold15"] - b["gold15"]) < TIE_MARGIN["gold15"]:
            return no_result(f"Within {TIE_MARGIN['gold15']:,} gold")
        return called(["A" if a["gold15"] > b["gold15"] else "B"], "Gold at 15:00 seen live")
    if kind == "total_kills_game":
        kills = sum(((tl.get("live") or {}).get("kills") or {}).values())
        return called(["OVER"], f"{kills} kills already") if kills > float(p["line"]) else None
    return None
