"""Livestats timeline extraction against a scripted feed that speaks the real payload format (no network)."""

from datetime import UTC, datetime, timedelta

import httpx

from rift import timeline
from rift.adapters.lolesports import parse_detail_frames, parse_frames
from rift.models import Game

T0 = datetime(2026, 10, 23, 17, 10, 1, 627000, tzinfo=UTC)
CHAMPS = ["Jayce", "LeeSin", "Cassiopeia", "Zeri", "Yuumi", "Yorick", "JarvanIV", "Akali", "Ashe", "Seraphine"]
# (game second, side, metric, dragon type)
SCRIPT = [
    (185.25, "blue", "kills", None), (300.0, "red", "kills", None), (330.5, "red", "dragons", "ocean"),
    (610.0, "red", "towers", None), (640.0, "blue", "dragons", "infernal"), (700.25, "blue", "towers", None),
    (960.0, "red", "dragons", "hextech"), (1270.0, "red", "dragons", "hextech"), (1500.0, "blue", "barons", None),
    (1580.75, "red", "dragons", "hextech"), (1700.0, "blue", "inhibitors", None), (1900.0, "red", "barons", None),
    (2100.5, "blue", "dragons", "elder"),
]


def _z(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class ScriptedGame:
    """A game whose counters follow a script; frames every 0.25 s like the dense real feed."""

    def __init__(self, game_id: str, t0: datetime, length_s: float, script=SCRIPT, champs=CHAMPS,
                 blue: str = "e-a", red: str = "e-b"):
        self.game_id, self.t0, self.length, self.script = game_id, t0, length_s, script
        self.champs, self.blue, self.red = champs, blue, red

    @property
    def end(self) -> datetime:
        return self.t0 + timedelta(seconds=self.length)

    def team(self, side: str, s: float) -> dict:
        done = [e for e in self.script if e[0] <= s and e[1] == side]
        count = {m: sum(1 for e in done if e[2] == m) for m in ("kills", "towers", "inhibitors", "barons")}
        base = 0 if side == "blue" else 5
        players = [{"participantId": base + i + 1, "totalGold": 500 + int(s * 2) + base + i, "level": 1 + int(s // 120),
                    "kills": count["kills"] if i == 0 else 0, "deaths": 0, "assists": 0,
                    "creepScore": (base + i + 1) * 10 + int(s // 10)} for i in range(5)]
        return {"totalGold": sum(p["totalGold"] for p in players), "inhibitors": count["inhibitors"],
                "towers": count["towers"], "barons": count["barons"], "totalKills": count["kills"],
                "dragons": [e[3] for e in done if e[2] == "dragons"], "participants": players}

    def window(self, at: datetime | None, now: datetime) -> dict | None:
        if now < self.t0:
            return None  # not loaded yet: still in draft
        last = min(self.end, now)
        start = self.t0 if at is None else max(self.t0, at.replace(microsecond=0) - timedelta(seconds=at.second % 10))
        if start > last:
            start = last - timedelta(seconds=4)  # past the end: the feed returns the final frames
        frames, t = [], max(start, self.t0)
        while t <= last and t < start + timedelta(seconds=10):
            s = (t - self.t0).total_seconds()
            frames.append({"rfc460Timestamp": _z(t), "gameState": "finished" if s >= self.length else "in_game",
                           "blueTeam": self.team("blue", s), "redTeam": self.team("red", s)})
            t += timedelta(seconds=0.25)
        if last == self.end and start + timedelta(seconds=10) > self.end and frames[-1]["gameState"] != "finished":
            s = self.length
            frames.append({"rfc460Timestamp": _z(self.end), "gameState": "finished",
                           "blueTeam": self.team("blue", s), "redTeam": self.team("red", s)})

        def meta(side, team_id):
            base = 0 if side == "blue" else 5
            return {"esportsTeamId": team_id, "participantMetadata": [
                {"participantId": base + i + 1, "esportsPlayerId": f"p{base + i}", "summonerName": f"P{base + i}",
                 "championId": self.champs[base + i], "role": "top"} for i in range(5)]}

        return {"esportsGameId": self.game_id, "gameMetadata": {
            "patchVersion": "16.20.1", "blueTeamMetadata": meta("blue", self.blue),
            "redTeamMetadata": meta("red", self.red)}, "frames": frames}

    def details(self, at: datetime, now: datetime) -> dict | None:
        w = self.window(at, now)
        if w is None:
            return None
        rows = []
        for f in w["frames"]:
            players = f["blueTeam"]["participants"] + f["redTeam"]["participants"]
            rows.append({"rfc460Timestamp": f["rfc460Timestamp"], "participants": [
                {"participantId": p["participantId"], "level": p["level"], "kills": p["kills"], "deaths": 0,
                 "assists": 0, "totalGoldEarned": p["totalGold"], "creepScore": p["creepScore"],
                 "killParticipation": 0.5, "championDamageShare": 0.2} for p in players]})
        return {"frames": rows}


class ScriptedClient:
    """The two livestats calls the timeline uses, answered from scripted games at the current clock."""

    def __init__(self, clock, *games: ScriptedGame):
        self.clock, self.games, self.requests = clock, {g.game_id: g for g in games}, 0

    def frames(self, game_id, starting_time=None):
        self.requests += 1
        game = self.games.get(game_id)
        payload = game.window(starting_time, self.clock()) if game else None
        return parse_frames(payload) if payload else None

    def detail_frames(self, game_id, starting_time):
        self.requests += 1
        game = self.games.get(game_id)
        payload = game.details(starting_time, self.clock()) if game else None
        return parse_detail_frames(payload) if payload else []


def _run_to_completion(game: Game, client: ScriptedClient, now: datetime, cycles: int = 10) -> int:
    n = 0
    while not game.timeline_complete and n < cycles:
        timeline.track(game, client, now)
        n += 1
    return n


def test_post_game_scan_extracts_frame_exact_firsts_dragons_and_lines():
    script = ScriptedGame("g1", T0, 2300)
    now = [T0 + timedelta(minutes=60)]
    client = ScriptedClient(lambda: now[0], script)
    game = Game(provider_id="g1", game_index=1, state="completed", timeline_complete=False)
    timeline.track(game, client, now[0])
    # 1-minute steps bracket most changes; those brackets wait to be bisected down to the frame.
    assert not game.timeline_complete and len(game.timeline["scan"]["refine"]) >= 5
    cycles = 1 + _run_to_completion(game, client, now[0])
    tl = game.timeline
    assert game.timeline_complete and cycles >= 2  # the scan is spread over cycles by its request budget
    assert client.requests < 90
    assert game.started_at == T0 and game.ended_at == script.end
    f = tl["firsts"]
    assert f["blood"] == {"side": "blue", "team_id": None, "at_s": 185}
    assert f["tower"]["side"] == "red" and f["tower"]["at_s"] == 610
    assert f["dragon"] == {"side": "red", "team_id": None, "at_s": 330, "type": "ocean"}
    assert f["baron"]["side"] == "blue" and f["baron"]["at_s"] == 1500
    assert f["inhibitor"]["side"] == "blue" and f["inhibitor"]["at_s"] == 1700
    assert [(d["side"], d["type"], d["at_s"]) for d in tl["dragons"]] == [
        ("red", "ocean", 330), ("blue", "infernal", 640), ("red", "hextech", 960), ("red", "hextech", 1270),
        ("red", "hextech", 1580), ("blue", "elder", 2100)]
    assert (tl["soul"], tl["soul_side"], tl["elder"]) == ("hextech", "red", True)
    assert [(b["side"], b["at_s"]) for b in tl["barons"]] == [("blue", 1500), ("red", 1900)]
    assert tl["at_15"]["at_s"] == 900 and tl["at_15"]["players"]["3"] == {"cs": 120, "gold": 500 + 1800 + 2}
    assert tl["final"]["1"] == {"kills": 1, "deaths": 0, "assists": 0, "cs": 10 + 230, "gold": 500 + 4600,
                                "damage_share": 0.2, "kill_participation": 0.5}
    assert tl["participants"]["7"]["champion"] == "JarvanIV"
    assert "live_state" not in tl and set(tl["scan"]) == {"requests"}
    # Complete timelines are final: no further requests.
    before = client.requests
    assert timeline.track(game, client, now[0]) is False and client.requests == before


def test_live_polling_fills_provisionally_then_completes_after_the_game():
    script = ScriptedGame("g1", T0, 2300)
    now = [T0 - timedelta(minutes=2)]
    client = ScriptedClient(lambda: now[0], script)
    game = Game(provider_id="g1", game_index=1, state="inProgress", timeline_complete=False)
    assert timeline.track(game, client, now[0]) is False and game.started_at is None  # still drafting
    now[0] = T0 + timedelta(seconds=20)
    timeline.track(game, client, now[0])
    assert game.started_at == T0 and game.timeline["live"]["clock_s"] < 20
    # Poll every 15 s for the first 20 minutes: one window per poll, plus one for the 15:00 lines.
    while now[0] < T0 + timedelta(minutes=20):
        now[0] += timedelta(seconds=15)
        timeline.track(game, client, now[0])
    tl = game.timeline
    assert not game.timeline_complete
    assert client.requests < 20 * 4 + 5
    assert tl["firsts"]["blood"]["side"] == "blue" and 185 <= tl["firsts"]["blood"]["at_s"] <= 185 + 16
    assert tl["firsts"]["dragon"]["type"] == "ocean" and "baron" not in tl["firsts"]  # not yet, not "none"
    assert tl["live"]["kills"] == {"blue": 1, "red": 1} and tl["live"]["dragons"] == {
        "blue": ["infernal"], "red": ["ocean", "hextech"]}
    assert tl["at_15"]["at_s"] == 900
    # The game ends; the full scan then replaces the provisional times with frame-exact ones.
    now[0] = script.end + timedelta(minutes=1)
    game.state = "completed"
    _run_to_completion(game, client, now[0])
    assert game.timeline_complete and game.timeline["firsts"]["blood"]["at_s"] == 185
    assert game.ended_at == script.end


def test_short_game_has_no_15_minute_line_and_absent_objectives_are_null():
    script = ScriptedGame("g1", T0, 800, script=[(100.0, "red", "kills", None)])
    client = ScriptedClient(lambda: T0 + timedelta(hours=1), script)
    game = Game(provider_id="g1", game_index=1, state="completed", timeline_complete=False)
    _run_to_completion(game, client, T0 + timedelta(hours=1))
    tl = game.timeline
    assert game.timeline_complete and tl["at_15"] is None
    assert tl["firsts"]["blood"]["side"] == "red"
    assert tl["firsts"]["tower"] is None and tl["firsts"]["baron"] is None and tl["dragons"] == []
    assert (tl["soul"], tl["elder"]) == (None, False)


def test_malformed_frames_are_dropped_not_guessed():
    payload = ScriptedGame("g1", T0, 2300).window(T0 + timedelta(minutes=5), T0 + timedelta(hours=1))
    payload["frames"][0]["blueTeam"]["totalKills"] = None
    payload["frames"][1]["redTeam"]["dragons"] = "ocean"
    del payload["frames"][2]["rfc460Timestamp"]
    w = parse_frames(payload)
    assert len(w.frames) == len(payload["frames"]) - 3
    assert w.participants[1]["champion"] == "Jayce" and w.team_esports_ids == {"blue": "e-a", "red": "e-b"}


def test_fearless_pool_accumulates_earlier_games():
    g1 = Game(game_index=1, state="completed", stats={"players": [{"champion": c} for c in CHAMPS]})
    g2 = Game(game_index=2, state="inProgress", stats=None, timeline={"participants": {
        "1": {"champion": "Rumble"}, "2": {"champion": "Vi"}}})
    pool = timeline.burned_champions([g1, g2], 3)
    assert pool[1] == [] and pool[2] == CHAMPS and pool[3] == CHAMPS + ["Rumble", "Vi"]


class DelayedClient(ScriptedClient):
    """The feed running 75 s behind real time: it answers 400 for anything newer, as it did on 2026-10-23."""

    def frames(self, game_id, starting_time=None):
        if starting_time is not None and starting_time > self.clock() - timedelta(seconds=75):
            self.requests += 1
            request = httpx.Request("GET", f"https://feed/window/{game_id}")
            raise httpx.HTTPStatusError("400", request=request, response=httpx.Response(400, request=request))
        return super().frames(game_id, starting_time)


def test_live_polling_backs_off_when_the_feed_trails_further_behind():
    script = ScriptedGame("g1", T0, 2300)
    now = [T0 + timedelta(seconds=20)]
    client = DelayedClient(lambda: now[0], script)
    game = Game(provider_id="g1", game_index=1, state="inProgress", timeline_complete=False)
    timeline.track(game, client, now[0])  # the first window takes no start time, so it always answers
    for _ in range(40):  # ten minutes of 15-second polls
        now[0] += timedelta(seconds=15)
        timeline.track(game, client, now[0])
    state = game.timeline["live_state"]
    assert 75 <= state["lag_s"] <= 75 + timeline.LAG_STEP_S
    # Live data keeps up to within the feed's own delay instead of freezing at the first failure.
    assert game.timeline["live"]["clock_s"] >= 10 * 60 - 75 - timeline.LAG_STEP_S - 15
