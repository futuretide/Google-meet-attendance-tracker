# Google Meet Breakout Room Attendance Tracker

Automated attendance tracking system for Google Meet — including breakout rooms — using computer vision and browser automation. No Google API required.

## What It Does

Tracks participant attendance across Google Meet main sessions and breakout rooms in real time, then exports timestamped CSV reports automatically.

- Detects participant presence using **OpenCV HSV color-space analysis** (green/yellow dot detection)
- Handles **breakout rooms** by automating the Activities panel via Selenium
- Dynamically crops screenshots at any screen resolution using pixel-level panel edge detection
- Cleans OCR noise from participant names using multi-pass regex filtering
- Exports per-room and combined CSV reports with join time, leave time, and session duration
- Handles layout shifts mid-scan (detects width changes between screenshots)
- Runs on a **multithreaded architecture** — tracking loop runs independently of the main thread

## Tech Stack

| Library | Purpose |
|---|---|
| Python | Core language |
| Selenium + undetected-chromedriver | Browser automation |
| OpenCV | Presence dot detection via HSV masking |
| Tesseract OCR + pytesseract | Participant name extraction |
| Pandas | CSV report generation |
| Pillow | Screenshot cropping and image handling |
| Threading | Concurrent tracking loop |

## Real-World Impact

Deployed for a live nonprofit organization (Women of Connections Ministry):
- Eliminated **3+ hours of manual admin work** per session
- Tracked **50+ weekly participants** across main sessions and breakout rooms
- Replaced all manual headcount with automated timestamped reporting
- Reduced administrative reporting overhead by **80%**

## Setup

### 1. Install Python dependencies
```bash
pip install opencv-python pytesseract pillow pandas undetected-chromedriver selenium
```

### 2. Install Tesseract OCR
Download and install from: https://github.com/UB-Mannheim/tesseract/wiki

### 3. Configure
Open `meet_attendance_tracker.py` and update line 51:
```python
YOUR_NAME = "YourNameInMeet"  # Your name as shown in Google Meet (excluded from tracking)
CHECK_INTERVAL = 15            # Seconds between scans (use 300 for real meetings)
```

### 4. Run
```bash
python meet_attendance_tracker.py
```

The script will:
1. Open Chrome and prompt you to log in manually
2. Ask you to paste the meeting link
3. Wait for you to join and set up breakout rooms
4. Begin tracking automatically — press `Ctrl+C` to stop and save reports

## Output

Reports are saved to the `attendance_logs/` folder:

- `ATTENDANCE_ALL_ROOMS_<timestamp>.csv` — combined report across all rooms
- `ATTENDANCE_<RoomName>_<timestamp>.csv` — per-room breakdown
- `tracker_<timestamp>.log` — full session log

**Sample CSV output:**

| Room | Name | Join_Time | Leave_Time | Duration_Minutes | Date |
|---|---|---|---|---|---|
| Breakout Room 1 | Jane Smith | 2025-03-15 10:05:00 | 2025-03-15 10:45:00 | 40.0 | 2025-03-15 |
| Main Call | John Doe | 2025-03-15 10:00:00 | 2025-03-15 11:00:00 | 60.0 | 2025-03-15 |

## How It Works

1. **Browser automation** opens the Activities → Breakout Rooms panel in Google Meet
2. **Screenshot + scroll** captures the full participant list across multiple scroll positions
3. **Dynamic panel detection** finds where the breakout panel starts using pixel color analysis (works at any resolution)
4. **OCR** extracts participant names from the cropped panel screenshots
5. **Dot detection** checks for green/yellow presence indicators using HSV masking and circularity filtering
6. **Merge logic** combines multi-scroll results, using the first screenshot as canonical room list to prevent duplicates
7. **Session tracking** logs join/leave events and calculates durations

## DOM vs OCR: detailed comparison

Two trackers ship in this repo. Both write the same CSV schema.

