"""Hypercare monitoring through the first closes after go-live.

Close metrics (reconciling items, manual journal entries, days to close) are
tracked on individuals and moving-range (XmR) control charts. Limits come from
the legacy system's own recent closes, so a shift after go-live stands out
from routine month-to-month variation.

Detection rules (Western Electric rules 1-3, applied to the post-go-live points):
  R1  one point beyond 3 sigma
  R2  two of three consecutive points beyond 2 sigma on the same side
  R3  four of five consecutive points beyond 1 sigma on the same side
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

D2 = 1.128  # bias constant for moving ranges of size 2


@dataclass
class Limits:
    center: float
    sigma: float

    @property
    def ucl(self) -> float:
        return self.center + 3 * self.sigma

    @property
    def lcl(self) -> float:
        return self.center - 3 * self.sigma


def xmr_limits(baseline) -> Limits:
    x = np.asarray(baseline, dtype=float)
    mr = np.abs(np.diff(x))
    return Limits(center=float(x.mean()), sigma=float(mr.mean() / D2) if len(mr) else 0.0)


def signals(points, lim: Limits) -> list[tuple[int, str]]:
    """Return (index, rule) for every point that triggers a rule."""
    z = (np.asarray(points, dtype=float) - lim.center) / (lim.sigma or 1e-9)
    out = []
    for i in range(len(z)):
        if abs(z[i]) > 3:
            out.append((i, "R1"))
            continue
        w3 = z[max(0, i - 2): i + 1]
        if len(w3) == 3 and (sum(w3 > 2) >= 2 or sum(w3 < -2) >= 2):
            out.append((i, "R2"))
            continue
        w5 = z[max(0, i - 4): i + 1]
        if len(w5) == 5 and (sum(w5 > 1) >= 4 or sum(w5 < -1) >= 4):
            out.append((i, "R3"))
    return out


def simulate_closes(rng: np.random.Generator, n_baseline: int = 12, n_post: int = 6,
                    mean: float = 40.0, sd: float = 6.0, shift_sigma: float = 0.0):
    """Manual journal entries per close: legacy closes, then post-go-live closes with a shift."""
    base = rng.normal(mean, sd, n_baseline)
    post = rng.normal(mean + shift_sigma * sd, sd, n_post)
    return base.round(0), post.round(0)


def exit_criteria_met(post_points, lim: Limits, recon_passed: list[bool], consecutive: int = 3) -> bool:
    """Hypercare ends after `consecutive` closes in control with every reconciliation passing."""
    sig = {i for i, _ in signals(post_points, lim)}
    run = 0
    for i, ok in enumerate(recon_passed):
        run = run + 1 if (ok and i not in sig) else 0
        if run >= consecutive:
            return True
    return False


def plot_control_chart(baseline, post, path, title="Manual journal entries per close",
                       ylabel="Manual journal entries"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lim = xmr_limits(baseline)
    x_all = np.concatenate([baseline, post])
    n0 = len(baseline)
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    ax.plot(range(1, n0 + 1), baseline, "o-", color="#8a8a8a", lw=1.2, ms=4, label="Legacy closes")
    ax.plot(range(n0 + 1, len(x_all) + 1), post, "o-", color="#1f5fbf", lw=1.6, ms=5,
            label="Closes after go-live")
    for y, ls in [(lim.center, "-"), (lim.ucl, "--"), (lim.lcl, "--")]:
        ax.axhline(y, color="#555555", lw=0.8, ls=ls)
    ax.set_xlim(0.5, len(x_all) + 0.5)
    ax.set_xticks(range(1, len(x_all) + 1))
    for y, lab in [(lim.ucl, "UCL"), (lim.center, "Mean"), (lim.lcl, "LCL")]:
        ax.text(len(x_all) + 0.7, y, lab, va="center", fontsize=8, clip_on=False)
    ax.axvline(n0 + 0.5, color="#1f5fbf", lw=0.8, ls=":")
    for i, rule in signals(post, lim):
        ax.annotate(rule, (n0 + 1 + i, post[i]), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=8, color="#b3261e")
    ax.set_title(title, fontsize=11, loc="left")
    ax.set_xlabel("Close number")
    ax.set_ylabel(ylabel)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return lim
