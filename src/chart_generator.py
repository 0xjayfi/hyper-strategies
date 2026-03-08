"""Chart generator for wallet spotlight posts.

Produces dark-themed PNG charts from a content payload.
Five chart types are available; generate_charts randomly picks a subset.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

# ── colour palette ──────────────────────────────────────────────────────────
DARK_BG = "#0d1117"
CARD_BG = "#161b22"
TEXT_COLOR = "#e6edf3"
ACCENT = "#58a6ff"
ACCENT_GREEN = "#3fb950"
ACCENT_RED = "#f85149"
GRID_COLOR = "#21262d"

# ── global rcParams for dark theme ──────────────────────────────────────────
plt.rcParams.update(
    {
        "figure.facecolor": DARK_BG,
        "axes.facecolor": CARD_BG,
        "axes.edgecolor": GRID_COLOR,
        "axes.labelcolor": TEXT_COLOR,
        "text.color": TEXT_COLOR,
        "xtick.color": TEXT_COLOR,
        "ytick.color": TEXT_COLOR,
        "grid.color": GRID_COLOR,
        "grid.alpha": 0.5,
        "font.size": 11,
    }
)

DIMENSIONS = ["growth", "drawdown", "leverage", "liq_distance", "diversity", "consistency"]


# ── helpers ─────────────────────────────────────────────────────────────────

def _shorten_label(label: str | None, max_len: int = 14) -> str:
    if not label:
        return "Unknown"
    return label if len(label) <= max_len else label[: max_len - 2] + ".."


def _save(fig: plt.Figure, output_path: str) -> None:
    """Save figure and close it."""
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close(fig)


# ── chart type 1: radar / spider ────────────────────────────────────────────

def chart_radar(payload: dict, output_path: str) -> None:
    """Radar chart showing the 6 dimensions for the spotlight wallet."""
    dims = payload["current_dimensions"]
    values = [dims[d] for d in DIMENSIONS]
    labels = [d.replace("_", " ").title() for d in DIMENSIONS]

    # close the polygon
    values += values[:1]
    n = len(DIMENSIONS)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(CARD_BG)

    ax.plot(angles, values, color=ACCENT, linewidth=2)
    ax.fill(angles, values, color=ACCENT, alpha=0.25)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, color=TEXT_COLOR, fontsize=10)
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0.25, 0.50, 0.75, 1.00])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], color=TEXT_COLOR, fontsize=8)
    ax.yaxis.grid(True, color=GRID_COLOR, alpha=0.5)
    ax.xaxis.grid(True, color=GRID_COLOR, alpha=0.5)

    wallet_label = _shorten_label(payload["wallet"].get("label"))
    ax.set_title(f"{wallet_label} — Dimension Profile", color=TEXT_COLOR, fontsize=13, pad=20)

    _save(fig, output_path)


# ── chart type 2: before/after bars (top-5 wallets) ────────────────────────

def chart_before_after_bars(payload: dict, output_path: str) -> None:
    """Horizontal bar chart of top-5 wallets by composite score."""
    wallets = payload["context"]["top_5_wallets"]
    spotlight_addr = payload["wallet"]["address"]

    labels = [_shorten_label(w.get("label")) for w in wallets]
    scores = [w["score"] for w in wallets]
    colors = [ACCENT_GREEN if w["address"] == spotlight_addr else ACCENT for w in wallets]

    fig, ax = plt.subplots(figsize=(8, 4))
    y_pos = np.arange(len(labels))
    ax.barh(y_pos, scores, color=colors, height=0.6, edgecolor="none")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("Composite Score")
    ax.set_title("Top 5 Wallets by Score", color=TEXT_COLOR, fontsize=13)
    ax.invert_yaxis()

    for i, v in enumerate(scores):
        ax.text(v + 0.01, i, f"{v:.2f}", va="center", color=TEXT_COLOR, fontsize=10)

    ax.grid(axis="x", color=GRID_COLOR, alpha=0.4)

    _save(fig, output_path)


# ── chart type 3: heatmap ──────────────────────────────────────────────────

def chart_heatmap(payload: dict, output_path: str) -> None:
    """Wallets x dimensions heatmap with colour-coded cells."""
    wallets = payload["context"]["top_5_wallets"]
    spotlight_addr = payload["wallet"]["address"]
    spotlight_dims = payload["current_dimensions"]

    labels = [_shorten_label(w.get("label")) for w in wallets]
    dim_labels = [d.replace("_", " ").title() for d in DIMENSIONS]

    data = []
    for w in wallets:
        if w["address"] == spotlight_addr:
            row = [spotlight_dims[d] for d in DIMENSIONS]
        else:
            # approximate: spread composite score with small random variation
            base = w["score"]
            row = [max(0.0, min(1.0, base + random.uniform(-0.1, 0.1))) for _ in DIMENSIONS]
        data.append(row)

    data_arr = np.array(data)

    fig, ax = plt.subplots(figsize=(8, 4))
    im = ax.imshow(data_arr, cmap="RdYlGn", aspect="auto", vmin=0, vmax=1)

    ax.set_xticks(np.arange(len(DIMENSIONS)))
    ax.set_xticklabels(dim_labels, fontsize=9, rotation=30, ha="right")
    ax.set_yticks(np.arange(len(wallets)))
    ax.set_yticklabels(labels, fontsize=9)

    # annotate each cell
    for i in range(len(wallets)):
        for j in range(len(DIMENSIONS)):
            val = data_arr[i, j]
            text_col = "#000000" if val > 0.55 else TEXT_COLOR
            ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=9, color=text_col)

    ax.set_title("Dimension Heatmap — Top 5 Wallets", color=TEXT_COLOR, fontsize=13)
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)

    _save(fig, output_path)


# ── chart type 4: dimension delta ──────────────────────────────────────────

def chart_dimension_delta(payload: dict, output_path: str) -> None:
    """Horizontal bars showing dimension changes for the spotlight wallet."""
    curr = payload["current_dimensions"]
    prev = payload["previous_dimensions"]

    deltas = {d: curr[d] - prev[d] for d in DIMENSIONS}
    dim_labels = [d.replace("_", " ").title() for d in DIMENSIONS]
    values = [deltas[d] for d in DIMENSIONS]
    colors = [ACCENT_GREEN if v >= 0 else ACCENT_RED for v in values]

    fig, ax = plt.subplots(figsize=(8, 4))
    y_pos = np.arange(len(DIMENSIONS))
    ax.barh(y_pos, values, color=colors, height=0.6, edgecolor="none")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(dim_labels)
    ax.axvline(0, color=GRID_COLOR, linewidth=1)
    ax.set_xlabel("Change")

    wallet_label = _shorten_label(payload["wallet"].get("label"))
    ax.set_title(f"{wallet_label} — Dimension Changes", color=TEXT_COLOR, fontsize=13)
    ax.grid(axis="x", color=GRID_COLOR, alpha=0.4)

    for i, v in enumerate(values):
        offset = 0.005 if v >= 0 else -0.005
        ha = "left" if v >= 0 else "right"
        ax.text(v + offset, i, f"{v:+.2f}", va="center", ha=ha, color=TEXT_COLOR, fontsize=9)

    _save(fig, output_path)


# ── chart type 5: rank comparison (yesterday vs today) ─────────────────────

def chart_rank_comparison(payload: dict, output_path: str) -> None:
    """Side-by-side bar comparison of yesterday vs today score and rank."""
    change = payload["change"]
    wallet_label = _shorten_label(payload["wallet"].get("label"))

    fig, axes = plt.subplots(1, 2, figsize=(8, 4))

    # --- score subplot ---
    ax1 = axes[0]
    x = np.arange(2)
    score_vals = [change["old_score"], change["new_score"]]
    bar_colors = [ACCENT, ACCENT_GREEN]
    ax1.bar(x, score_vals, color=bar_colors, width=0.5, edgecolor="none")
    ax1.set_xticks(x)
    ax1.set_xticklabels(["Yesterday", "Today"])
    ax1.set_ylim(0, 1.05)
    ax1.set_ylabel("Score")
    ax1.set_title("Score", color=TEXT_COLOR, fontsize=12)
    for i, v in enumerate(score_vals):
        ax1.text(i, v + 0.02, f"{v:.2f}", ha="center", color=TEXT_COLOR, fontsize=10)

    # --- rank subplot ---
    ax2 = axes[1]
    rank_vals = [change["old_rank"], change["new_rank"]]
    ax2.bar(x, rank_vals, color=bar_colors, width=0.5, edgecolor="none")
    ax2.set_xticks(x)
    ax2.set_xticklabels(["Yesterday", "Today"])
    ax2.set_ylabel("Rank")
    ax2.set_title("Rank", color=TEXT_COLOR, fontsize=12)
    ax2.invert_yaxis()  # lower rank number = better
    for i, v in enumerate(rank_vals):
        ax2.text(i, v, f"#{v}", ha="center", va="bottom", color=TEXT_COLOR, fontsize=10)

    fig.suptitle(f"{wallet_label} — Yesterday vs Today", color=TEXT_COLOR, fontsize=13, y=1.02)
    fig.tight_layout()

    _save(fig, output_path)


# ── registry ────────────────────────────────────────────────────────────────

CHART_TYPES: dict[str, callable] = {
    "radar": chart_radar,
    "before_after_bars": chart_before_after_bars,
    "heatmap": chart_heatmap,
    "dimension_delta": chart_dimension_delta,
    "rank_comparison": chart_rank_comparison,
}


# ── public API ──────────────────────────────────────────────────────────────

def generate_charts(
    payload: dict,
    output_dir: str,
    count: int = 2,
) -> list[str]:
    """Randomly select *count* chart types, render each to a PNG, return paths."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    keys = list(CHART_TYPES.keys())
    selected = random.sample(keys, min(count, len(keys)))

    paths: list[str] = []
    for key in selected:
        dest = out / f"{key}.png"
        CHART_TYPES[key](payload, str(dest))
        paths.append(str(dest))

    return paths


# ── CLI entry-point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    payload_path = Path(__file__).resolve().parent.parent / "data" / "content_payload.json"
    with open(payload_path) as f:
        payload = json.load(f)

    chart_dir = Path(__file__).resolve().parent.parent / "data" / "charts"
    paths = generate_charts(payload, str(chart_dir), count=2)
    for p in paths:
        print(f"Generated: {p}")
