"""Charts saved in results/."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

INK, MUTED = "#0b0b0b", "#52514e"

plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "axes.edgecolor": MUTED,
    "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
    "grid.color": "#e6e5e0", "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
    "lines.linewidth": 2, "font.size": 10, "legend.frameon": False,
})


def save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def market(curve, cal, path):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    t = np.linspace(0.5, 30, 300)
    ax1.plot(t, 100 * curve.zero(t), color="#2a78d6", label="zero rate (continuous)")
    ax1.plot(curve.tenors, 100 * curve.par_rates, "o", color="#eb6834", ms=6, label="SOFR OIS par swaps (Bloomberg)")
    ax1.set(title="USD SOFR curve on 29/10/2026", xlabel="years", ylabel="%")
    ax1.legend()
    ax2.plot(cal["expiry"], cal["market_bp"], "o", color="#eb6834", ms=6, label="market (VCUB)")
    ax2.plot(cal["expiry"], cal["model_bp"], "-", color="#2a78d6", label="Hull-White, one sigma")
    ax2.set(title="Coterminal swaptions: call date into a swap to 2035",
            xlabel="option expiry = call date (years)", ylabel="ATM normal vol (bp)")
    ax2.legend()
    save(fig, path)


def note_value(row, probs, path):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5), gridspec_kw={"width_ratios": [1, 1.6]})
    labels = ["GS 5.35% 2035\nif not callable", "issuer's call", "callable note\n(market price)"]
    bottoms = [0, row["price"], 0]
    heights = [row["straight_at_oas"], row["call_value"], row["price"]]
    ax1.bar(labels, heights, bottom=bottoms, color=["#2a78d6", "#eb6834", "#52514e"], width=0.6)
    for x, (b, h, v) in enumerate(zip(bottoms, heights, [row["straight_at_oas"], -row["call_value"], row["price"]])):
        ax1.text(x, b + h + 0.2, f"{v:+.2f}" if x == 1 else f"{v:.2f}", ha="center", color=INK)
    ax1.set(title="GS 5.35% 2035: what the investor holds", ylabel="clean price (%)", ylim=(85, 100))
    ax1.grid(axis="x", visible=False)
    # the 4 quarterly dates of each year are added up (date by date, the tree's grid makes the numbers jumpy)
    t, p = np.array(list(probs.keys())), 100 * np.array(list(probs.values()))
    years = 2026 + 10 / 12 + t
    by_year = {y: p[np.floor(years) == y].sum() for y in np.unique(np.floor(years))}
    ax2.bar([str(int(y)) for y in by_year], list(by_year.values()), width=0.6, color="#2a78d6")
    for x, v in enumerate(by_year.values()):
        ax2.text(x, v + 0.2, f"{v:.0f}%", ha="center", color=INK)
    ax2.set(title=f"Probability that GS calls the note, by year (total {p.sum():.0f}%, risk-neutral)", ylabel="%")
    ax2.grid(axis="x", visible=False)
    save(fig, path)


def negative_convexity(profiles, path):
    fig, axes = plt.subplots(1, len(profiles), figsize=(6.5 * len(profiles), 4.5), squeeze=False)
    for ax, (name, df) in zip(axes[0], profiles.items()):
        ax.plot(df["shift_bp"], df["straight"], color="#2a78d6", label="GS 5.35% 2035 bond, not callable")
        ax.plot(df["shift_bp"], df["callable"], color="#eb6834", label="callable note")
        ax.axhline(100, color=MUTED, lw=1, ls="--")
        ax.fill_between(df["shift_bp"], df["callable"], df["straight"], color="#eb6834", alpha=0.12, lw=0)
        ax.set(title=f"{name}: price vs rates", xlabel="parallel move of the OIS curve (bp)", ylabel="clean price (%)")
        ax.legend()
    save(fig, path)


def vol_effect(vol_table, coupons, path):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    ax1.plot(vol_table["vol_shift_bp"], vol_table["call_value"], color="#2a78d6", marker="o", ms=6)
    ax1.set(title="GS 5.35% 2035: call value when swaption vols move", xlabel="shift of all normal vols (bp)",
            ylabel="points")
    ax2.plot(100 * coupons["vol_multiplier"], 100 * coupons["callable_coupon"], color="#eb6834", marker="o",
             ms=6, label="callable every quarter after 2 years")
    ax2.axhline(100 * coupons["bullet_coupon"].iloc[0], color="#2a78d6", label="same GS bond, not callable")
    ax2.set(title="New 9-year GS note at par: fair coupon", xlabel="swaption vols (% of today's level)",
            ylabel="coupon (%)")
    ax2.legend()
    save(fig, path)


def desk(hedge_table, scenarios, path):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    ax = axes[0]
    x = np.arange(len(hedge_table))
    ax.bar(x, hedge_table["dv01_bp"], color="#2a78d6", width=0.6)
    for xi, (_, r) in zip(x, hedge_table.iterrows()):
        ax.text(xi, r["dv01_bp"], f"receive\n{r['swap_notional_m']:.1f}m", ha="center", va="bottom", color=INK, fontsize=8)
    ax.set_xticks(x, [f"{p:.0f}Y" for p in hedge_table["pillar"]])
    ax.set(title="Desk DV01 by pillar and hedge swaps", ylabel="$ per bp", ylim=(0, hedge_table["dv01_bp"].max() * 1.35))
    ax.grid(axis="x", visible=False)
    labels = {"unhedged": "no hedge", "delta_hedged": "swaps (delta)", "delta_vega_hedged": "swaps + straddle (delta + vega)"}
    for ax, kind, xlabel in ((axes[1], "rates", "parallel move of SOFR swaps (bp)"),
                             (axes[2], "vols", "shift of all normal vols (bp)")):
        df = scenarios[scenarios["scenario"] == kind]
        for (col, label), color, style in zip(labels.items(), ["#52514e", "#2a78d6", "#eb6834"], ["--", "-", "-"]):
            ax.plot(df["shift_bp"], df[col] / 1e3, style, color=color, label=label, zorder=3 if style == "--" else 2)
        ax.axhline(0, color=MUTED, lw=1)
        ax.set(title=f"Desk P&L: instant {kind} move", xlabel=xlabel, ylabel="P&L ($ thousands)")
        ax.legend()
    save(fig, path)


def since_issue(df, market_price, notional, path):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    ax = axes[0]
    for col, label, color in (("sofr2", "2Y", "#2a78d6"), ("sofr5", "5Y", "#eb6834"), ("sofr10", "10Y", "#1baf7a")):
        ax.plot(df["date"], df[col], color=color, label=f"SOFR swap {label}")
    ax.set(title="SOFR swaps since the GS note was issued", ylabel="%")
    ax.legend()

    ax = axes[1]
    ax.plot(df["date"], df["price"], color="#2a78d6", label="model, spread kept at its issue level")
    ax.plot(market_price[0], market_price[1], "o", color="#eb6834", ms=8, label="Bloomberg price, 29/10/2026")
    ax.set(title="GS 5.35% 2035: price since issue", ylabel="clean price (%)")
    ax.legend(loc="lower left")

    ax = axes[2]
    ax.plot(df["date"], df["pnl_unhedged"].cumsum() * notional / 1e3, "--", color=MUTED, label="no hedge")
    ax.plot(df["date"], df["pnl_hedged"].cumsum() * notional / 1e3, color="#2a78d6", label="swaps rebalanced every week")
    ax.axhline(0, color=MUTED, lw=1)
    ax.set(title="Desk: cumulative P&L of the callable swap", ylabel="$ thousands")
    ax.legend(loc="upper left")
    for ax in axes:
        ax.tick_params(axis="x", rotation=30)
    save(fig, path)
