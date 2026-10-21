"""How teams and players are named on every screen. Provider names are inconsistent ("BILIBILI GAMING",
"Hanwha Life Esports", "Gen.G Esports") and livestats prefixes players with their team ("GEN Kiin", "IGTheShy");
this is the one place that turns them into display names."""

import re

TEAM_NAMES: dict[str, str] = {
    "GEN": "Gen.G",
    "HLE": "Hanwha Life",
    "BLG": "Bilibili Gaming",
    "TES": "Top Esports",
    "AL": "Anyone's Legend",
    "IG": "Invictus Gaming",
    "DK": "Dplus KIA",
    "KC": "Karmine Corp",
    "MVK": "MVK Esports",
    "C9": "Cloud9",
    "G2": "G2 Esports",
    "FLY": "FlyQuest",
    "FUR": "FURIA",
    "CFO": "CTBC Flying Oyster",
    "T1": "T1",
}


def _tidy(name: str) -> str:
    if name != name.upper() or len(name) <= 4:
        return name
    return re.sub(r"\b(\w)(\w*)", lambda m: m.group(1).upper() + m.group(2).lower(), name)


def team_name(code: str | None, name: str) -> str:
    return TEAM_NAMES.get(code or "") or _tidy(name)


def relabel(text: str | None, teams) -> str | None:
    """Swap provider team names in text stored before display names existed (pick snapshots)."""
    if not text:
        return text
    for t in sorted(teams, key=lambda t: -len(t.name)):
        shown = team_name(t.code, t.name)
        if t.name != shown and t.name in text:
            text = text.replace(t.name, shown)
    return text


def player_name(name: str | None, codes) -> str | None:
    """'GEN Kiin' -> 'Kiin', 'IGTheShy' -> 'TheShy' when the prefix is one of the given team codes."""
    if not name:
        return name
    for code in sorted((c for c in codes if c), key=len, reverse=True):
        if name.startswith(code + " "):
            return name[len(code) + 1:].strip() or name
        rest = name[len(code):]
        if name.startswith(code) and len(rest) > 1 and rest[0].isupper() and not rest[1].isupper():
            return rest
    return name
