"""Per-game livestats timeline: objective firsts, dragon order, 15-minute and final player lines.

Game time is wall time since the game's first livestats frame. That frame appears when the game loads
(after the draft), and pauses are not subtracted, so a time after a pause reads late by the pause length.
An event's time is that of the first frame showing the new counter. While a game is live that is within
one worker poll; once it ends, one full scan (1-minute steps, then a bisection of each change down to the
frame) rebuilds the timeline and only then marks it complete. Graders that read it HOLD until then.

Fetches are economical: one window per poll while live, a bounded number per cycle for the final scan,
and scan progress is stored on the game so nothing already fetched is fetched again.
"""

import copy
import logging
from datetime import datetime, timedelta

import httpx

from rift.adapters.lolesports import COUNTERS, SIDES, Frame, LolesportsClient, Window, parse_time
from rift.models import Game

log = logging.getLogger(__name__)

LIVE_LAG = timedelta(seconds=30)  # the feed trails real time; asking for "now" returns nothing yet
LAG_STEP_S, LAG_EASE_S, MAX_LIVE_LAG_S = 20, 5, 300  # back off on a 400, ease back on success, never past 5:00
STEP = timedelta(minutes=1)  # post-game scan step; each change found is then bisected down to the frame
EXACT = timedelta(seconds=2)  # frames are many per second, so a bracket this tight is the frame itself
REQUEST_BUDGET = 25  # feed requests per game per worker cycle, so a scan never holds a transaction long
AT_15 = timedelta(minutes=15)
FIRSTS = {"blood": "kills", "tower": "towers", "dragon": "dragons", "baron": "barons", "inhibitor": "inhibitors"}
EVERY = ("dragons", "barons")  # every occurrence is kept; other counters only matter the first time
RACE_KILLS = 5  # kills are kept up to the fifth, for "first to 5 kills"


def _iso(t: datetime) -> str:
    return t.isoformat()


def _zero() -> dict:
    return {side: dict.fromkeys(COUNTERS, 0) for side in SIDES}


def _key(metric: str, side: str, n: int) -> str:
    return f"{metric}:{side}:{n}"


def observe(frames: list[Frame], state: dict, refine: list | None = None) -> None:
    """Fold frames into `state` ({prev, prev_at, events}), recording the first frame of each new count.

    A change seen on the first new frame of a fetch happened somewhere since the previous fetch; when
    `refine` is given that bracket is queued for bisection.
    """
    prev, events = state["prev"], state["events"]
    prev_at = parse_time(state["prev_at"]) if state.get("prev_at") else None
    first = True
    for f in frames:
        if prev_at is not None and f.at <= prev_at:
            continue
        gap = first and prev_at is not None and f.at - prev_at > EXACT
        for side in SIDES:
            team = f.teams[side]
            for metric in COUNTERS:
                value, seen = team.count(metric), prev[side][metric]
                for n in range(seen + 1, value + 1):
                    key = _key(metric, side, n)
                    if (metric in EVERY or n == 1 or (metric == "kills" and n <= RACE_KILLS)) and key not in events:
                        events[key] = {"at": _iso(f.at),
                                       "type": team.dragons[n - 1] if metric == "dragons" else None}
                        if gap and refine is not None:
                            refine.append({"key": key, "lo": _iso(prev_at), "hi": _iso(f.at)})
                prev[side][metric] = max(seen, value)
        prev_at, first = f.at, False
    if prev_at is not None:
        state["prev_at"] = _iso(prev_at)


