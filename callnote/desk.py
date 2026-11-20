"""The desk's side: the callable swap with the issuer, its risks and its hedge.

The issuer does not want fixed-rate callable debt. It swaps it with the desk: the desk pays the note's
fixed coupon and receives SOFR + the issuer's funding spread, and the desk can cancel the swap on every
call date. When the desk cancels, the issuer calls the note.

Paying c and receiving SOFR + x is the same as paying (c - x) against SOFR flat. So the desk is:
pay fixed (c - x) to maturity + right to cancel = long a Bermudan receiver swaption struck at c - x.
The floating leg is worth par on reset dates, so the desk position is
    1 - (clean value of a callable bond paying c - x, on the OIS curve)
I take the floating leg as worth par today too (its next reset is a few months away, its rate risk is tiny).
"""

from dataclasses import replace

import numpy as np
from scipy.stats import norm

from .curve import forward_swap
from .hull_white import Tree
from .pricing import MEAN_REVERSION, calibrate, cube_vol


def swap_leg(note, funding_spread):
    """The fixed leg the desk pays: the note's schedule and calls, with coupon c - x."""
    return replace(note, coupon=note.coupon - funding_spread)


def desk_value(leg, curve, cube, a=MEAN_REVERSION):
    """Value of the callable swap for the desk, per 1 of notional (`leg` from swap_leg)."""
    sigma, _ = calibrate(leg, curve, cube, a)
    tree = Tree(curve, a, sigma, leg.maturity_years)
    t, cf = leg.cash_flows()
    callable_ = tree.price_callable(t, cf, leg.call_times(), 0.0, leg.call_prices())[0]
    plain = np.sum(cf * curve.df(t))
    return {"swap_with_call": 1 - (callable_ - leg.accrued()),
            "swap_without_call": 1 - (plain - leg.accrued()),
            "bermudan": plain - callable_}


def swap_value(curve, tenor, strike):
    """Receiver swap (receive fixed `strike`) starting today, per 1 of notional."""
    rate, annuity = forward_swap(curve, 0.0, tenor)
    return (strike - rate) * annuity


def straddle_value(curve, cube, expiry, end, strike, vol_shift_bp=0.0):
    """Payer + receiver swaption (Bachelier, normal vol from the cube), per 1 of notional."""
    rate, annuity = forward_swap(curve, expiry, end)
    vol = cube_vol(cube, expiry, end - expiry) + vol_shift_bp / 1e4
    sd = vol * np.sqrt(expiry)
    d = (rate - strike) / sd
    return annuity * ((rate - strike) * (2 * norm.cdf(d) - 1) + 2 * sd * norm.pdf(d))


def hedge(leg, curve, cube, a=MEAN_REVERSION):
    """Delta hedge with par swaps on each curve pillar, vega hedge with an ATM coterminal straddle.

    - key-rate DV01: desk value change when one par swap rate moves by +1bp.
      A par swap of the same tenor has a DV01 of (its annuity x 1bp) on that pillar only,
      so the hedge notional of each swap is just DV01 / swap DV01.
    - vega: desk value change when all swaption vols go up by 1bp (sigma recalibrated).
      The desk is long vol, so it sells ATM straddles on the swaption 'first call -> maturity'.
    """
    base = desk_value(leg, curve, cube, a)["swap_with_call"]
    last = curve.tenors[np.searchsorted(curve.tenors, leg.maturity_years)]   # first pillar after maturity
    pillars = [p for p in curve.tenors if p <= last]
    rows = []
    for p in pillars:
        dv01 = desk_value(leg, curve.shifted(1, p), cube, a)["swap_with_call"] - base
        swap_dv01 = -forward_swap(curve, 0.0, p)[1] * 1e-4           # receiver swap loses when rates go up
        rows.append({"pillar": p, "dv01": dv01, "swap_notional": -dv01 / swap_dv01})
    vega = desk_value(leg, curve, cube + 1, a)["swap_with_call"] - base

    expiry, end = leg.call_times()[0], leg.maturity_years
    strike = forward_swap(curve, expiry, end)[0]
    straddle_vega = straddle_value(curve, cube, expiry, end, strike, 1) - straddle_value(curve, cube, expiry, end, strike)
    return {
        "base": base,
        "key_rates": rows,
        "vega": vega,
        "straddle": {"expiry": expiry, "end": end, "strike": strike, "notional": -vega / straddle_vega},
    }


def scenario_pnl(leg, curve, cube, h, rate_shift_bp=0.0, vol_shift_bp=0.0, a=MEAN_REVERSION):
    """Instant P&L (per 1 of notional) of the desk alone, delta-hedged, and delta + vega hedged."""
    new_curve = curve.shifted(rate_shift_bp)
    new_cube = cube + vol_shift_bp
    desk = desk_value(leg, new_curve, new_cube, a)["swap_with_call"] - h["base"]
    swaps = 0.0
    for row in h["key_rates"]:
        strike = forward_swap(curve, 0.0, row["pillar"])[0]
        swaps += row["swap_notional"] * swap_value(new_curve, row["pillar"], strike)
    s = h["straddle"]
    straddle = s["notional"] * (straddle_value(new_curve, cube, s["expiry"], s["end"], s["strike"], vol_shift_bp)
                                - straddle_value(curve, cube, s["expiry"], s["end"], s["strike"]))
    return {"unhedged": desk, "delta_hedged": desk + swaps, "delta_vega_hedged": desk + swaps + straddle}
