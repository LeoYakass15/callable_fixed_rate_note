"""OIS discount curve bootstrapped from par swap rates (annual fixed leg)."""

import numpy as np


class Curve:
    def __init__(self, tenors, par_rates):
        """tenors in years, par_rates in decimals. Missing years are interpolated,
        and the par rate is kept flat after the last quoted tenor."""
        self.tenors = np.asarray(tenors, float)
        self.par_rates = np.asarray(par_rates, float)
        years = np.arange(1, 31)
        par = np.interp(years, self.tenors, self.par_rates)
        dfs = []
        for s in par:  # par swap: s * sum(DF) + DF_n = 1
            dfs.append((1 - s * sum(dfs)) / (1 + s))
        self.t = np.r_[0.0, years]
        self.log_df = np.log(np.r_[1.0, dfs])

    def df(self, t):
        """Discount factor, log-linear between yearly points (flat forward rates)."""
        return np.exp(np.interp(t, self.t, self.log_df))

    def zero(self, t):
        t = np.asarray(t, float)
        return -np.log(self.df(t)) / t

    def shifted(self, bp, pillar=None):
        """New curve with the par rates moved by `bp` (all pillars, or only one)."""
        bump = np.where(self.tenors == pillar, bp, 0.0) if pillar is not None else bp
        return Curve(self.tenors, self.par_rates + np.asarray(bump) / 1e4)


def swap_schedule(start, end, step=1.0):
    """Fixed-leg payment times of a swap from `start` to `end`, every `step` years (short first period if needed)."""
    times = np.arange(end, start + 1e-9, -step)[::-1]
    times = times[times > start + 1e-9]
    return times, np.diff(np.r_[start, times])


def forward_swap(curve, start, end):
    """Forward par swap rate and annuity of a swap starting at `start`."""
    times, accruals = swap_schedule(start, end)
    annuity = np.sum(accruals * curve.df(times))
    return (curve.df(start) - curve.df(end)) / annuity, annuity