def summarise(events: dict, team_ids: dict, t0: datetime, complete: bool) -> dict:
    """Firsts, ordered dragons (with soul and elder) and barons from recorded events.

    A first that has not happened yet is absent while the game runs and null once it is complete.
    Two sides showing the same first in the same frame cannot be ordered: the side is left null.
    """
    def at_s(ev: dict) -> int:
        return int((parse_time(ev["at"]) - t0).total_seconds())

    def entry(side: str | None, ev: dict) -> dict:
        return {"side": side, "team_id": team_ids.get(side) if side else None, "at_s": at_s(ev)}

    firsts: dict = {}
    for name, metric in FIRSTS.items():
        seen = sorted(((parse_time(ev["at"]), side, ev) for side in SIDES
                       if (ev := events.get(_key(metric, side, 1)))), key=lambda row: row[:2])
        if not seen:
            if complete:
                firsts[name] = None
            continue
        at, side, ev = seen[0]
        tied = len(seen) > 1 and seen[1][0] == at
        firsts[name] = entry(None if tied else side, ev)
        if metric == "dragons":
            firsts[name]["type"] = None if tied else ev["type"]
    # First to five kills: the side whose fifth kill shows first (null if both in the same frame, or nobody).
    race = sorted(((parse_time(ev["at"]), side, ev) for side in SIDES
                   if (ev := events.get(_key("kills", side, RACE_KILLS)))), key=lambda row: row[:2])
    if race:
        tied = len(race) > 1 and race[1][0] == race[0][0]
        firsts["five_kills"] = entry(None if tied else race[0][1], race[0][2])
    elif complete:
        firsts["five_kills"] = None
    dragons, barons = [], []
    for key, ev in events.items():
        metric, side, _n = key.split(":")
        if metric == "dragons":
            dragons.append({**entry(side, ev), "type": ev["type"]})
        elif metric == "barons":
            barons.append(entry(side, ev))
    dragons.sort(key=lambda d: d["at_s"])
    barons.sort(key=lambda b: b["at_s"])
    soul = soul_side = None
    for side in SIDES:
        elemental = [d["type"] for d in dragons if d["side"] == side and d["type"] != "elder"]
        if len(elemental) >= 4:
            soul, soul_side = elemental[3], side
    # When each recorded kill happened (the first five per side): live prices that hadn't seen a kill yet
    # void the picks accepted after it (rift.props.priced_before_a_kill).
    kills_at = sorted(({"side": key.split(":")[1], "at": ev["at"]} for key, ev in events.items()
                       if key.startswith("kills:")), key=lambda k: k["at"])
    return {"firsts": firsts, "dragons": dragons, "barons": barons, "soul": soul, "soul_side": soul_side,
            "elder": any(d["type"] == "elder" for d in dragons), "kills_at": kills_at}


def live_summary(frame: Frame, t0: datetime) -> dict:
    return {"at": _iso(frame.at), "state": frame.state, "clock_s": int((frame.at - t0).total_seconds()),
            **{metric: {side: frame.teams[side].count(metric) for side in SIDES}
               for metric in ("kills", "towers", "inhibitors", "barons")},
            "gold": {side: frame.teams[side].gold for side in SIDES},
            "players": {str(pid): p["gold"] for pid, p in sorted(frame.players.items())},
            "dragons": {side: list(frame.teams[side].dragons) for side in SIDES}}


def nearest(frames: list[Frame], target: datetime) -> Frame | None:
    return min(frames, key=lambda f: abs((f.at - target).total_seconds()), default=None)


def at_15(window: Window | None, t0: datetime) -> dict | None:
    frame = nearest(window.frames if window else [], t0 + AT_15)
    if frame is None or abs(frame.at - (t0 + AT_15)) > timedelta(seconds=30) or len(frame.players) != 10:
        return None
    return {"at_s": int((frame.at - t0).total_seconds()),
            "players": {str(pid): {"cs": p["cs"], "gold": p["gold"]} for pid, p in sorted(frame.players.items())}}


class _Budget:
    def __init__(self, client: LolesportsClient, game_id: str, limit: int):
        self.client, self.game_id, self.left = client, game_id, limit

    def frames(self, at: datetime | None) -> Window | None:
        self.left -= 1
        return self.client.frames(self.game_id, at)


