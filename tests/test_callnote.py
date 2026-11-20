from datetime import date

import numpy as np
import pytest

from callnote.curve import Curve, forward_swap
from callnote.hull_white import Tree, swaption_vol
from callnote.notes import Note

CURVE = Curve([1, 2, 5, 10, 30], [0.030, 0.031, 0.032, 0.034, 0.035])


def test_curve_reprices_par_swaps():
    for n, s in [(1, 0.030), (2, 0.031), (5, 0.032), (10, 0.034)]:
        assert forward_swap(CURVE, 0.0, n)[0] == pytest.approx(s, abs=1e-10)


def test_tree_reprices_zero_coupon_bonds():
    tree = Tree(CURVE, 0.03, 0.01, 10)
    for T in (1.0, 4.0, 10.0):
        assert tree.price_callable([T], [1.0])[0] == pytest.approx(CURVE.df(T), rel=1e-6)


def test_call_lowers_the_price_and_is_worth_more_with_vol():
    times, cf = np.arange(1.0, 9.0), np.full(8, 0.04)
    cf[-1] += 1
    calls = [3.0, 4.0, 5.0]
    plain = np.sum(cf * CURVE.df(times))
    values = []
    for sigma in (0.005, 0.01, 0.015):
        tree = Tree(CURVE, 0.03, sigma, 8)
        assert tree.price_callable(times, cf)[0] == pytest.approx(plain, rel=1e-5)
        values.append(plain - tree.price_callable(times, cf, calls)[0])
    assert 0 < values[0] < values[1] < values[2]


def test_call_probabilities_add_up_to_less_than_one():
    times, cf = np.arange(1.0, 9.0), np.full(8, 0.05)
    cf[-1] += 1
    tree = Tree(CURVE, 0.03, 0.01, 8)
    _, called = tree.price_callable(times, cf, [2.0, 4.0, 6.0])
    p = np.array(list(tree.call_probabilities(called).values()))
    assert np.all(p >= 0) and 0 < p.sum() < 1


def test_swaption_vol_close_to_sigma_without_mean_reversion():
    # with a ~ 0 and a short swap, the swap rate moves almost one for one with the short rate
    assert swaption_vol(CURVE, 1e-6, 0.01, 2.0, 3.0) == pytest.approx(0.01, rel=0.05)


def test_note_schedule_and_accrued():
    gs = Note("GS", "USD", 0.0535, 2, "30/360", date(2035, 4, 21), [date(2028, 7, 21)])
    assert gs.last_coupon == date(2026, 10, 21)
    assert gs.coupon_dates[0] == date(2027, 4, 21) and len(gs.coupon_dates) == 17
    assert gs.accrued() == pytest.approx(0.0535 * 8 / 360)
    assert gs.call_prices()[0] == pytest.approx(1 + 0.0535 / 4)   # called mid-period: par + 3 months of coupon


def test_note_can_be_valued_on_another_date():
    from dataclasses import replace
    gs = Note("GS", "USD", 0.0535, 2, "30/360", date(2035, 4, 21), [date(2028, 4, 21)])
    at_issue = replace(gs, valuation=date(2026, 4, 24))
    assert at_issue.last_coupon == date(2026, 4, 21)
    assert at_issue.accrued() == pytest.approx(0.0535 * 3 / 360)
    assert at_issue.maturity_years > gs.maturity_years
