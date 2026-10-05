"""Generates LaTeX tables and \\newcommand number macros from the benchmark JSON files.
Every number in the paper's prose/tables comes from here, so it cannot drift from the data."""
import json
from pathlib import Path

HERE = Path(__file__).parent
bench = json.load(open(HERE.parent / "benchmark_results.json"))
grace = json.load(open(HERE / "grace_results.json"))
OUT = HERE / "tables"; OUT.mkdir(exist_ok=True)

def sid(x): return x["scenario"].split()[0]
order = sorted(bench, key=lambda x: (x["scenario"][0] != "S", int(sid(x)[1:])))
T = lambda k, f: sum(x[k][f] for x in bench)
truth = T("dom", "truth")
def pr(k):
    d, s = T(k, "detected"), T(k, "spurious"); p = d / (d + s); r = d / truth
    return p, r, 2 * p * r / (p + r)
def passed(k, x):
    m = x[k]; return m["detected"] == m["truth"] and m["spurious"] == 0 and m["room_correct"] == m["truth"]

M = {}
for k in ("dom", "ocr"):
    p, r, f = pr(k)
    M[k + "Prec"] = f"{100*p:.1f}"; M[k + "Rec"] = f"{100*r:.1f}"; M[k + "Fone"] = f"{f:.3f}"
    M[k + "Found"] = str(T(k, "detected")); M[k + "Spur"] = str(T(k, "spurious"))
    M[k + "Room"] = f"{100*T(k,'room_correct')/truth:.1f}"; M[k + "RoomN"] = str(T(k, "room_correct"))
    M[k + "Pass"] = str(sum(passed(k, x) for x in bench))
    M[k + "TotalSec"] = f"{sum(x[k+'_seconds'] for x in bench):.1f}"
M["nCases"] = str(len(bench)); M["nSlots"] = str(truth)
M["nStd"] = str(sum(1 for x in bench if not x.get("adversarial"))); M["nAdv"] = str(sum(1 for x in bench if x.get("adversarial")))
big = {sid(x): x for x in bench}
for c in ("S04", "A05", "S05", "S02"):
    M[c + "OcrFound"] = str(big[c]["ocr"]["detected"]); M[c + "Truth"] = str(big[c]["ocr"]["truth"])
    M[c + "OcrSpur"] = str(big[c]["ocr"]["spurious"]); M[c + "OcrSec"] = f"{big[c]['ocr_seconds']:.1f}"; M[c + "DomSec"] = f"{big[c]['dom_seconds']:.1f}"
M["speedup"] = f"{big['S04']['ocr_seconds']/big['S04']['dom_seconds']:.1f}"
for g in (1, 2, 3):
    for r in grace:
        if r["grace_scans"] == g:
            tag = f"G{g}P{int(round(r['miss_prob']*100)):02d}"
            M[tag + "Frag"] = f"{r['fragmented_pct']:.1f}"; M[tag + "Mae"] = f"{r['duration_mae_min']:.2f}"; M[tag + "Sess"] = f"{r['sessions_per_person']:.3f}"
M["simTrials"] = str(grace[0]["trials"])
names = {k: "".join(c for c in k) for k in M}
def tex_name(k):  # LaTeX macro names must be letters only
    return k.replace("0", "Zero").replace("1", "One").replace("2", "Two").replace("3", "Three").replace("4", "Four").replace("5", "Five").replace("6", "Six").replace("7", "Seven").replace("8", "Eight").replace("9", "Nine")
(OUT / "macros.tex").write_text("".join(f"\\newcommand{{\\{tex_name(k)}}}{{{v}}}\n" for k, v in M.items()))

