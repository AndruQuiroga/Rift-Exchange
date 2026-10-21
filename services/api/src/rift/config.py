from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RIFT_", env_file=".env", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls, settings_cls: type[BaseSettings], init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource, dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple:
        # Explicit *_FILE configuration takes precedence over development defaults.
        # Use the same source for CLI, Alembic, API and worker.
        def mounted_secrets() -> dict:
            import os

            values = {}
            for field in ("database_url", "leaguepedia_bot_user", "leaguepedia_bot_password"):
                path = os.environ.get(f"RIFT_{field.upper()}_FILE")
                if path:
                    try:
                        value = Path(path).read_text(encoding="utf-8").strip()
                    except OSError:
                        raise ValueError(f"Cannot read configured secret file for {field}") from None
                    if not value:
                        raise ValueError(f"Empty configured secret file for {field}")
                    values[field] = value
            return values

        return init_settings, mounted_secrets, env_settings, dotenv_settings, file_secret_settings

    database_url: str = "postgresql+psycopg://rift:rift@localhost:5432/rift"

    # Season defaults (D-010). Match days use the venue-local calendar date.
    season_code: str = "worlds-2026"
    season_name: str = "Worlds 2026"
    season_timezone: str = "America/Chicago"
    season_first_match_day: str = "2026-10-23"
    opening_grant_rc: int = 5000
    match_day_grant_rc: int = 1000

    # Provider settings (D-009)
    lolesports_api: str = "https://esports-api.lolesports.com/persisted/gw"
    lolesports_feed: str = "https://feed.lolesports.com/livestats/v1"
    # Public key embedded in the lolesports website; not a secret.
    lolesports_api_key: str = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
    lolesports_worlds_league_id: str = "98767975604431411"
    leaguepedia_mode: Literal["mock", "live"] = "mock"
    leaguepedia_bot_user: str = Field(default="", repr=False)
    leaguepedia_bot_password: str = Field(default="", repr=False)

    # Worker cadence: fast while a series is live or within 30 minutes of one
    live_poll_seconds: int = 15
    early_poll_seconds: int = 5  # while an early-game window (game start to 3:00) may be open
    idle_poll_seconds: int = 60

    # Market behaviour
    quote_ttl_seconds: int = 20
    settle_delay_seconds: int = 600  # data must be unchanged this long before grading
    hold_void_after_hours: int = 48  # unresolved markets void after this
    max_decimal_odds: str = "100.00"
    min_probability: str = "0.01"
    # Most one player can stake on one prediction (all their picks on it together). Every market is capped
    # in the Swiss stage; from the quarterfinals only predictions open after the draft is seen stay capped.
    stake_cap_rc: int = 1000
    # The Worlds champion future is paused until the Swiss stage is over (owner decision 2026-10-21).
    offer_tournament_winner: bool = False

    session_days: int = 60
    cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