| | OCR (`GMA_tracker_code.py`) | DOM (`GMA_tracker_dom.py`) |
|---|---|---|
| How it reads names | Screenshot, then Tesseract OCR, then regex clean-up | Text/`aria-label` read from the page via Selenium + JS |
| Presence signal | Name seen (green/yellow dot is logged only) | Name in participant list |
| Source lines | 1,072 | 484 |
| Python packages | selenium, undetected-chromedriver, pandas, opencv, pytesseract, Pillow, numpy, psutil | selenium, undetected-chromedriver, pandas |
| System binaries | Tesseract OCR | none |
| Needs visible window / fixed layout | Yes (pixel panel-edge detection, dark theme colours) | No |
| Leave handling | Immediate on one missed scan | Leave after `GRACE_SCANS` (default 2) missed scans, back-dated to last seen |
| Failed scan (panel closed, stale selectors) | Warns; may feed bad text downstream | Empty snapshot is discarded, so nobody is marked left |
| Main failure mode | Silent: garbled, split or invented names | Loud: empty snapshot when Meet's markup changes |
| Fix when it breaks | Retune image/regex heuristics | Edit one `JS_*` string (use `--dump-dom`) |
| Verified on real Google Meet | In production use (per author) | **Not yet** (see caveats) |

> Full accuracy scores and every test case side by side: **[ACCURACY_AND_TEST_COMPARISON.md](ACCURACY_AND_TEST_COMPARISON.md)**

### Measured results (mock Meet panels, same page given to both trackers)

`verify_dom_vs_ocr.py` renders mock Meet-style side panels in headless Chromium,
then runs the **real** `PanelReader` (DOM) and the **real** `BreakoutRoomTracker`
(OCR: screenshots, panel-edge detection, Tesseract 5.3.4, `clean_name`,
`merge_attendance_data`) on each page and scores both against known ground truth.
19 scenarios, 311 participant slots (12 standard + 7 adversarial). Raw data:
[`benchmark_results.json`](benchmark_results.json).

| Metric (all 19 scenarios) | DOM | OCR |
|---|---|---|
| Names detected exactly (of 311) | **311 (100%)** | 165 (53.1%) |
| Spurious / garbage names output | **0** | 124 |
| Names placed in the correct room | **311 (100%)** | 123 (39.5%) |
| Mean F1 across scenarios | **1.000** | 0.564 |
| Time, 12 standard scenarios (sum) | **10.3 s** | 21.1 s |
| Time, 60 people with scrolling | **1.9 s** | 6.4 s (5 screenshots) |

| Scenario | People | DOM found | DOM spurious | DOM s | OCR found | OCR spurious | OCR in correct room | OCR s |
|---|---|---|---|---|---|---|---|---|
| S01 small main only | 5 | 5/5 | 0 | 0.65 | 5/5 | 0 | 5 | 0.78 |
| S02 30 people main | 30 | 30/30 | 0 | 1.27 | 26/30 | 11 | 26 | 3.61 |
| S03 3 breakout rooms | 22 | 22/22 | 0 | 0.96 | 21/22 | 3 | 3 | 2.39 |
| S04 60 people (scrolling) | 60 | 60/60 | 0 | 1.91 | 21/60 | 31 | 15 | 6.41 |
| S05 hard names (accents/CJK/emoji) | 10 | 10/10 | 0 | 0.65 | 1/10 | 5 | 1 | 1.02 |
| S06 markup: h2 headings | 10 | 10/10 | 0 | 0.65 | 8/10 | 3 | 4 | 1.04 |
| S07 markup: aria-expanded | 10 | 10/10 | 0 | 0.65 | 8/10 | 3 | 4 | 1.08 |
| S08 markup: text-only rows | 8 | 8/8 | 0 | 0.65 | 6/8 | 3 | 6 | 0.90 |
| S09 markup: nested aria | 8 | 8/8 | 0 | 0.65 | 6/8 | 3 | 6 | 0.91 |
| S11 OCR-native chips layout | 18 | 18/18 | 0 | 0.65 | 0/18 | 6 | 0 | 0.66 |
| S12 OCR-native, 30 people | 30 | 30/30 | 0 | 0.96 | 0/30 | 13 | 0 | 1.35 |
| S10 empty rooms | 6 | 6/6 | 0 | 0.64 | 4/6 | 3 | 2 | 0.92 |
| A01 decorated labels + self row | 6 | 6/6 | 0 | 0.65 | 6/6 | 1 | 6 | 0.75 |
| A02 per-row action buttons | 6 | 6/6 | 0 | 0.64 | 6/6 | 0 | 6 | 0.70 |
| A03 non-room section titles | 8 | 8/8 | 0 | 0.64 | 7/8 | 3 | 7 | 0.97 |
| A04 custom/non-English room names | 12 | 12/12 | 0 | 0.65 | 11/12 | 5 | 3 | 1.16 |
| A05 virtualized list (60) | 60 | 60/60 | 0 | 1.89 | 29/60 | 30 | 29 | 6.34 |
| A06 duplicate names | 2 | 2/2 | 0 | 0.65 | 0/2 | 0 | 0 | 0.59 |
| A07 panel closed | 0 | 0/0 | 0 | 0.01 | 0/0 | 1 | 0 | 0.55 |

