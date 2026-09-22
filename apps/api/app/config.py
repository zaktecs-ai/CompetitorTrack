"""Application configuration.

Every field on :class:`Settings` is one variable of the ``[api]`` section of
``.env.example`` (§A12), read by *both* the ``api`` and the ``scheduler``
service — they run from the same image (§A2).

That pairing is enforced, not merely documented: ``tools/check_env_example.py``
parses this module and the ``[api]`` section of ``.env.example`` and fails when
either side has a variable the other does not. Add a setting in both places or
not at all.

Values are read from the process environment only. Nothing here loads a
``.env`` file: on the server Docker Compose injects the variables, and a
silently-loaded file next to the code is exactly how a development value ends
up in production.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProxyMode = Literal["off", "on_block", "always"]

#: SQLAlchemy URL prefix we insist on. psycopg 3 is named explicitly because the
#: bare ``postgresql://`` default differs between SQLAlchemy 2.0 and 2.1 (§A3).
REQUIRED_DB_URL_PREFIX = "postgresql+psycopg://"

#: Origins for which a non-Secure cookie is tolerable (the local HTTP override).
LOCAL_ORIGIN_PREFIXES = ("http://localhost", "http://127.0.0.1")

#: The only placeholder the User-Agent template may contain (§A6.2, D0.11).
USER_AGENT_ORIGIN_PLACEHOLDER = "{PUBLIC_ORIGIN}"

#: ``/api/health`` reports 503 once the scheduler heartbeat is older than this
#: (§A12). ``/api/health/ready`` ignores it — it is the deploy gate.
HEARTBEAT_MAX_AGE_SECONDS = 300

#: Fernet keys are urlsafe-base64 of exactly 32 bytes.
FERNET_KEY_BYTES = 32

_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class Settings(BaseSettings):
    """The ``[api]`` environment section, validated at import of the process."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    # --- database ---
    DATABASE_URL: str

    # --- auth (consumed from P2; validated here so a bad value fails at boot) ---
    JWT_SECRET: str
    ACCESS_TOKEN_MINUTES: int = Field(default=15, ge=1, le=1440)
    REFRESH_TOKEN_DAYS: int = Field(default=14, ge=1, le=365)
    REFRESH_GRACE_SECONDS: int = Field(default=30, ge=0, le=300)
    MASTER_ENCRYPTION_KEYS: str

    # --- origin and cookies ---
    PUBLIC_ORIGIN: str = "http://localhost"
    COOKIE_SECURE: bool = True

    # --- platform mailer for auth emails (§A8.6); empty = log the links ---
    PLATFORM_SMTP_URL: str = ""
    PLATFORM_FROM_EMAIL: str = ""

    # --- scraper (§A6); values below are the Phase 0 verdict (docs/PHASE0_FINDINGS.md §6) ---
    SCRAPE_INTERVAL_MINUTES: int = Field(default=360, ge=1)
    MAX_PAGES: int = Field(default=4, ge=1, le=20)
    POLITE_DELAY_SECONDS: float = Field(default=2.5, ge=0.0, le=60.0)
    SCRAPER_CONCURRENCY: int = Field(default=2, ge=1, le=16)
    SCRAPER_USER_AGENT: str = "CompetitorTrackBot/1.0 (+{PUBLIC_ORIGIN}/bot)"
    SCRAPER_PROXY_URLS: str = ""
    SCRAPER_PROXY_MODE: ProxyMode | None = None

    # --- background work ---
    DIGEST_TICK_MINUTES: int = Field(default=15, ge=1)
    RUN_STALE_MINUTES: int = Field(default=30, ge=1)

    # --- AI insights (§A9) ---
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # --- logging ---
    LOG_LEVEL: str = "INFO"

    # ------------------------------------------------------------------ #
    # field validators
    # ------------------------------------------------------------------ #

    @field_validator("DATABASE_URL")
    @classmethod
    def _check_db_url(cls, value: str) -> str:
        if not value.startswith(REQUIRED_DB_URL_PREFIX):
            raise ValueError(
                f"DATABASE_URL must name the driver explicitly and start with "
                f"{REQUIRED_DB_URL_PREFIX!r}"
            )
        return value

    @field_validator("JWT_SECRET")
    @classmethod
    def _check_jwt_secret(cls, value: str) -> str:
        # HS256 with a 256-bit secret (§A10.2). 32 characters is the floor, not
        # a recommendation: generate with `openssl rand -base64 48`.
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters (256 bits)")
        return value

    @field_validator("MASTER_ENCRYPTION_KEYS")
    @classmethod
    def _check_master_keys(cls, value: str) -> str:
        keys = [part.strip() for part in value.split(",") if part.strip()]
        if not keys:
            raise ValueError("MASTER_ENCRYPTION_KEYS must contain at least one Fernet key")
        for index, key in enumerate(keys):
            try:
                raw = base64.urlsafe_b64decode(key.encode("ascii"))
            except Exception as exc:  # any decode failure is the same answer
                raise ValueError(f"MASTER_ENCRYPTION_KEYS[{index}] is not urlsafe base64") from exc
            if len(raw) != FERNET_KEY_BYTES:
                raise ValueError(
                    f"MASTER_ENCRYPTION_KEYS[{index}] decodes to {len(raw)} bytes, "
                    f"expected {FERNET_KEY_BYTES} (generate with Fernet.generate_key())"
                )
        return ",".join(keys)

    @field_validator("PUBLIC_ORIGIN")
    @classmethod
    def _check_public_origin(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("PUBLIC_ORIGIN must start with http:// or https://")
        remainder = value.split("://", 1)[1]
        if not remainder or "/" in remainder:
            raise ValueError("PUBLIC_ORIGIN must be scheme + host only, with no path")
        return value

    @field_validator("SCRAPER_USER_AGENT")
    @classmethod
    def _check_user_agent(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("SCRAPER_USER_AGENT must not be empty")
        if "\n" in value or "\r" in value:
            raise ValueError("SCRAPER_USER_AGENT must be a single line")
        leftovers = value.replace(USER_AGENT_ORIGIN_PLACEHOLDER, "")
        if "{" in leftovers or "}" in leftovers:
            raise ValueError(
                "SCRAPER_USER_AGENT may only contain the "
                f"{USER_AGENT_ORIGIN_PLACEHOLDER} placeholder"
            )
        return value

    @field_validator("LOG_LEVEL")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}")
        return level

    @field_validator("SCRAPER_PROXY_MODE", mode="before")
    @classmethod
    def _blank_proxy_mode_is_unset(cls, value: object) -> object:
        # `.env.example` ships the variable present-but-empty; empty means
        # "unset", which §A12 resolves from SCRAPER_PROXY_URLS below.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    # ------------------------------------------------------------------ #
    # cross-field resolution
    # ------------------------------------------------------------------ #

    @model_validator(mode="after")
    def _resolve(self) -> Settings:
        if self.SCRAPER_PROXY_MODE is None:
            # Unset resolves to on_block when proxies exist, off otherwise (§A12).
            self.SCRAPER_PROXY_MODE = "on_block" if self.proxy_urls else "off"
        if self.SCRAPER_PROXY_MODE != "off" and not self.proxy_urls:
            raise ValueError(
                f"SCRAPER_PROXY_MODE={self.SCRAPER_PROXY_MODE} needs at least one "
                "URL in SCRAPER_PROXY_URLS"
            )
        if not self.COOKIE_SECURE and not self.is_local_origin:
            raise ValueError(
                "COOKIE_SECURE=false is only allowed for a localhost PUBLIC_ORIGIN "
                "(the local HTTP override); it would ship session cookies in clear"
            )
        return self

    # ------------------------------------------------------------------ #
    # derived values
    # ------------------------------------------------------------------ #

    @property
    def proxy_urls(self) -> list[str]:
        """Configured proxies, in round-robin order. Empty when direct-only."""
        return [part.strip() for part in self.SCRAPER_PROXY_URLS.split(",") if part.strip()]

    @property
    def proxy_mode(self) -> ProxyMode:
        """The resolved mode; never ``None`` after validation."""
        assert self.SCRAPER_PROXY_MODE is not None  # noqa: S101 - set in _resolve
        return self.SCRAPER_PROXY_MODE

    @property
    def is_local_origin(self) -> bool:
        return self.PUBLIC_ORIGIN.startswith(LOCAL_ORIGIN_PREFIXES)

    @property
    def user_agent(self) -> str:
        """The User-Agent actually sent, with ``{PUBLIC_ORIGIN}`` filled in.

        D0.11 left an open item: the honest bot UA advertises ``/bot`` on an
        origin the probe hard-coded as ``competitortrack.example.com``. Building
        the string from ``PUBLIC_ORIGIN`` at runtime closes it — a placeholder
        origin can no longer reach production, because the origin is validated
        and the page it points at is served by the same deployment.
        """
        return self.SCRAPER_USER_AGENT.replace(USER_AGENT_ORIGIN_PLACEHOLDER, self.PUBLIC_ORIGIN)

    @property
    def bot_page_url(self) -> str:
        return f"{self.PUBLIC_ORIGIN}/bot"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, validated once.

    Tests that need a different environment call ``get_settings.cache_clear()``.
    """
    return Settings()  # type: ignore[call-arg]  # values come from the environment
