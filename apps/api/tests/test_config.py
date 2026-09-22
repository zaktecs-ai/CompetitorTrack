"""Configuration validation — the boot-time guards (§A10, §A12, D0.11)."""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from app.config import Settings

VALID_KEY = base64.urlsafe_b64encode(bytes(32)).decode()
BASE = {
    "DATABASE_URL": "postgresql+psycopg://ct:pw@db:5432/competitortrack",
    "JWT_SECRET": "x" * 40,
    "MASTER_ENCRYPTION_KEYS": VALID_KEY,
    "PUBLIC_ORIGIN": "https://app.jobsearchpk.site",
    "COOKIE_SECURE": True,
}


def make(**overrides: object) -> Settings:
    return Settings(**{**BASE, **overrides})  # type: ignore[arg-type]


def test_phase0_defaults_are_the_shipped_defaults() -> None:
    """Every number Phase 0 signed off on (docs/PHASE0_FINDINGS.md §6)."""
    settings = make()
    assert settings.SCRAPE_INTERVAL_MINUTES == 360
    assert settings.MAX_PAGES == 4
    assert settings.POLITE_DELAY_SECONDS == 2.5
    assert settings.SCRAPER_CONCURRENCY == 2
    assert settings.DIGEST_TICK_MINUTES == 15
    assert settings.RUN_STALE_MINUTES == 30
    assert settings.GEMINI_MODEL == "gemini-2.5-flash"
    assert settings.SCRAPER_USER_AGENT.startswith("CompetitorTrackBot/1.0")


def test_user_agent_interpolates_the_real_origin() -> None:
    """D0.11's open item: the UA must not advertise a placeholder origin."""
    settings = make()
    assert settings.user_agent == "CompetitorTrackBot/1.0 (+https://app.jobsearchpk.site/bot)"
    assert "{PUBLIC_ORIGIN}" not in settings.user_agent
    assert settings.bot_page_url == "https://app.jobsearchpk.site/bot"


def test_user_agent_rejects_other_placeholders() -> None:
    with pytest.raises(ValidationError, match="placeholder"):
        make(SCRAPER_USER_AGENT="Bot/1.0 (+{SOME_OTHER}/bot)")


@pytest.mark.parametrize(
    ("mode", "urls", "expected"),
    [
        (None, "", "off"),
        ("", "", "off"),
        (None, "socks5h://user:pw@proxy.example:1080", "on_block"),
        ("off", "socks5h://user:pw@proxy.example:1080", "off"),
        ("always", "socks5h://user:pw@proxy.example:1080", "always"),
    ],
)
def test_proxy_mode_resolution(mode, urls, expected) -> None:
    settings = make(SCRAPER_PROXY_MODE=mode, SCRAPER_PROXY_URLS=urls)
    assert settings.proxy_mode == expected


@pytest.mark.parametrize("mode", ["on_block", "always"])
def test_proxy_mode_without_urls_is_rejected(mode: str) -> None:
    with pytest.raises(ValidationError, match="SCRAPER_PROXY_URLS"):
        make(SCRAPER_PROXY_MODE=mode, SCRAPER_PROXY_URLS="")


def test_proxy_urls_are_split_and_trimmed() -> None:
    settings = make(
        SCRAPER_PROXY_URLS=" socks5h://a:1080 , http://b:8080 ,",
        SCRAPER_PROXY_MODE="on_block",
    )
    assert settings.proxy_urls == ["socks5h://a:1080", "http://b:8080"]


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://ct:pw@db:5432/competitortrack",
        "postgres://ct:pw@db:5432/competitortrack",
        "postgresql+asyncpg://ct:pw@db:5432/competitortrack",
    ],
)
def test_database_url_must_name_psycopg(url: str) -> None:
    with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
        make(DATABASE_URL=url)


def test_short_jwt_secret_is_rejected() -> None:
    with pytest.raises(ValidationError, match="32 characters"):
        make(JWT_SECRET="too-short")


@pytest.mark.parametrize(
    "keys",
    ["", "not-base64!!", base64.urlsafe_b64encode(bytes(16)).decode()],
)
def test_bad_master_keys_are_rejected(keys: str) -> None:
    with pytest.raises(ValidationError, match="MASTER_ENCRYPTION_KEYS"):
        make(MASTER_ENCRYPTION_KEYS=keys)


def test_master_keys_accept_a_rotation_pair() -> None:
    new_key = base64.urlsafe_b64encode(bytes(range(32))).decode()
    settings = make(MASTER_ENCRYPTION_KEYS=f"{new_key}, {VALID_KEY}")
    assert settings.MASTER_ENCRYPTION_KEYS.split(",") == [new_key, VALID_KEY]


def test_insecure_cookies_are_only_allowed_on_localhost() -> None:
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        make(COOKIE_SECURE=False)
    local = make(PUBLIC_ORIGIN="http://localhost", COOKIE_SECURE=False)
    assert local.is_local_origin is True
    assert local.user_agent.endswith("(+http://localhost/bot)")


@pytest.mark.parametrize(
    "origin",
    ["app.jobsearchpk.site", "ftp://app.jobsearchpk.site", "https://app.jobsearchpk.site/api"],
)
def test_public_origin_must_be_scheme_plus_host(origin: str) -> None:
    with pytest.raises(ValidationError, match="PUBLIC_ORIGIN"):
        make(PUBLIC_ORIGIN=origin)


def test_public_origin_trailing_slash_is_stripped() -> None:
    assert make(PUBLIC_ORIGIN="https://app.jobsearchpk.site/").PUBLIC_ORIGIN == (
        "https://app.jobsearchpk.site"
    )


def test_log_level_is_normalised_and_validated() -> None:
    assert make(LOG_LEVEL="debug").LOG_LEVEL == "DEBUG"
    with pytest.raises(ValidationError, match="LOG_LEVEL"):
        make(LOG_LEVEL="chatty")
