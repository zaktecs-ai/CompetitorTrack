"""Registrable-domain classification (D0.6).

The three redirects in the second block are the ones Phase 0 actually recorded
on the production run (docs/PHASE0_FINDINGS.md §3.7), which is why the
probe's two-label heuristic could not be kept: ``uk.theinkeylist.com`` and
``www.saltandstone.com`` must both classify as the same site as their apex,
while a redirect to an unrelated host must not.
"""

from __future__ import annotations

import pytest

from app.net.domains import (
    is_ip_literal,
    normalize_host,
    registrable_domain,
    same_registrable_domain,
)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("colourpop.com", "colourpop.com"),
        ("www.colourpop.com", "colourpop.com"),
        ("uk.theinkeylist.com", "theinkeylist.com"),
        ("WWW.SaltAndStone.COM", "saltandstone.com"),
        ("herbivorebotanicals.com.", "herbivorebotanicals.com"),
        ("shop.example.co.uk", "example.co.uk"),
        ("example.com.au", "example.com.au"),
        ("deep.sub.domain.example.org", "example.org"),
    ],
)
def test_registrable_domain(host: str, expected: str) -> None:
    assert registrable_domain(host) == expected


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("theinkeylist.com", "uk.theinkeylist.com"),
        ("saltandstone.com", "www.saltandstone.com"),
        ("herbivorebotanicals.com", "www.herbivorebotanicals.com"),
        ("shop.example.co.uk", "www.example.co.uk"),
    ],
)
def test_same_site_redirects_are_followed(left: str, right: str) -> None:
    assert same_registrable_domain(left, right) is True


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("colourpop.com", "fentybeauty.com"),
        ("example.com", "example.org"),
        ("example.co.uk", "example.co"),
        ("store.com", "store.com.evil.net"),
        ("shop.example.com", "example.com.attacker.io"),
        # Two different Shopify-hosted stores are NOT the same site: myshopify.com
        # is a private suffix, so the boundary sits below it.
        ("one.myshopify.com", "two.myshopify.com"),
    ],
)
def test_foreign_redirects_are_rejected(left: str, right: str) -> None:
    assert same_registrable_domain(left, right) is False


@pytest.mark.parametrize(
    "host",
    [
        "",
        "   ",
        "localhost",
        "co.uk",
        "127.0.0.1",
        "169.254.169.254",
        "[::1]",
        "example.com:443",
        "example.com/products.json",
        "https://example.com",
        "user@example.com",
        "exa mple.com",
        "..example.com",
        "exämple.com",
    ],
)
def test_unclassifiable_hosts_return_none(host: str) -> None:
    assert registrable_domain(host) is None


def test_unclassifiable_is_never_a_match() -> None:
    """A None on either side must not be read as equality."""
    assert same_registrable_domain("127.0.0.1", "127.0.0.1") is False
    assert same_registrable_domain("co.uk", "co.uk") is False
    assert same_registrable_domain("example.com", "not a host") is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("127.0.0.1", True),
        ("169.254.169.254", True),
        ("::1", True),
        ("[::1]", True),
        ("fd00::1", True),
        ("example.com", False),
        ("1.2.3.4.example.com", False),
    ],
)
def test_is_ip_literal(value: str, expected: bool) -> None:
    assert is_ip_literal(value) is expected


def test_normalize_host_lowercases_and_strips() -> None:
    assert normalize_host("  WWW.Example.COM.  ") == "www.example.com"