# ---- Table: aggregate ---------------------------------------------------------
agg = [
 ("Cases passed (all names, no extras, right rooms)", f"{M['domPass']}/{M['nCases']}", f"{M['ocrPass']}/{M['nCases']}"),
 ("Recall (\\%)", M["domRec"], M["ocrRec"]),
 ("Precision (\\%)", M["domPrec"], M["ocrPrec"]),
 ("F1 (pooled)", M["domFone"], M["ocrFone"]),
 ("Room accuracy (\\%)", M["domRoom"], M["ocrRoom"]),
 ("Spurious names output", M["domSpur"], M["ocrSpur"]),
 ("Total scan time, all cases (s)", M["domTotalSec"], M["ocrTotalSec"]),
]
t = ["\\begin{table}[t]", "\\caption{Aggregate accuracy over %s cases and %s participant slots}" % (M["nCases"], M["nSlots"]),
     "\\label{tab:aggregate}", "\\centering\\footnotesize", "\\begin{tabular}{lrr}", "\\toprule", "Metric & DOM & OCR \\\\", "\\midrule"]
t += [f"{a} & {b} & {c} \\\\" for a, b, c in agg] + ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
(OUT / "aggregate.tex").write_text("\n".join(t) + "\n")

# ---- Table: per case (double column) ------------------------------------------
DESC = {
 "S01": "Baseline, 5 people, 1 room", "S02": "30 people, Main Call", "S03": "Main + 3 breakout rooms",
 "S04": "60 people, 3 rooms, scrolled", "S05": "Accents, CJK, Cyrillic, emoji", "S06": "Headings as \\texttt{<h2>}",
 "S07": "Headings via \\texttt{aria-expanded}", "S08": "Rows without \\texttt{aria-label}", "S09": "Nested \\texttt{aria-label}",
 "S10": "Empty rooms between rooms", "S11": "OCR-native chip layout", "S12": "OCR-native chips, 30 people",
 "A01": "Decorated labels + own row", "A02": "Per-row action buttons", "A03": "Non-room section titles",
 "A04": "Custom/non-English room names", "A05": "Virtualized list, 60 people", "A06": "One person listed twice",
 "A07": "Panel not open",
}
t = ["\\begin{table*}[t]", "\\caption{Per-case results. \\emph{Found} = real names recovered exactly; \\emph{Extra} = output names that are not real; \\emph{Room} = names in the correct room. $n$ = real participants.}",
     "\\label{tab:cases}", "\\centering\\footnotesize", "\\begin{tabular}{llrcrrcrrrr}", "\\toprule",
     " & & & \\multicolumn{2}{c}{DOM} & & \\multicolumn{4}{c}{OCR} & \\\\", "\\cmidrule(lr){4-5}\\cmidrule(lr){7-10}",
     "ID & Description & $n$ & Found & Extra & & Found & Extra & Room & Time (s) \\\\", "\\midrule"]
for x in order:
    i = sid(x)
    if i == "A01": t.append("\\midrule")
    t.append(f"{i} & {DESC[i]} & {x['participants']} & {x['dom']['detected']} & {x['dom']['spurious']} & & "
             f"{x['ocr']['detected']} & {x['ocr']['spurious']} & {x['ocr']['room_correct']} & {x['ocr_seconds']:.1f} \\\\")
t += ["\\bottomrule", "\\end{tabular}", "\\end{table*}"]
(OUT / "cases.tex").write_text("\n".join(t) + "\n")

# ---- Table: grace -------------------------------------------------------------
t = ["\\begin{table}[t]", "\\caption{Grace-period simulation (%s meetings per cell, 50 participants, 19 scans). Cells: participants with split attendance (\\%%) / mean absolute duration error (min).}" % M["simTrials"],
     "\\label{tab:grace}", "\\centering\\footnotesize", "\\begin{tabular}{lccc}", "\\toprule", "Miss prob. & grace=1 & grace=2 & grace=3 \\\\", "\\midrule"]
for p in (0.0, 0.01, 0.02, 0.05, 0.10):
    cells = []
    for g in (1, 2, 3):
        r = next(r for r in grace if r["grace_scans"] == g and abs(r["miss_prob"] - p) < 1e-9)
        cells.append(f"{r['fragmented_pct']:.1f} / {r['duration_mae_min']:.2f}")
    t.append(f"{int(round(p*100))}\\% & " + " & ".join(cells) + " \\\\")
t += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
(OUT / "grace.tex").write_text("\n".join(t) + "\n")
print(json.dumps(M, indent=1))