def track(game: Game, client: LolesportsClient, now: datetime, budget: int = REQUEST_BUDGET) -> bool:
    """Advance one game's timeline by at most `budget` feed requests. Returns True if anything changed.

    Progress is written back even when the feed fails part-way, so the next cycle resumes from it.
    """
    if game.timeline_complete or game.state == "unneeded":
        return False
    before = (game.timeline, game.started_at, game.ended_at)
    tl = copy.deepcopy(game.timeline) if game.timeline else {}
    feed = _Budget(client, game.provider_id, budget)
    try:
        _advance(game, tl, feed, now)
    except httpx.HTTPError as exc:
        log.warning("game %s: livestats fetch failed (%s)", game.provider_id, type(exc).__name__)
    finally:
        if tl:
            game.timeline = tl
    return (game.timeline, game.started_at, game.ended_at) != before


def _team_ids(game: Game) -> dict:
    return {"blue": str(game.blue_team_id) if game.blue_team_id else None,
            "red": str(game.red_team_id) if game.red_team_id else None}


def _advance(game: Game, tl: dict, feed: _Budget, now: datetime) -> None:
    if "t0" not in tl:
        w = feed.frames(None)
        if w is None or not w.frames:
            return  # not loaded yet (the draft is still running, or the game never starts)
        if len(w.participants) != 10:
            return
        game.started_at = w.frames[0].at
        tl.update({"version": 1, "t0": _iso(w.frames[0].at),
                   "participants": {str(pid): p for pid, p in sorted(w.participants.items())},
                   "live_state": {"prev": _zero(), "events": {}}})
        observe(w.frames, tl["live_state"])
        tl["live"] = live_summary(w.frames[-1], w.frames[0].at)
        if w.frames[-1].state == "finished":
            game.ended_at = w.frames[-1].at
    t0 = parse_time(tl["t0"])
    if game.ended_at is None and game.state != "completed":
        _live(game, tl, feed, now, t0)
    else:
        _final(game, tl, feed, now, t0)


def _live(game: Game, tl: dict, feed: _Budget, now: datetime, t0: datetime) -> None:
    state = tl["live_state"]
    lag = state.get("lag_s", LIVE_LAG.total_seconds())
    probe = now - timedelta(seconds=lag)
    if state.get("prev_at") and probe <= parse_time(state["prev_at"]):
        return
    try:
        w = feed.frames(probe)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 400:
            raise
        # Broadcast delay varies, and the feed answers 400 for a time it hasn't reached yet. Ask further back
        # next poll instead of repeating a request that keeps failing.
        state["lag_s"] = min(lag + LAG_STEP_S, MAX_LIVE_LAG_S)
        return
    if lag > LIVE_LAG.total_seconds():  # creep back toward real time while it keeps answering
        state["lag_s"] = max(lag - LAG_EASE_S, LIVE_LAG.total_seconds())
    frames = w.frames if w else []
    if frames:
        observe(frames, state)
        tl["live"] = live_summary(frames[-1], t0)
        tl.update(summarise(state["events"], _team_ids(game), t0, complete=False))
        if frames[-1].state == "finished":
            game.ended_at = frames[-1].at
    clock = parse_time(state["prev_at"]) - t0 if state.get("prev_at") else timedelta(0)
    if "at_15" not in tl and clock >= AT_15 + timedelta(seconds=30) and feed.left > 0:
        line = at_15(feed.frames(t0 + AT_15), t0)
        if line is not None:
            tl["at_15"] = line


