"""Market data, Hull-White calibration and pricing of the note (OAS, call value, call probabilities)."""

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .curve import Curve
from .hull_white import Tree, calibrate_sigma, swaption_vol

DATE = "2026-10-29"
MEAN_REVERSION = 0.03   # fixed, a usual value for USD rates


def load_market(folder="data_bloomberg"):
    """SOFR OIS curve (1-30Y) and the USD ATM normal swaption vol cube (bp) on 29/10/2026."""
    ois = pd.read_csv(f"{folder}/ois_curves_{DATE}.csv").dropna()
    # SOFR 12-30Y, taken later from the daily history (same date, 29/10/2026)
    long = pd.read_csv(f"{folder}/sofr_long_daily_2026-10-27_to_2026-11-16.csv", index_col="date").loc[DATE]
    curve = Curve(np.r_[ois["tenor"], [12, 15, 20, 25, 30]], np.r_[ois["sofr_pct"], long.values] / 100)
    cube = pd.read_csv(f"{folder}/usd_swaption_atm_cube_{DATE}.csv", index_col="expiry")
    cube.columns = cube.columns.astype(float)
    return curve, cube


def cube_vol(cube, expiry, tenor):
    """ATM normal vol (decimal) for any expiry and swap tenor, by linear interpolation in the cube."""
    by_tenor = [np.interp(expiry, cube.index, cube[c]) for c in cube.columns]
    return np.interp(tenor, cube.columns, by_tenor) / 1e4


def coterminal(note, cube):
    """The European swaptions that match the call: expiry = a call date, swap ends at the note's maturity.
    Swaps shorter than 1 year are left out (not in the cube)."""
    T, end = note.call_times(), note.maturity_years
    keep = end - T >= 1
    T = T[keep]
    return T, np.full(len(T), end), np.array([cube_vol(cube, t, end - t) for t in T])


def calibrate(note, curve, cube, a=MEAN_REVERSION):
    expiries, ends, vols = coterminal(note, cube)
    sigma = calibrate_sigma(curve, a, expiries, ends, vols)
    model = np.array([swaption_vol(curve, a, sigma, t, e) for t, e in zip(expiries, ends)])
    return sigma, pd.DataFrame({"expiry": expiries, "market_bp": vols * 1e4, "model_bp": model * 1e4})


def straight_price(note, curve, spread):
    """Same note without the call: discounted cash flows (dirty price per 1)."""
    t, cf = note.cash_flows()
    return np.sum(cf * curve.df(t) * np.exp(-spread * t))


def bond_yield(dirty, times, amounts, freq):
    return brentq(lambda y: np.sum(amounts * (1 + y / freq) ** (-freq * times)) - dirty, -0.05, 0.3)


def analyse(note, curve, cube, a=MEAN_REVERSION, sigma=None):
    """Everything about one note: OAS, Z-spread, call value, call probabilities, yields."""
    if sigma is None:
        sigma, _ = calibrate(note, curve, cube, a)
    tree = Tree(curve, a, sigma, note.maturity_years)
    t, cf = note.cash_flows()
    calls, call_px = note.call_times(), note.call_prices()
    dirty = note.price / 100 + note.accrued()

    def callable_price(spread):
        return tree.price_callable(t, cf, calls, spread, call_px)[0]

    oas = brentq(lambda s: callable_price(s) - dirty, -0.05, 0.2)
    z_spread = brentq(lambda s: straight_price(note, curve, s) - dirty, -0.05, 0.2)
    called = tree.price_callable(t, cf, calls, oas, call_px)[1]
    probs = tree.call_probabilities(called)
    p_call = np.array(list(probs.values()))
    life = np.sum(p_call * np.array(list(probs.keys()))) + (1 - p_call.sum()) * note.maturity_years

    first = calls[0]
    to_call = t < first - 1e-9
    t_call = np.r_[t[to_call], first]
    cf_call = np.r_[cf[to_call], call_px[0] + (cf[np.isclose(t, first)].sum())]
    ytm = bond_yield(dirty, t, cf, note.freq)
    ytc = bond_yield(dirty, t_call, cf_call, note.freq)
    return {
        "note": note.name,
        "price": note.price,
        "sigma_bp": sigma * 1e4,
        "oas_bp": oas * 1e4,
        "z_spread_bp": z_spread * 1e4,
        "option_cost_bp": (z_spread - oas) * 1e4,
        "straight_at_oas": 100 * (straight_price(note, curve, oas) - note.accrued()),
        "call_value": 100 * (straight_price(note, curve, oas) - dirty),
        "p_call": p_call.sum(),
        "p_first_call": p_call[0],
        "expected_life": life,
        "maturity": note.maturity_years,
        "ytm_pct": 100 * ytm,
        "ytc_pct": 100 * ytc,
        "_probs": probs,
        "_tree": tree,
        "_oas": oas,
    }


def price_at_oas(note, curve, cube, oas, a=MEAN_REVERSION, vol_shift_bp=0.0):
    """Callable and straight price (clean, %) for a given curve and vol shift, keeping the OAS fixed."""
    shifted = cube + vol_shift_bp
    sigma, _ = calibrate(note, curve, shifted, a)
    tree = Tree(curve, a, sigma, note.maturity_years)
    t, cf = note.cash_flows()
    callable_ = tree.price_callable(t, cf, note.call_times(), oas, note.call_prices())[0]
    return 100 * (callable_ - note.accrued()), 100 * (straight_price(note, curve, oas) - note.accrued())


def par_coupon(curve, cube, spread, maturity, first_call, freq=2, a=MEAN_REVERSION, vol_mult=1.0, callable_=True):
    """Coupon that prices a new note at 100 today (new issue): maturity in years,
    callable every coupon date from `first_call` (or not callable)."""
    times = np.arange(maturity, 0, -1 / freq)[::-1]
    calls = times[(times >= first_call - 1e-9) & (times < maturity - 1e-9)] if callable_ else []
    expiries = [c for c in calls if maturity - c >= 1]
    vols = np.array([cube_vol(cube, e, maturity - e) for e in expiries]) * vol_mult
    sigma = calibrate_sigma(curve, a, expiries, np.full(len(expiries), maturity), vols) if callable_ else 0.01
    tree = Tree(curve, a, sigma, maturity)

    def price(c):
        cf = np.full(len(times), c / freq)
        cf[-1] += 1
        return tree.price_callable(times, cf, calls, spread)[0] - 1.0
    return brentq(price, 0.0, 0.2)
