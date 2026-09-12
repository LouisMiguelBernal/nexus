"""
Verification: geopolitical risk scoring and its effect on the macro gate.

Two invariants matter more than the exact numbers:

  1. **Unavailable is not zero.** A dead feed must not read as "no risk". The
     score renormalises over the sources that answered, and reports ``None``
     when none did.
  2. **The overlay can only restrict.** Folding geo risk into the calendar gate
     may tighten every axis; it may never loosen one, and it may never re-open
     positions the calendar closed.
"""

import pytest

from backend.geo import instability
from backend.macro.gate import GateStatus, MacroGate


@pytest.fixture(autouse=True)
def _clear_smoothing():
    """The score carries EWMA memory between calls; tests must not inherit it."""
    instability.reset_state()
    yield
    instability.reset_state()


def _snapshot(**overrides) -> dict:
    base = {
        "seismic": {"available": True, "events": []},
        "disasters": {"available": True, "events": []},
        "space_weather": {"available": True, "geomagnetic": 0, "radiation": 0, "radio_blackout": 0},
        "wires": {"available": True, "items": []},
        "natural": {"available": True, "events": [], "by_category": {}},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_quiet_world_scores_near_zero():
    result = instability.compute(_snapshot(), smooth=False)
    assert result["score"] == pytest.approx(0.0, abs=1.0)
    assert result["band"] == "normal"


def test_all_sources_down_reports_unknown_not_safe():
    dead = {
        k: {"available": False, "events": []}
        for k in ("seismic", "disasters", "space_weather", "wires", "natural")
    }
    result = instability.compute(dead, smooth=False)
    assert result["score"] is None
    assert result["band"] == "unknown"
    assert result["available_weight"] == 0.0


def test_partial_coverage_renormalises_and_is_reported():
    """One live source still scores, but coverage says how thin the read is."""
    snap = _snapshot(
        seismic={"available": False, "events": []},
        disasters={"available": False, "events": []},
        space_weather={"available": False},
        natural={"available": False},
    )
    result = instability.compute(snap, smooth=False)
    assert result["score"] is not None
    assert 0.0 < result["available_weight"] < 1.0
    assert result["components"]["seismic"] is None


def test_conflict_lexicon_drives_the_score():
    hot = _snapshot(
        wires={
            "available": True,
            "items": [
                {"title": "Missile strike closes Strait of Hormuz", "summary": "oil supply halted"},
                {"title": "New sanctions and export ban announced", "summary": "escalation feared"},
                {"title": "Coup attempt triggers state of emergency", "summary": ""},
            ],
        }
    )
    quiet = instability.compute(_snapshot(), smooth=False)
    instability.reset_state()
    loud = instability.compute(hot, smooth=False)
    assert loud["score"] > quiet["score"] + 20
    assert loud["components"]["conflict"] > 50


def test_de_escalation_terms_reduce_pressure():
    escalating = _snapshot(
        wires={
            "available": True,
            "items": [
                {"title": "Missile strike reported", "summary": "escalation"},
            ],
        }
    )
    resolving = _snapshot(
        wires={
            "available": True,
            "items": [
                {"title": "Missile strike reported", "summary": "ceasefire and peace deal agreed"},
            ],
        }
    )
    hot = instability.compute(escalating, smooth=False)["components"]["conflict"]
    instability.reset_state()
    cool = instability.compute(resolving, smooth=False)["components"]["conflict"]
    assert cool < hot


def test_single_large_quake_saturates_rather_than_pinning_composite():
    snap = _snapshot(
        seismic={
            "available": True,
            "events": [{"magnitude": 8.6, "place": "offshore", "tsunami": True}],
        }
    )
    result = instability.compute(snap, smooth=False)
    assert result["components"]["seismic"] == 100.0
    # Seismic carries 12% of the weight; it must not own the composite.
    assert result["score"] < 25


def test_score_is_bounded_under_every_source_maxed():
    snap = _snapshot(
        seismic={"available": True, "events": [{"magnitude": 9.5, "tsunami": True}]},
        disasters={"available": True, "events": [{"level": "red"}] * 12},
        space_weather={"available": True, "geomagnetic": 5, "radiation": 5, "radio_blackout": 5},
        wires={
            "available": True,
            "items": [{"title": "nuclear invasion missile sanctions coup", "summary": "escalation blockade"}]
            * 20,
        },
    )
    result = instability.compute(snap, smooth=False)
    assert 0.0 <= result["score"] <= 100.0
    assert result["band"] == "critical"


def test_smoothing_spikes_up_immediately_and_decays_slowly():
    hot = _snapshot(disasters={"available": True, "events": [{"level": "red"}] * 3})
    spike = instability.compute(hot, smooth=True)["score"]
    assert spike > 0

    calm = instability.compute(_snapshot(), smooth=True)["score"]
    # Decays, but nowhere near instantly - a gate that flickers open the moment
    # a headline ages out is worse than useless under leverage.
    assert 0 < calm < spike
    assert calm > spike * 0.5


def test_worldmonitor_enrichment_is_optional():
    without = instability.compute(_snapshot(), smooth=False)
    assert without["enriched"] is False
    assert without["components"]["instability"] is None

    instability.reset_state()
    with_wm = instability.compute(
        _snapshot(),
        {
            "available": True,
            "peak_score": 90.0,
            "mean_top5": 70.0,
            "countries": [{"country": "X", "score": 90.0}],
        },
        smooth=False,
    )
    assert with_wm["enriched"] is True
    assert with_wm["components"]["instability"] == 80.0
    assert with_wm["score"] > without["score"]


def test_cyber_scores_against_its_own_base_rate():
    """A normal week is quiet; a fixed threshold used to score one at 80/100."""
    normal = _snapshot(cyber={"available": True, "added_7d": 9, "added_30d": 37, "ransomware_7d": 0})
    assert instability.compute(normal, smooth=False)["components"]["cyber"] < 10

    instability.reset_state()
    surge = _snapshot(cyber={"available": True, "added_7d": 30, "added_30d": 37, "ransomware_7d": 3})
    assert instability.compute(surge, smooth=False)["components"]["cyber"] == 100.0


def test_cyber_ransomware_entries_weigh_double():
    plain = _snapshot(cyber={"available": True, "added_7d": 14, "added_30d": 40, "ransomware_7d": 0})
    ransom = _snapshot(cyber={"available": True, "added_7d": 14, "added_30d": 40, "ransomware_7d": 5})
    a = instability.compute(plain, smooth=False)["components"]["cyber"]
    instability.reset_state()
    b = instability.compute(ransom, smooth=False)["components"]["cyber"]
    assert b > a


def test_missing_cyber_feed_is_not_scored_as_calm():
    result = instability.compute(_snapshot(), smooth=False)
    assert result["components"]["cyber"] is None


def test_worldmonitor_sandbox_samples_are_never_scored():
    """
    Sandbox fixtures are schema-valid samples, not observations. Letting them
    into the composite would put invented numbers into the macro gate.
    """
    sample = {
        "available": True,
        "sample": True,
        "peak_score": 95.0,
        "mean_top5": 90.0,
        "countries": [{"country": "X", "score": 95.0}],
    }
    result = instability.compute(_snapshot(), sample, smooth=False)
    assert result["components"]["instability"] is None

    instability.reset_state()
    live = {**sample, "sample": False}
    assert instability.compute(_snapshot(), live, smooth=False)["components"]["instability"] is not None


def test_worldmonitor_reports_why_it_is_unavailable():
    """'No key' and 'unreachable' are different states and must read differently."""
    from backend.geo import worldmonitor

    state = worldmonitor.status()
    assert state["mode"] in ("live", "sandbox", "unavailable", "disabled")
    if state["mode"] == "unavailable":
        assert "key" in (state["reason"] or "")


# ---------------------------------------------------------------------------
# Macro gate overlay
# ---------------------------------------------------------------------------


class _NoEventsCalendar:
    def get_active_danger_windows(self):
        return []


class _Tier1Calendar:
    """One active Tier-1 window, the most restrictive calendar state."""

    class _Event:
        tier = "Tier1_Critical"
        name = "FOMC"
        minutes_until = 30.0
        danger_window_hours = 2
        timestamp = 0.0

    def get_active_danger_windows(self):
        return [self._Event()]


def test_gate_is_calendar_only_when_no_geo_reading():
    gate = MacroGate(_NoEventsCalendar())
    status = gate.evaluate()
    assert status.is_restricted is False
    assert status.geo_score is None
    assert status.geo_band == "unknown"


def test_geo_below_watch_threshold_does_not_restrict():
    gate = MacroGate(_NoEventsCalendar())
    gate.set_geo_risk(25.0, band="normal")
    status = gate.evaluate()
    assert status.is_restricted is False
    assert status.geo_tier is None


def test_critical_geo_alone_closes_new_positions():
    gate = MacroGate(_NoEventsCalendar())
    gate.set_geo_risk(85.0, band="critical")
    status = gate.evaluate()
    assert status.is_restricted is True
    assert status.new_positions_allowed is False
    assert status.leverage_cap == 3
    assert status.geo_tier == "Tier1_Critical"
    assert "geo" in status.sources
    # With no calendar event, the status still has to say why it is restricted.
    assert "Geopolitical" in (status.active_event or "")


def test_overlay_can_only_tighten_never_loosen():
    """A mild geo reading must not relax an active Tier-1 calendar window."""
    gate = MacroGate(_Tier1Calendar())
    strict = gate.evaluate()
    assert strict.new_positions_allowed is False

    gate.set_geo_risk(45.0, band="watch")  # Tier3-equivalent: much looser
    relaxed = gate.evaluate()
    assert relaxed.leverage_cap == strict.leverage_cap
    assert relaxed.max_position_pct == strict.max_position_pct
    assert relaxed.confidence_threshold == strict.confidence_threshold
    assert relaxed.new_positions_allowed is False


def test_calendar_and_geo_compose_to_the_tightest_constraint():
    gate = MacroGate(_Tier1Calendar())
    gate.set_geo_risk(85.0, band="critical")
    status = gate.evaluate()
    assert status.sources == ["calendar", "geo"]
    assert status.leverage_cap == 3
    assert status.new_positions_allowed is False


def test_clearing_geo_risk_restores_calendar_only_behaviour():
    gate = MacroGate(_NoEventsCalendar())
    gate.set_geo_risk(85.0, band="critical")
    assert gate.evaluate().is_restricted is True

    gate.set_geo_risk(None, band="unknown")
    status = gate.evaluate()
    assert status.is_restricted is False
    assert status.geo_score is None


def test_status_dict_keeps_its_existing_keys():
    """The frontend binds these names; adding fields must not remove any."""
    status = GateStatus().to_dict()
    for key in (
        "is_restricted",
        "status",
        "active_tier",
        "active_event",
        "confidence_threshold",
        "max_position_pct",
        "leverage_cap",
        "new_positions_allowed",
        "minutes_until_event",
        "minutes_until_clear",
    ):
        assert key in status, f"missing legacy key {key}"
    for key in ("geo_score", "geo_band", "geo_tier", "sources"):
        assert key in status, f"missing new key {key}"
