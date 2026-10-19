from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RIFT_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://rift:rift@localhost:5432/rift"

    # Season defaults (D-010). Match days use the venue-local calendar date.
    season_code: str = "worlds-2026"
    season_name: str = "Worlds 2026"
    season_timezone: str = "America/Chicago"
    season_first_match_day: str = "2026-10-23"
    opening_grant_rc: int = 1000
    match_day_grant_rc: int = 1000

    # Provider settings (D-009)
    lolesports_api: str = "https://esports-api.lolesports.com/persisted/gw"
    lolesports_feed: str = "https://feed.lolesports.com/livestats/v1"
    # Public key embedded in the lolesports website; not a secret.
    lolesports_api_key: str = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
    lolesports_worlds_league_id: str = "98767975604431411"
    leaguepedia_mode: str = "mock"  # "mock" until bot credentials exist
    leaguepedia_bot_user: str = ""
    leaguepedia_bot_password: str = ""

    # Market behaviour
    quote_ttl_seconds: int = 20
    settle_delay_seconds: int = 600  # data must be unchanged this long before grading
    hold_void_after_hours: int = 48  # unresolved markets void after this
    max_decimal_odds: str = "100.00"
    min_probability: str = "0.01"

    session_days: int = 60
    cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
