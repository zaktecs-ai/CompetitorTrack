"""Advisory locks: key derivation and real mutual exclusion (§A6.2, §A6.11)."""

from __future__ import annotations

import pytest

from app.locks import (
    SCHEDULER_LOCK_NAME,
    AdvisoryLock,
    LockUnavailable,
    advisory_key,
    domain_lock_name,
)

INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1


def test_key_is_stable_over_time() -> None:
    """Hard-coded expectations on purpose.

    If someone swaps the hash, changes the digest size or the byte order, two
    processes deployed at different times would take *different* keys and both
    believe they are the singleton. That failure is silent, so the constant is
    pinned here rather than recomputed from the same code under test.
    """
    assert advisory_key(SCHEDULER_LOCK_NAME) == -8111429485687993114
    assert advisory_key(domain_lock_name("example.com")) == -7536494811583353003
    assert advisory_key(domain_lock_name("colourpop.com")) == 483614500529189486


def test_domain_lock_name_shape() -> None:
    assert domain_lock_name("colourpop.com") == "ct:domain:colourpop.com"


@pytest.mark.parametrize(
    "name",
    [SCHEDULER_LOCK_NAME, domain_lock_name("colourpop.com"), domain_lock_name("a" * 200)],
)
def test_keys_fit_a_signed_bigint(name: str) -> None:
    assert INT64_MIN <= advisory_key(name) <= INT64_MAX


def test_different_domains_get_different_keys() -> None:
    keys = {advisory_key(domain_lock_name(d)) for d in ("a.com", "b.com", "www.a.com")}
    assert len(keys) == 3


@pytest.mark.db
async def test_second_holder_is_refused_then_allowed_after_release(engine) -> None:
    first = AdvisoryLock("ct:test:exclusive")
    second = AdvisoryLock("ct:test:exclusive")

    assert await first.try_acquire() is True
    assert first.held is True
    assert await second.try_acquire() is False, "two sessions held the same lock"

    await first.release()
    assert first.held is False

    assert await second.try_acquire() is True
    await second.release()


@pytest.mark.db
async def test_acquire_is_idempotent_and_release_is_safe_twice(engine) -> None:
    lock = AdvisoryLock("ct:test:idempotent")
    assert await lock.try_acquire() is True
    assert await lock.try_acquire() is True
    await lock.release()
    await lock.release()  # must not raise
    assert lock.held is False


@pytest.mark.db
async def test_unrelated_names_do_not_block_each_other(engine) -> None:
    one = AdvisoryLock(domain_lock_name("colourpop.com"))
    other = AdvisoryLock(domain_lock_name("fentybeauty.com"))
    try:
        assert await one.try_acquire() is True
        assert await other.try_acquire() is True
    finally:
        await one.release()
        await other.release()


@pytest.mark.db
async def test_context_manager_raises_when_held_elsewhere(engine) -> None:
    holder = AdvisoryLock("ct:test:ctx")
    assert await holder.try_acquire() is True
    try:
        with pytest.raises(LockUnavailable):
            async with AdvisoryLock("ct:test:ctx"):
                pass
    finally:
        await holder.release()
