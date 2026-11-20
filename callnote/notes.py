"""The GS 5.35% 2035 callable note (terms from the Bloomberg DES screens) and its cash flows."""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

VALUATION = date(2026, 10, 29)


@dataclass
class Note:
    name: str
    currency: str
    coupon: float          # annual rate
    freq: int              # coupons per year
    day_count: str         # "ACT/ACT" or "30/360"
    maturity: date
    call_dates: list       # issuer calls at par, only the dates still to come
    price: float = np.nan  # clean market price in % on 29/10/2026
    valuation: date = VALUATION
    coupon_dates: list = field(init=False)

    def __post_init__(self):
        # coupon dates, counted back from maturity every 12/freq months
        dates, k = [], 0
        while True:
            months = self.maturity.year * 12 + self.maturity.month - 1 - k * 12 // self.freq
            d = date(months // 12, months % 12 + 1, self.maturity.day)
            if d <= self.valuation:
                self.last_coupon = d
                break
            dates.append(d)
            k += 1
        self.coupon_dates = dates[::-1]

    def accrued(self, on=None):
        """Accrued coupon per 1 of notional on a given date (valuation date by default)."""
        on = on or self.valuation
        schedule = [self.last_coupon] + self.coupon_dates
        start = max(d for d in schedule if d <= on)
        if start == on:
            return 0.0
        if self.day_count == "30/360":
            days = 360 * (on.year - start.year) + 30 * (on.month - start.month) + min(on.day, 30) - min(start.day, 30)
            return self.coupon * days / 360
        end = min(d for d in schedule if d > on)
        return self.coupon / self.freq * (on - start).days / (end - start).days

    def cash_flows(self):
        """Payment times (years from today, ACT/365) and amounts per 1 of notional."""
        times = np.array([years(d, self.valuation) for d in self.coupon_dates])
        amounts = np.full(len(times), self.coupon / self.freq)
        amounts[-1] += 1.0
        return times, amounts

    def call_times(self):
        return np.array([years(d, self.valuation) for d in self.call_dates if d > self.valuation])

    def call_prices(self):
        """The issuer repays par plus the accrued coupon (GS calls between two coupon dates)."""
        return np.array([1.0 + self.accrued(d) for d in self.call_dates if d > self.valuation])

    @property
    def maturity_years(self):
        return years(self.maturity, self.valuation)


def years(d, valuation=VALUATION):
    return (d - valuation).days / 365.0


def quarterly(first, last):
    out, d = [], first
    while d <= last:
        out.append(d)
        m = d.month + 3
        d = date(d.year + (m - 1) // 12, (m - 1) % 12 + 1, d.day)
    return out


def load_note(folder="data_bloomberg"):
    """GS 5.35% 2035: semi-annual 30/360 coupon, callable at par every quarter from 21/04/2028 to 21/01/2035."""
    note = Note("GS 5.35% 2035", "USD", 0.0535, 2, "30/360", date(2035, 4, 21),
                quarterly(date(2028, 4, 21), date(2035, 1, 21)))
    prices = pd.read_csv(f"{folder}/notes_2026-10-29.csv").set_index("name")["price"]
    note.price = prices[note.name]
    return note