def _final(game: Game, tl: dict, feed: _Budget, now: datetime, t0: datetime) -> None:
    if game.ended_at is None:
        # The series says the game is over; its last frames say when.
        w = feed.frames(min(now - LIVE_LAG, t0 + timedelta(hours=3)))
        if w is None or not w.frames or w.frames[-1].state != "finished":
            return
        game.ended_at = w.frames[-1].at
        tl["live"] = live_summary(w.frames[-1], t0)
    end = game.ended_at
    scan = tl.setdefault("scan", {"cursor": _iso(t0), "prev_at": _iso(t0), "prev": _zero(), "events": {},
                                  "refine": [], "requests": 0})
    start_left = feed.left
    try:
        _step(scan, feed, t0, end)
        _refine(scan, feed)
    finally:
        scan["requests"] += start_left - feed.left
    if parse_time(scan["cursor"]) < end or scan["refine"]:
        return
    if "at_15" not in tl or tl["at_15"] is None:
        if end - t0 < AT_15:
            tl["at_15"] = None
        elif feed.left > 0:
            line = at_15(feed.frames(t0 + AT_15), t0)
            if line is None:
                return  # a hole at 15:00; HOLD rather than use a distant frame
            tl["at_15"] = line
        else:
            return
    if tl.get("final") is None:
        if feed.left <= 0:
            return
        feed.left -= 1
        rows = feed.client.detail_frames(game.provider_id, end)
        last = rows[-1][1] if rows and rows[-1][0] >= end - EXACT else {}  # the end itself, or HOLD
        if len(last) != 10 or any(v["damage_share"] is None or v["kill_participation"] is None
                                  for v in last.values()):
            return
        tl["final"] = {str(pid): last[pid] for pid in sorted(last)}
    tl.update(summarise(scan["events"], _team_ids(game), t0, complete=True))
    tl["scan"] = {"requests": scan["requests"]}
    tl.pop("live_state", None)
    game.timeline_complete = True
    game.data_changed_at = now


def _step(scan: dict, feed: _Budget, t0: datetime, end: datetime) -> None:
    while feed.left > 0 and parse_time(scan["cursor"]) < end:
        cursor = parse_time(scan["cursor"])
        probe = min(cursor + STEP, end)
        w = feed.frames(probe)
        frames = [f for f in (w.frames if w else []) if f.at > cursor]
        if frames:
            observe(frames, scan, scan["refine"])
        done = (frames and frames[-1].state == "finished") or probe >= end
        scan["cursor"] = _iso(end if done else max(probe, frames[-1].at) if frames else probe)


def _refine(scan: dict, feed: _Budget) -> None:
    """Bisect each bracketed change down to the first frame that shows it."""
    while scan["refine"] and feed.left > 0:
        task = scan["refine"][0]
        metric, side, n = task["key"].split(":")
        lo, hi = parse_time(task["lo"]), parse_time(task["hi"])
        settled = False
        while hi - lo > EXACT:
            if feed.left <= 0:
                break
            w = feed.frames(lo + (hi - lo) / 2)
            inside = [f for f in (w.frames if w else []) if lo < f.at < hi]
            if not inside:
                settled = True  # the feed has a hole here; the bracket's upper end is the best we know
                break
            hit = next((f for f in inside if f.teams[side].count(metric) >= int(n)), None)
            if hit is None:
                lo = inside[-1].at
            else:
                earlier = [f for f in inside if f.at < hit.at]
                hi, lo = hit.at, earlier[-1].at if earlier else lo
        else:
            settled = True
        task["lo"], task["hi"] = _iso(lo), _iso(hi)
        if not settled:
            return
        scan["events"][task["key"]]["at"] = task["hi"]
        scan["refine"].pop(0)


def champions(game: Game) -> list[str]:
    """Champions played in a game, from verified stats or else from its first livestats frame."""
    if game.stats and game.stats.get("players"):
        return [p["champion"] for p in game.stats["players"] if p.get("champion")]
    participants = (game.timeline or {}).get("participants") or {}
    return [p["champion"] for _pid, p in sorted(participants.items(), key=lambda kv: int(kv[0]))
            if p.get("champion")]


def burned_champions(games: list[Game], best_of: int) -> dict[int, list[str]]:
    """Fearless Draft pool: for each game index, the champions already played earlier in the series."""
    played = {g.game_index: champions(g) for g in games if g.state != "unneeded"}
    out: dict[int, list[str]] = {}
    for idx in range(1, best_of + 1):
        seen: list[str] = []
        for earlier in range(1, idx):
            seen.extend(c for c in played.get(earlier, []) if c not in seen)
        out[idx] = seen
    return out
