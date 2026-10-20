"""Champion identity across sources: Leaguepedia display names vs livestats `championId`.

Leaguepedia writes "Lee Sin", "Wukong", "K'Sante"; livestats writes "LeeSin", "MonkeyKing", "KSante". Most
ids are the display name without spaces and punctuation; the exceptions below are Riot's legacy ids.
Comparisons go through `champion_key`, so a source spelling "KaiSa" and another "Kaisa" still agree.
"""

import re

# Display name -> livestats id where stripping punctuation is not enough (Riot data-dragon ids).
DISPLAY_TO_ID = {
    "Wukong": "MonkeyKing", "Nunu & Willump": "Nunu", "Renata Glasc": "Renata", "Kai'Sa": "Kaisa",
    "Cho'Gath": "Chogath", "Kha'Zix": "Khazix", "Vel'Koz": "Velkoz", "Bel'Veth": "Belveth", "LeBlanc": "Leblanc",
}
# Lower-case alphanumeric spellings that name the same champion.
KEY_ALIASES = {"wukong": "monkeyking", "nunuwillump": "nunu", "renataglasc": "renata"}
# Leaguepedia placeholders for an unused ban slot.
NO_CHAMPION = {"", "none", "lossofban", "nopick", "noban"}


def champion_key(name: str) -> str:
    """Source-independent comparison key for a champion name or id."""
    flat = re.sub(r"[^0-9a-z]", "", name.casefold())
    return KEY_ALIASES.get(flat, flat)


def champion_id(display: str) -> str | None:
    """Livestats-style id for a Leaguepedia display name; None for an empty slot or unreadable value."""
    name = display.strip()
    if champion_key(name) in NO_CHAMPION:
        return None
    if name in DISPLAY_TO_ID:
        return DISPLAY_TO_ID[name]
    ident = re.sub(r"[^0-9A-Za-z]", "", name)
    if not ident or not ident[0].isalpha():
        raise ValueError("unrecognised champion name")
    return ident[0].upper() + ident[1:]