What the data shows:

- **Exact names.** DOM keeps accents, CJK, emoji and mixed case. OCR found 1 of 10 in the hard-names scenario.
- **Scale.** OCR dropped to 35% on a 60-person list; DOM stayed at 100% and was about 3x faster (the DOM time includes about 0.6 s of fixed scroll waits).
- **Rooms.** DOM headings are matched generically, including custom names like "Group A" and "Sala 1". OCR relies on "Main call" / "Breakout N" text patterns.
- **Layout independence.** DOM scored 100% on every markup variant of the same panel (S06-S09); OCR ranged from 71% to 100% F1 across them.
- **Duplicates.** Neither can tell apart two people with identical display names (DOM collapses them; see limitations).

### Caveats: read before trusting these numbers

1. **Mock pages, not live Meet.** I could not run against a real meeting. The mock
   follows Meet's accessibility structure (`role`, `aria-label`, headings) but the
   real markup may differ. DOM's 100% means the extraction logic is robust across
   many plausible markups; it does **not** prove it works on Meet today. Do the
   first-run check in [`DOM_APPROACH_DESIGN.md`](DOM_APPROACH_DESIGN.md) section 7.
2. **OCR is under-represented.** The OCR code was tuned on real Meet screens.
   My mock approximates its fonts, chips and colours, so OCR's absolute numbers
   here are likely **worse** than on a real screen (S11/S12, a layout built to
   match its conventions, still scored 0 because names came out as last-name
   fragments). Treat the OCR column as evidence of fragility to layout, not as
   its true production accuracy.
3. **DOM was fixed using this benchmark.** The first run exposed a real defect
   (breakout headings like "Breakout 1" were not recognised). It was fixed and
   the scenarios re-run, so the final DOM result is partly tuned to these
   scenarios. A fresh live test is the real check.
4. Single run on one machine; timings are indicative only.

### Reproduce

```bash
python -m unittest test_dom_logic -v     # 25 offline tests
pip install playwright opencv-python-headless pytesseract pandas pillow numpy psutil selenium
sudo apt-get install tesseract-ocr       # or the Windows installer
python verify_dom_vs_ocr.py              # rewrites benchmark_results.json
```

## Research paper

An IEEE-format paper describing the DOM approach, the OCR baseline, the evaluation and its limits is in [`paper/`](paper/) ([PDF](paper/main.pdf), LaTeX source, figures and the scripts that generate every number).

## Notes

- Requires the host Google account to be logged in
- Works with Chrome (uses undetected-chromedriver to bypass bot detection)
- Tested on Windows with Chrome v147

## Author

**Harsha Sunkavalli**  
MS Computer Science, George Mason University  
[LinkedIn](https://linkedin.com/in/harsha-sunkavalli) | [Email](mailto:smasriharsha@gmail.com)
