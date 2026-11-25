from __future__ import annotations

import math

import pytest

from sakshya.links.terms import agreement_term, finalize, place_term, time_term
from sakshya.model import Link, Term, verbal


def _link(terms: list[Term], sources: list[str]) -> Link:
    return Link(
        "L1",
        "co_presence",
        "phone:+919800000000",
        "E01:1",
        "entity",
        "obs",
        "test",
        terms=terms,
        sources=sources,
        status="candidate",
    )


def test_time_term_rewards_close_events_and_penalises_far_ones() -> None:
    near = time_term(5, 0, 30**2, 3600, "cdr", "call")
    far = time_term(600, 0, 30**2, 3600, "cdr", "call")
    assert near.w > 1.5
    assert far.w < 0
    expected = math.log10(3600 * math.exp(-25 / 1800) / math.sqrt(2 * math.pi * 900))
    assert near.w == pytest.approx(expected)


def test_place_term_matches_closed_form() -> None:
    term = place_term(100.0, 300.0, 50.0, 5000.0, "tower", "cell")
    sigma2 = (300.0**2 + 50.0**2) / 4
    expected = math.log10(math.pi * 5000.0**2 / (2 * math.pi * sigma2)) - 100.0**2 / (2 * sigma2 * math.log(10))
    assert term.w == pytest.approx(expected)
    assert place_term(4000.0, 300.0, 50.0, 5000.0, "tower", "cell").w < 0


def test_agreement_term_uses_fellegi_sunter_weights() -> None:
    assert agreement_term("name", True, 0.95, 0.01, "kyc", "").w == pytest.approx(math.log10(95))
    assert agreement_term("name", False, 0.95, 0.01, "kyc", "").w == pytest.approx(math.log10(0.05 / 0.99))


def test_each_source_is_capped_and_one_source_cannot_carry_a_link() -> None:
    single = finalize(_link([Term("time", 3.0, "cdr", ""), Term("place", 3.0, "cdr", "")], ["cdr"]), 4.0, 2.0, 2, 1.0)
    assert single.w == pytest.approx(4.0)
    assert single.status == "candidate"
    assert "single source" in single.note
    double = finalize(
        _link([Term("time", 1.5, "cdr", ""), Term("place", 1.5, "atm_journal", "")], ["cdr", "atm_journal"]), 4.0, 2.0, 2, 1.0
    )
    assert double.status == "inferred"


def test_calibration_scales_reported_strength_only() -> None:
    link = finalize(
        _link([Term("time", 1.5, "cdr", ""), Term("place", 1.5, "atm_journal", "")], ["cdr", "atm_journal"]), 4.0, 2.0, 2, 0.5
    )
    assert link.w == pytest.approx(3.0)
    assert link.w_calibrated == pytest.approx(1.5)
    assert link.status == "inferred"


def test_verbal_scale_is_monotonic() -> None:
    labels = [verbal(w) for w in (0.5, 1.5, 2.5, 3.5, 4.5, 6.5)]
    assert len(set(labels)) >= 4
