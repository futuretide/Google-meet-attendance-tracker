"""Builds the vector PDF figures for the paper from benchmark_results.json and grace_results.json."""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

HERE = Path(__file__).parent
OUT = HERE / "figures"; OUT.mkdir(exist_ok=True)
bench = json.load(open(HERE.parent / "benchmark_results.json"))
grace = json.load(open(HERE / "grace_results.json"))

DOM, OCR = "#2a78d6", "#eb6834"          # validated categorical pair (blue / orange)
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e3e2de"
plt.rcParams.update({
    "font.family": "serif", "font.size": 7, "axes.labelsize": 7, "xtick.labelsize": 6, "ytick.labelsize": 6,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "hatch.linewidth": 0.6,
    "pdf.fonttype": 42, "ps.fonttype": 42,
})

def sid(x): return x["scenario"].split()[0]
order = sorted(bench, key=lambda x: (x["scenario"][0] != "S", int(sid(x)[1:])))
plot_order = [x for x in order if x["participants"] > 0]   # A07 (empty panel) has nothing to recall

# ---- Fig. 2: per-case recall (double column) ----------------------------------
fig, ax = plt.subplots(figsize=(7.1, 2.2))
w = 0.38
xs = list(range(len(plot_order)))
rec = lambda k, x: 100 * x[k]["detected"] / x[k]["truth"]
ax.bar([i - w / 2 for i in xs], [rec("dom", x) for x in plot_order], w, color=DOM, zorder=3)
ax.bar([i + w / 2 for i in xs], [rec("ocr", x) for x in plot_order], w, color=OCR, hatch="////", edgecolor="white", zorder=3)
for i, x in enumerate(plot_order):
    if x["ocr"]["detected"] == 0:                       # zero-height bars are invisible: label them
        ax.text(i + w / 2, 2, "0", ha="center", fontsize=6, color=INK)
ax.set_xticks(xs); ax.set_xticklabels([sid(x) for x in plot_order])
ax.set_ylabel("Names found exactly (%)"); ax.set_ylim(0, 118)
ax.yaxis.grid(True, color=GRID, lw=0.5, zorder=0); ax.set_axisbelow(True)
split = sum(1 for x in plot_order if x["scenario"][0] == "S") - 0.5
ax.axvline(split, color=MUTED, lw=0.5, ls=":")
ax.text(split / 2, 111, "standard cases (S01\u2013S12)", ha="center", fontsize=6, color=MUTED)
ax.text((split + len(xs) - 0.5) / 2, 111, "adversarial cases (A01\u2013A06)", ha="center", fontsize=6, color=MUTED)
ax.legend(handles=[Patch(color=DOM, label="DOM"), Patch(facecolor=OCR, hatch="////", edgecolor="white", label="OCR")],
          loc="upper center", ncol=2, frameon=False, fontsize=6.5, bbox_to_anchor=(0.5, 1.22))
fig.tight_layout(pad=0.3); fig.savefig(OUT / "per_case_recall.pdf"); plt.close(fig)

# ---- Fig. 3: scan time vs participants (single column) ------------------------
fig, ax = plt.subplots(figsize=(3.4, 2.1))
pts = [x for x in bench if x["participants"] > 0]
ax.scatter([x["participants"] for x in pts], [x["ocr_seconds"] for x in pts], s=14, color=OCR, marker="s", zorder=3, label="OCR")
ax.scatter([x["participants"] for x in pts], [x["dom_seconds"] for x in pts], s=14, color=DOM, marker="o", zorder=3, label="DOM")
ax.set_xlabel("Participants in panel"); ax.set_ylabel("Time per full scan (s)")
ax.yaxis.grid(True, color=GRID, lw=0.5, zorder=0); ax.set_axisbelow(True)
ax.text(52, 5.2, "OCR", color=OCR, fontsize=7, ha="right"); ax.text(52, 2.5, "DOM", color=DOM, fontsize=7, ha="right")
fig.tight_layout(pad=0.3); fig.savefig(OUT / "scan_time.pdf"); plt.close(fig)

# ---- Fig. 4: grace period vs fragmentation (single column) --------------------
fig, ax = plt.subplots(figsize=(3.4, 2.1))
shades = {1: ("#86b6ef", "^"), 2: ("#2a78d6", "o"), 3: ("#0d366b", "s")}
for g in (1, 2, 3):
    rows = [r for r in grace if r["grace_scans"] == g]
    c, m = shades[g]
    ax.plot([100 * r["miss_prob"] for r in rows], [r["fragmented_pct"] for r in rows], color=c, marker=m, ms=3.5, lw=1.2, zorder=3)
    last = rows[-1]
    ax.annotate(f"grace = {g}", (10, last["fragmented_pct"]), xytext=(-4, {1: 4, 2: 5, 3: -11}[g]), textcoords="offset points",
                ha="right", fontsize=6.5, color=INK)
ax.set_ylim(-9, 75); ax.set_yticks([0, 20, 40, 60]); ax.set_xlabel("Per-scan read-miss probability (%)"); ax.set_ylabel("Participants with split\nattendance (%)")
ax.yaxis.grid(True, color=GRID, lw=0.5, zorder=0); ax.set_axisbelow(True)
fig.tight_layout(pad=0.3); fig.savefig(OUT / "grace_fragmentation.pdf"); plt.close(fig)
print("figures written to", OUT)
