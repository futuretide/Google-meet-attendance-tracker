# Paper

**DOM-Based Participant Attendance Tracking for Google Meet Breakout Rooms: A Comparison with OCR-Based Screen Reading**

IEEE conference format (`IEEEtran`). Built PDF: [`main.pdf`](main.pdf).

| File | Purpose |
|---|---|
| `main.tex` | Paper source |
| `references.bib` | Bibliography (BibTeX) |
| `main.pdf` | Compiled paper (7 pages) |
| `make_tables.py` | Generates `tables/*.tex` and number macros from the result JSON files |
| `make_figures.py` | Generates `figures/*.pdf` from the result JSON files |
| `grace_simulation.py` | Seeded grace-period simulation, writes `grace_results.json` |
| `grace_results.json` | Simulation output |
| `../benchmark_results.json` | DOM vs OCR benchmark output (from `../verify_dom_vs_ocr.py`) |

All accuracy, timing and simulation numbers in the paper come from the two JSON files through
`make_tables.py` (macros) and `make_figures.py`, so they cannot drift from the data.

## Rebuild

```bash
# (optional) regenerate data
python ../verify_dom_vs_ocr.py        # needs Chromium, Tesseract, OpenCV; writes ../benchmark_results.json
python grace_simulation.py            # writes grace_results.json

# regenerate tables and figures, then compile
pip install matplotlib
python make_tables.py && python make_figures.py
latexmk -pdf main.tex                 # needs a TeX Live with IEEEtran, algorithms, pgf/tikz, booktabs
```

On Debian/Ubuntu: `apt-get install texlive-latex-base texlive-latex-recommended texlive-latex-extra texlive-publishers texlive-fonts-recommended texlive-pictures texlive-science latexmk`.

## Scope note

The evaluation uses mock Google Meet panels, not a live meeting, and the OCR implementation was tuned on real
screens, so its scores here likely understate its field accuracy. See the paper's Discussion section.
