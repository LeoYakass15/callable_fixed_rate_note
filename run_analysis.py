"""GS 5.35% 2035 callable note: Hull-White pricing, the investor's view, the desk's hedge and the note since issue.
Charts and tables go to results/."""

from datetime import datetime

import numpy as np
import pandas as pd

from callnote import desk, history, plots
from callnote.notes import load_note
from callnote.pricing import analyse, calibrate, load_market, par_coupon, price_at_oas

OUT = "results"
usd, cube = load_market()
gs = load_note()

# 1. GS note: calibration to the coterminal swaptions, OAS, call value, call probabilities
sigma, cal = calibrate(gs, usd, cube)
r = analyse(gs, usd, cube, sigma=sigma)
gs_oas = r["_oas"]
cal.round(2).to_csv(f"{OUT}/gs_calibration.csv", index=False)
pd.Series({k: v for k, v in r.items() if not k.startswith("_")}).to_csv(f"{OUT}/gs_summary.csv", header=False)
pd.DataFrame({"years": list(r["_probs"]), "p_call": list(r["_probs"].values())}).round(4).to_csv(
    f"{OUT}/gs_call_probabilities.csv", index=False)
print(f"GS 5.35% 2035 at {gs.price}: Z-spread {r['z_spread_bp']:.0f}bp, OAS {r['oas_bp']:.0f}bp, "
      f"call value {r['call_value']:.2f} pts, P(call) {100 * r['p_call']:.0f}%, expected life {r['expected_life']:.1f}y")
plots.market(usd, cal, f"{OUT}/01_market.png")
plots.note_value(r, r["_probs"], f"{OUT}/02_note_value.png")

# 2. Negative convexity: price when the whole curve moves, OAS kept fixed
shifts = np.arange(-200, 201, 25)
prices = [price_at_oas(gs, usd.shifted(s), cube, gs_oas) for s in shifts]
profile = pd.DataFrame(prices, columns=["callable", "straight"]).assign(shift_bp=shifts)
profile.round(3).to_csv(f"{OUT}/rates_profile.csv", index=False)
plots.negative_convexity({gs.name: profile}, f"{OUT}/03_negative_convexity.png")

# 3. Volatility: call value, and the fair coupon of a new 9-year GS note callable after 2 years
vol_rows = []
for v in (-40, -20, 0, 20, 40):
    callable_, straight = price_at_oas(gs, usd, cube, gs_oas, vol_shift_bp=v)
    vol_rows.append({"vol_shift_bp": v, "call_value": straight - callable_})
vol_table = pd.DataFrame(vol_rows)
vol_table.round(3).to_csv(f"{OUT}/vol_sensitivity.csv", index=False)
mults = [0.5, 0.75, 1.0, 1.25, 1.5]
coupons = pd.DataFrame({
    "vol_multiplier": mults,
    "callable_coupon": [par_coupon(usd, cube, gs_oas, 9, 2, vol_mult=m) for m in mults],
    "bullet_coupon": par_coupon(usd, cube, gs_oas, 9, 2, callable_=False),
})
coupons.round(5).to_csv(f"{OUT}/new_note_coupon.csv", index=False)
plots.vol_effect(vol_table, coupons, f"{OUT}/04_vol_effect.png")

# 4. The desk: callable swap with GS on the 15.853m note, delta and vega hedge
notional = 15.853e6
leg = desk.swap_leg(gs, gs_oas)
value = desk.desk_value(leg, usd, cube)
h = desk.hedge(leg, usd, cube)
hedge_table = pd.DataFrame(h["key_rates"])
hedge_table["dv01_bp"] = hedge_table["dv01"] * notional * 1e-4 * 1e4 / 1e4     # $ per bp
hedge_table["dv01_bp"] = hedge_table["dv01"] * notional
hedge_table["swap_notional_m"] = hedge_table["swap_notional"] * notional / 1e6
hedge_table[["pillar", "dv01_bp", "swap_notional_m"]].round(2).to_csv(f"{OUT}/desk_hedge.csv", index=False)

scen = []
for s in range(-100, 101, 10):
    scen.append({"scenario": "rates", "shift_bp": s, **desk.scenario_pnl(leg, usd, cube, h, s, 0)})
for v in range(-30, 31, 5):
    scen.append({"scenario": "vols", "shift_bp": v, **desk.scenario_pnl(leg, usd, cube, h, 0, v)})
scenarios = pd.DataFrame(scen)
for col in ("unhedged", "delta_hedged", "delta_vega_hedged"):
    scenarios[col] *= notional
scenarios.round(0).to_csv(f"{OUT}/desk_scenarios.csv", index=False)
plots.desk(hedge_table, scenarios, f"{OUT}/05_desk_hedge.png")

s = h["straddle"]
print(f"\nDesk (GS note, {notional / 1e6:.3f}m): Bermudan receiver swaption worth {100 * value['bermudan']:.2f} pts "
      f"(${value['bermudan'] * notional / 1e3:.0f}k)")
print(f"DV01 ${hedge_table['dv01_bp'].sum():.0f} per bp, vega ${h['vega'] * notional:.0f} per bp of vol")
print(f"Vega hedge: sell {-s['notional'] * notional / 1e6:.1f}m of ATM {s['expiry']:.1f}y x {s['end'] - s['expiry']:.1f}y "
      f"straddles (strike {100 * s['strike']:.2f}%)")

# 5. Since issue (21/04/2026): the GS note and the desk week by week, on the weekly SOFR swaps
weekly, issue_spread = history.run(gs, cube)
weekly.assign(date=weekly["date"].dt.date).round(5).to_csv(f"{OUT}/since_issue.csv", index=False)
plots.since_issue(weekly, (datetime(2026, 10, 29), gs.price), notional, f"{OUT}/06_since_issue.png")
pnl = weekly[["pnl_unhedged", "pnl_hedged"]] * notional
print(f"\nSince issue: GS spread at issue {issue_spread * 1e4:.0f}bp (vs OAS {gs_oas * 1e4:.0f}bp on 29/10)")
print(f"Desk P&L: no hedge ${pnl['pnl_unhedged'].sum() / 1e3:.0f}k (weekly std ${pnl['pnl_unhedged'].std() / 1e3:.0f}k), "
      f"hedged ${pnl['pnl_hedged'].sum() / 1e3:.0f}k (weekly std ${pnl['pnl_hedged'].std() / 1e3:.1f}k)")
