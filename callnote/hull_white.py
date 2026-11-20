"""Hull-White one-factor model: dr = (theta(t) - a r) dt + sigma dW.

- `swaption_vol`: normal vol of a swaption implied by the model (quick approximation),
  used to calibrate sigma on the market swaption vols.
- `Tree`: the classic Hull-White trinomial tree (Hull, Options Futures and Other Derivatives),
  fitted to today's discount curve, used to price the callable note by backward induction.
"""

import numpy as np
from scipy.optimize import minimize_scalar

from .curve import swap_schedule


def B(a, t, T):
    return (1 - np.exp(-a * (T - t))) / a


def swaption_vol(curve, a, sigma, expiry, end):
    """Normal vol of the forward swap rate (expiry -> end) in the Hull-White model.

    In Hull-White every zero-coupon bond at the expiry is P(T,Ti) = A_i exp(-B(T,Ti) r_T), so the swap
    rate S = (1 - P_n) / sum(d_i P_i) moves with the short rate r_T. Its normal vol is
    |dS/dr| x (std of r_T) / sqrt(expiry). Quarterly payments keep the result smooth across expiries."""
    times, accruals = swap_schedule(expiry, end, 0.25)
    P = curve.df(times) / curve.df(expiry)          # forward discount factors seen from the expiry
    Bi = B(a, expiry, times)
    annuity = np.sum(accruals * P)
    S = (1 - P[-1]) / annuity
    dS_dr = (Bi[-1] * P[-1] + S * np.sum(accruals * Bi * P)) / annuity
    std_r = sigma * np.sqrt((1 - np.exp(-2 * a * expiry)) / (2 * a))
    return dS_dr * std_r / np.sqrt(expiry)


def calibrate_sigma(curve, a, expiries, ends, market_vols):
    """Sigma that best fits the market normal vols (in decimals) of the given swaptions."""
    def error(sigma):
        model = [swaption_vol(curve, a, sigma, T, E) for T, E in zip(expiries, ends)]
        return np.sum((np.array(model) - market_vols) ** 2)
    return minimize_scalar(error, bounds=(1e-4, 0.05), method="bounded").x


class Tree:
    def __init__(self, curve, a, sigma, maturity, steps_per_year=52):
        self.n = int(np.ceil(maturity * steps_per_year))
        self.dt = dt = maturity / self.n
        self.a, self.sigma = a, sigma

        # 1) tree of x = r - alpha(t): x takes the values j * dx, j = -jmax..jmax
        self.dx = dx = sigma * np.sqrt(3 * dt)
        M = np.exp(-a * dt) - 1
        jmax = min(int(np.ceil(0.184 / -M)), self.n + 1)   # no need to be wider than the tree can reach
        j = np.arange(-jmax, jmax + 1)
        self.j, self.jmax = j, jmax

        # each node j goes to mid+1, mid, mid-1 (mid = j, except at the edges where the tree turns inwards).
        # The probabilities match the mean (j dx (1 + M)) and the variance (sigma^2 dt = dx^2 / 3) of x.
        mid = np.clip(j, -jmax + 1, jmax - 1)
        mu = j * (1 + M) - mid                     # expected move from mid, in units of dx
        pu = (1 / 3 + mu**2 + mu) / 2
        pd = (1 / 3 + mu**2 - mu) / 2
        pm = 1 - pu - pd
        self.probs = np.vstack([pu, pm, pd])
        self.mid = mid + jmax                      # as array index

        # 2) shift alpha(t) at each step so that the tree reprices today's zero-coupon bonds
        width = 2 * jmax + 1
        Q = np.zeros(width)
        Q[jmax] = 1.0                              # Arrow-Debreu prices, start at node 0
        self.alpha = np.zeros(self.n)
        for i in range(self.n):
            target = curve.df((i + 1) * dt)
            self.alpha[i] = np.log(np.sum(Q * np.exp(-j * dx * dt)) / target) / dt
            Q = self.step_forward(Q * np.exp(-(self.alpha[i] + j * dx) * dt))

    def rates(self, i):
        return self.alpha[i] + self.j * self.dx

    def step_forward(self, values):
        """Send values from each node to its three children (used for Arrow-Debreu prices and call probabilities)."""
        out = np.zeros_like(values)
        for k, shift in enumerate((1, 0, -1)):
            np.add.at(out, self.mid + shift, values * self.probs[k])
        return out

    def expectation(self, values):
        """Expected value one step later, seen from each node."""
        return (self.probs[0] * values[self.mid + 1] + self.probs[1] * values[self.mid]
                + self.probs[2] * values[self.mid - 1])

    def step(self, t):
        return int(round(t / self.dt))

    def price_callable(self, times, amounts, call_times=(), spread=0.0, call_prices=None):
        """Price of a bond paying `amounts` at `times`, callable at par by the issuer at `call_times`.

        The issuer calls when the rest of the bond is worth more than the call price (par by default):
        it can refinance cheaper. `spread` is added to the tree rate to discount (the issuer's credit spread, or OAS).
        Returns the price today and, for each call date, the nodes where the issuer calls."""
        cash = np.zeros(self.n + 1)
        np.add.at(cash, [self.step(t) for t in times], amounts)
        if call_prices is None:
            call_prices = np.ones(len(call_times))
        call_price = {self.step(t): k for t, k in zip(call_times, call_prices)}
        value = np.zeros(len(self.j))
        called = {}
        for i in range(self.n, -1, -1):
            if i < self.n:
                value = np.exp(-(self.rates(i) + spread) * self.dt) * self.expectation(value)
            if i in call_price:                    # a coupon due on the call date is paid either way
                called[i] = value > call_price[i]
                value = np.minimum(value, call_price[i])
            value = value + cash[i]
        return value[self.jmax], called

    def call_probabilities(self, called):
        """Probability (risk-neutral) that the note is called at each call date."""
        p = np.zeros(len(self.j))
        p[self.jmax] = 1.0
        out = {}
        for i in range(max(called) + 1):
            if i in called:
                out[i * self.dt] = p[called[i]].sum()
                p[called[i]] = 0.0
            p = self.step_forward(p)
        return out
