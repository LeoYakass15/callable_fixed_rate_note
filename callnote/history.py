"""Since issue: the GS note and the desk's callable swap, week by week (21/04/2026 -> 13/11/2026).

Data: weekly SOFR swaps 2Y, 5Y, 10Y (Bloomberg). The curve of each week is built from these three
rates only (flat before 2Y and after 10Y). There is no history of swaption vols, so the vol cube is
kept at its 29/10/2026 level, and the issuer's spread stays at its level at issue.
"""

from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .curve import Curve
from .desk import desk_value, swap_leg
from .hull_white import Tree
from .pricing import MEAN_REVERSION, calibrate

ISSUE = date(2026, 4, 21)
PILLARS = [2, 5, 10]


def load_weekly(folder="data_bloomberg"):
    df = pd.read_csv(f"{folder}/sofr_2y5y10y_weekly_2025-04-25_to_2026-11-13.csv", parse_dates=["date"])
    return df[df["date"].dt.date >= ISSUE].reset_index(drop=True)


def curve_of(row):
    return Curve(PILLARS, row[["USOSFR2", "USOSFR5", "USOSFR10"]].to_numpy(float) / 100)


def model_price(note, curve, cube, spread):
    """Clean price (%) of the note with the call, for a given curve and issuer spread."""
    sigma, _ = calibrate(note, curve, cube, MEAN_REVERSION)
    tree = Tree(curve, MEAN_REVERSION, sigma, note.maturity_years)
    t, cf = note.cash_flows()
    dirty, called = tree.price_callable(t, cf, note.call_times(), spread, note.call_prices())
    p_call = sum(tree.call_probabilities(called).values())
    return 100 * (dirty - note.accrued()), p_call


def run(gs, cube, folder="data_bloomberg"):
    weeks = load_weekly(folder)

    # 1) spread at issue: the spread that prices the note at 100 on the first week
    first = replace(gs, valuation=weeks["date"][0].date())
    curve0 = curve_of(weeks.iloc[0])
    spread = brentq(lambda s: model_price(first, curve0, cube, s)[0] - 100, -0.02, 0.05)

    rows = []
    for _, w in weeks.iterrows():
        note = replace(gs, valuation=w["date"].date())
        curve = curve_of(w)
        price, p_call = model_price(note, curve, cube, spread)

        # 2) desk: value of the callable swap and its DV01 on the 3 pillars (for next week's hedge)
        leg = swap_leg(note, spread)
        value = desk_value(leg, curve, cube)["swap_with_call"]
        dv01 = [desk_value(leg, curve.shifted(1, p), cube)["swap_with_call"] - value for p in PILLARS]
        rows.append({"date": w["date"], "sofr2": w["USOSFR2"], "sofr5": w["USOSFR5"], "sofr10": w["USOSFR10"],
                     "price": price, "p_call": p_call, "desk_value": value, **{f"dv01_{p}y": d for p, d in zip(PILLARS, dv01)}})
    df = pd.DataFrame(rows)

    # 3) weekly P&L: the desk alone, and with swaps that cancel last week's DV01 on each pillar
    moves_bp = df[["sofr2", "sofr5", "sofr10"]].diff() * 100
    hedge = -(df[[f"dv01_{p}y" for p in PILLARS]].shift().to_numpy() * moves_bp.to_numpy()).sum(axis=1)
    df["pnl_unhedged"] = df["desk_value"].diff().fillna(0)
    df["pnl_hedged"] = (df["pnl_unhedged"] + np.nan_to_num(hedge))
    return df, spread
