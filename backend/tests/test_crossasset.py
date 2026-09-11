"""
Verification: cross-asset reference data helpers.

These are the pure functions in the OpenBB-shaped layer - the parts that can be
tested without an upstream. The network paths are exercised by the live probe,
not here.
"""

import pytest

from backend.crossasset.equity import _open_interest_is_credible, max_pain
from backend.crossasset.fred import _nearest_year_ago, _parse_csv


# ---------------------------------------------------------------------------
# Option chain
# ---------------------------------------------------------------------------

def _leg(pairs):
    return [{"strike": s, "open_interest": oi} for s, oi in pairs]


def test_max_pain_is_none_without_open_interest():
    """
    A newly listed expiry has strikes but no open contracts. Every strike then
    scores a pain of zero and the lowest wins on tie-break, which reports a
    meaningless number that looks authoritative - it showed 40 against a spot
    of 178.
    """
    calls = _leg([(40.0, 0.0), (180.0, 0.0), (300.0, 0.0)])
    puts = _leg([(40.0, 0.0), (180.0, 0.0)])
    assert max_pain(calls, puts) is None


def test_max_pain_is_none_with_no_strikes():
    assert max_pain([], []) is None


def test_max_pain_lands_where_open_interest_concentrates():
    # Everything is written at 100; that is where the least premium survives.
    calls = _leg([(90.0, 10.0), (100.0, 5000.0), (110.0, 10.0)])
    puts = _leg([(90.0, 10.0), (100.0, 5000.0), (110.0, 10.0)])
    assert max_pain(calls, puts) == 100.0


def test_max_pain_handles_missing_open_interest_fields():
    calls = [{"strike": 50.0, "open_interest": None}, {"strike": 60.0, "open_interest": 100.0}]
    assert max_pain(calls, []) == 50.0


def test_open_interest_credibility_rejects_yahoo_zeroes():
    """
    Yahoo currently serves openInterest 0 on near expiries while the same chain
    shows hundreds of thousands of contracts of volume, and two-digit totals on
    longer tenors. Both are unusable; anything derived from them is fiction.
    """
    assert _open_interest_is_credible(0, 484_661) is False
    assert _open_interest_is_credible(78, 7_282) is False


def test_open_interest_credibility_accepts_a_healthy_chain():
    # OI accumulates over a contract's life, so it normally exceeds one day's
    # volume on an established chain.
    assert _open_interest_is_credible(5_000_000, 400_000) is True
    # Nothing to contradict it when the chain has not traded today.
    assert _open_interest_is_credible(100, 0) is True


# ---------------------------------------------------------------------------
# FRED CSV
# ---------------------------------------------------------------------------

def test_parse_csv_skips_missing_observations():
    """FRED writes '.' for a missing print; those rows are not zeros."""
    csv = "observation_date,DGS10\n2026-01-01,.\n2026-01-02,4.15\n2026-01-03,4.20\n"
    points = _parse_csv(csv)
    assert [p["value"] for p in points] == [4.15, 4.20]


def test_parse_csv_tolerates_a_ragged_tail():
    csv = "observation_date,X\n2026-01-02,1.0\n\nbroken\n"
    assert len(_parse_csv(csv)) == 1


@pytest.mark.parametrize(
    "dates,latest,expected",
    [
        # Monthly series: a year back is 12 rows.
        ([f"2025-{m:02d}-01" for m in range(1, 13)] + ["2026-01-01"], "2026-01-01", "2025-01-01"),
        # Quarterly series: a year back is 4 rows, not 12.
        (["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01", "2026-01-01"], "2026-01-01", "2025-01-01"),
    ],
)
def test_year_ago_is_found_by_date_not_by_offset(dates, latest, expected):
    points = [{"date": d, "value": 1.0} for d in dates]
    hit = _nearest_year_ago(points, latest)
    assert hit is not None
    assert hit["date"] == expected


def test_year_ago_is_none_when_the_series_is_too_young():
    """A short series must report no YoY rather than a wrong one."""
    points = [{"date": "2026-07-01", "value": 1.0}, {"date": "2026-08-01", "value": 2.0}]
    assert _nearest_year_ago(points, "2026-08-01") is None
