"""
Verification: Binance ban-aware backoff (rate_guard).

Regression guard for the self-inflicted outage where the 30s/2s REST pollers
kept hammering fapi.binance.com during an active 418 IP ban, extending it.

Covers:
  - a 418 with an explicit "banned until <epoch-ms>" deadline suspends the host
    until that time and lifts exactly once past it,
  - a 429 without a deadline falls back to exponential backoff,
  - non-Binance / healthy responses never trip the guard,
  - the cooldown is never shortened by a later, nearer soft-backoff.
"""

import time

import pytest

from backend.ingestion import rate_guard as rg
from backend.ingestion.rate_guard import BINANCE_FUTURES_HOST as HOST


@pytest.fixture(autouse=True)
def _clean_guard():
    rg.reset()
    yield
    rg.reset()


def test_healthy_response_never_trips():
    assert rg.record_response(HOST, 200, '{"openInterest":"123"}') is False
    assert rg.should_skip(HOST) is False
    assert rg.cooldown_remaining(HOST) == 0.0


def test_418_with_deadline_suspends_until_epoch():
    until_ms = int((time.time() + 120) * 1000)
    body = f'{{"code":-1003,"msg":"Way too many requests; IP(1.2.3.4) banned until {until_ms}."}}'

    tripped = rg.record_response(HOST, 418, body)

    assert tripped is True
    assert rg.should_skip(HOST) is True
    remaining = rg.cooldown_remaining(HOST)
    # ~120s deadline (+1s pad), allow slack for test execution time.
    assert 100 <= remaining <= 122


def test_cooldown_lifts_after_deadline_passes():
    past_ms = int((time.time() - 5) * 1000)  # already expired
    body = f'{{"code":-1003,"msg":"banned until {past_ms}."}}'
    rg.record_response(HOST, 418, body)
    # Deadline is in the past → guard should report clear on next check.
    assert rg.should_skip(HOST) is False
    assert rg.cooldown_remaining(HOST) == 0.0


def test_429_without_deadline_uses_exponential_backoff():
    # First rate-limit → base delay (60s).
    assert rg.record_response(HOST, 429, "rate limited") is True
    first = rg.cooldown_remaining(HOST)
    assert 55 <= first <= 61

    # Force the first window to expire, then a second 429 should escalate.
    rg.reset(HOST)
    rg.record_response(HOST, 429, "rate limited")   # step 0 → 60s
    rg.record_response(HOST, 429, "rate limited")   # step 1 → 120s
    second = rg.cooldown_remaining(HOST)
    assert 115 <= second <= 121


def test_minus_1003_in_body_trips_even_on_200():
    # Some proxies rewrite the status but keep the -1003 payload.
    assert rg.record_response(HOST, 200, '{"code":-1003,"msg":"banned"}') is True
    assert rg.should_skip(HOST) is True


def test_success_resets_soft_backoff():
    rg.record_response(HOST, 429, "rate limited")
    rg.reset(HOST)  # simulate window expiry
    rg.record_success(HOST)
    # Next 429 should start from base again, not escalate.
    rg.record_response(HOST, 429, "rate limited")
    assert 55 <= rg.cooldown_remaining(HOST) <= 61


def test_cooldown_not_shortened_by_later_soft_backoff():
    until_ms = int((time.time() + 300) * 1000)
    rg.record_response(HOST, 418, f'banned until {until_ms}')
    long_remaining = rg.cooldown_remaining(HOST)
    assert long_remaining > 250

    # A subsequent plain 429 (60s) must NOT undercut the 300s hard deadline.
    rg.record_response(HOST, 429, "rate limited")
    assert rg.cooldown_remaining(HOST) > 250
