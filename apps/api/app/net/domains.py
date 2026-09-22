"""Registrable-domain classification — the production answer to D0.6.

The Phase 0 probe compared "the last two labels, plus a small allow-list of
two-label suffixes". D0.6 records that this heuristic **must not ship**, because
a wrong verdict is not cosmetic:

* too permissive → a 3xx is followed off-site, which is an SSRF-adjacent
  security bug (§A6.9 re-runs its address check on every hop, but the hop
  should not have been followed in the first place);
* too strict → a legitimate ``www.`` or country redirect is rejected as
  ``redirected_away`` and a real store cannot be added. Phase 0 saw three of
  these on seven stores (``www.herbivorebotanicals.com``,
  ``www.saltandstone.com``, ``uk.theinkeylist.com``), so this is the common
  case, not the exotic one.

So the real Public Suffix List is used, from the ``publicsuffixlist`` package,
which bundles its data in the wheel — no network access at import, nothing to
refresh at runtime, and the pinned version in ``requirements.txt`` is the
dataset version. Refresh it deliberately, like any other dependency.

**Private-section rules are used on purpose.** ``privatesuffix()`` treats
``myshop.myshopify.com`` as the registrable domain rather than
``myshopify.com``, so two unrelated Shopify-hosted stores are correctly *not*
the same site. For a redirect-follow decision the tighter boundary is the safe
one.

Callers arrive in P3 (§A6.3 redirect classification, §A6.9 add-store
validation). This module deliberately knows nothing about HTTP.
"""

from __future__ import annotations

import ipaddress

from publicsuffixlist import PublicSuffixList

# Bundled dataset; constructed once per process.
_PSL = PublicSuffixList()

_FORBIDDEN_IN_HOST = frozenset({"/", "\\", " ", "\t", "?", "#", "@", ":"})


def is_ip_literal(host: str) -> bool:
    """True when the host is a bare IPv4/IPv6 address rather than a name.

    §A6.9 rejects IP literals outright; a store is identified by a domain.
    """
    candidate = host.strip().strip(".")
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return False
    return True


def normalize_host(value: str) -> str | None:
    """Lowercase a hostname and reject anything that is not just a hostname.

    Returns ``None`` for empty input, IP literals, hosts carrying a port, path,
    scheme or credentials, and hosts with empty labels. Stripping those parts
    off a user-supplied URL is the caller's job (§A6.9 step 1) — this function
    refuses to guess.
    """
    host = value.strip().rstrip(".").lower()
    if not host or len(host) > 253:
        return None
    if any(char in host for char in _FORBIDDEN_IN_HOST):
        return None
    if is_ip_literal(host):
        return None
    labels = host.split(".")
    if len(labels) < 2 or any(not label for label in labels):
        return None
    try:
        host.encode("ascii")
    except UnicodeEncodeError:
        # Internationalised names must reach us already punycoded; encoding here
        # would hide a mismatch between what we resolve and what we display.
        return None
    return host


def registrable_domain(host: str) -> str | None:
    """The registrable ("private") domain of ``host``, or ``None``.

    ``None`` means "cannot be classified" — an IP literal, a malformed host, or
    a host that *is* a public suffix (``co.uk``). Callers must treat ``None`` as
    "not the same site", never as a match.
    """
    normalized = normalize_host(host)
    if normalized is None:
        return None
    suffix = _PSL.privatesuffix(normalized)
    return suffix or None


def same_registrable_domain(left: str, right: str) -> bool:
    """True when both hosts belong to the same registrable domain.

    Used by §A6.3 to decide whether a 3xx is an in-store redirect to follow
    (``store.com`` → ``www.store.com``) or a ``redirected_away`` failure.
    Unclassifiable input is never a match.
    """
    left_domain = registrable_domain(left)
    if left_domain is None:
        return False
    return left_domain == registrable_domain(right)


def psl_dataset_version() -> str:
    """Version string of the bundled PSL snapshot, for diagnostics."""
    from publicsuffixlist import __version__  # local import keeps module import cheap

    return str(__version__)
