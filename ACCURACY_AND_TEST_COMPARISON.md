# Accuracy Score & Test Case Comparison: DOM vs OCR

Which tracker reads Google Meet attendance more accurately? This page gives the scores, every test case side by side, and how to reproduce them.

> **Read this first.** All results come from **mock Meet panels** rendered in headless Chromium, not from a live Google Meet call. They show how each method behaves across many layouts and edge cases. They do **not** prove the DOM tracker works on Meet's real markup today. See [Limitations](#5-limitations).

## 1. Accuracy scores (overall)

Totals over **19 test cases** and **311 participant slots**. Both methods read the identical page in each test.

| Metric | DOM tracker | OCR tracker |
|---|---|---|
| **Test cases passed** (all names, no extras, right rooms) | **19 / 19** | 2 / 19 |
| **Recall** (real names found exactly) | **100.0%** (311/311) | 53.1% (165/311) |
| **Precision** (output names that are real) | **100.0%** | 57.1% |
| **F1 score** (pooled) | **1.000** | 0.550 |
| **Room accuracy** (names put in the correct room) | **100.0%** | 39.5% |
| Spurious / garbage names produced | **0** | 124 |
| Total scan time, all cases | 15.4 s | 32.1 s |

How the scores are defined:

- **Recall** = real participants found, spelled exactly (ignoring case and extra spaces), divided by real participants.
- **Precision** = real participants found divided by everything the tracker output. Garbage, split or invented names lower it.
- **F1** = harmonic mean of precision and recall.
- **Room accuracy** = real participants reported in the correct room, divided by real participants.
- A test **passes** only if recall, precision and room accuracy are all 100%.

## 2. Test case comparison

✅ = pass, ❌ = fail. *Found* is real names found exactly out of the real total; *Extra* is names output that are not real.

| # | Test case | People | DOM result | DOM found | DOM extra | OCR result | OCR found | OCR extra | OCR right room |
|---|---|---|---|---|---|---|---|---|---|
| S01 | Baseline: 5 people, one room | 5 | ✅ | 5/5 | 0 | ✅ | 5/5 | 0 | 5/5 |
| S02 | 30 people in Main Call (list needs scrolling for OCR) | 30 | ✅ | 30/30 | 0 | ❌ | 26/30 | 11 | 26/30 |
| S03 | 4 rooms (Main + 3 breakouts), 22 people | 22 | ✅ | 22/22 | 0 | ❌ | 21/22 | 3 | 3/22 |
| S04 | 60 people across 3 rooms, scrolled list | 60 | ✅ | 60/60 | 0 | ❌ | 21/60 | 31 | 15/60 |
| S05 | Hard names: accents, Chinese, Cyrillic, emoji, apostrophes, lowercase | 10 | ✅ | 10/10 | 0 | ❌ | 1/10 | 5 | 1/10 |
| S06 | Room headings marked up as `<h2>` | 10 | ✅ | 10/10 | 0 | ❌ | 8/10 | 3 | 4/10 |
| S07 | Room headings marked up with aria-expanded | 10 | ✅ | 10/10 | 0 | ❌ | 8/10 | 3 | 4/10 |
| S08 | Rows with no aria-label (name only as visible text) | 8 | ✅ | 8/8 | 0 | ❌ | 6/8 | 3 | 6/8 |
| S09 | aria-label only on a nested element | 8 | ✅ | 8/8 | 0 | ❌ | 6/8 | 3 | 6/8 |
| S10 | Rooms with zero members between populated rooms | 6 | ✅ | 6/6 | 0 | ❌ | 4/6 | 3 | 2/6 |
| S11 | Chip layout with 'Main call' / 'Breakout N Join' headers (OCR's native style) | 18 | ✅ | 18/18 | 0 | ❌ | 0/18 | 6 | 0/18 |
| S12 | Same chip layout, 30 people | 30 | ✅ | 30/30 | 0 | ❌ | 0/30 | 13 | 0/30 |
| A01 | Names decorated with (Host)/(You) plus the tracker's own account row | 6 | ✅ | 6/6 | 0 | ❌ | 6/6 | 1 | 6/6 |
| A02 | Every row has a 'more actions' button with aria-expanded (must not be read as a room) | 6 | ✅ | 6/6 | 0 | ✅ | 6/6 | 0 | 6/6 |
| A03 | Section titles People / Breakout rooms / Contributors that are not rooms | 8 | ✅ | 8/8 | 0 | ❌ | 7/8 | 3 | 7/8 |
| A04 | Custom and non-English room names (Group A, Team Blue, Sala 1) | 12 | ✅ | 12/12 | 0 | ❌ | 11/12 | 5 | 3/12 |
| A05 | Virtualized list: only visible rows exist in the DOM, 60 people | 60 | ✅ | 60/60 | 0 | ❌ | 29/60 | 30 | 29/60 |
| A06 | One person listed twice (name differs only in case/spacing) plus one other person | 2 | ✅ | 2/2 | 0 | ❌ | 0/2 | 0 | 0/2 |
| A07 | Panel not open (nothing to read) | 0 | ✅ | 0/0 | 0 | ❌ | 0/0 | 1 | 0/0 |

Per group:

| Group | Cases | People | DOM recall | OCR recall | DOM extra | OCR extra |
|---|---|---|---|---|---|---|
| Standard (S01-S12) | 12 | 217 | 100.0% | 48.8% | 0 | 84 |
| Adversarial (A01-A07) | 7 | 94 | 100.0% | 62.8% | 0 | 40 |

## 3. What the results show

- **Hard names:** DOM found 10/10 (accents, Chinese, Cyrillic and emoji survive because text is read, not recognized). OCR found 1/10.
- **Large lists:** with 60 people OCR found 21/60 (S04) and 29/60 (A05) and output 31 and 30 bogus names. DOM found all 60 both times, including the virtualized list.
- **Markup changes:** DOM passed all four markup variants (S06-S09). OCR's accuracy moved with each, because it depends on how the panel looks, not what it contains.
- **Rooms:** DOM reads room headings generically, so custom and non-English names work (A04). OCR matches fixed "Main call" / "Breakout N" patterns.
- **Failure style:** when DOM cannot read the page it returns nothing (A07) and the tracker ignores that scan. OCR on the same empty page returned a bogus name.
- **Duplicate rows (A06):** DOM correctly collapses one person listed twice and found both people; OCR found 0 of 2. Two *different* people sharing an identical display name are not tested here and would be merged by both trackers (needs participant IDs to separate).

## 4. Offline unit tests (no browser)

`test_dom_logic.py` checks the pure logic that runs after names are read. All pass.

| Area | Tests | What is checked |
|---|---|---|
| Attendance engine (edge cases) | 11 | concurrent update and rows threadsafe, duplicate names same poll collapse to one, finalize back-dates someone who left inside the grace window, finalize idempotent and sets leave time, grace one leaves immediately, grace zero is clamped to one, large roster 100 people 20 scans, noise rows never become participants, rejoin after leave makes second session, room appearing later and empty snapshot room, self excluded case insensitively and with suffix |
| Attendance engine | 3 | glitch does not split session, join leave with backdated leave, room move and rejoin |
| Name cleaning (edge cases) | 4 | more noise, name containing noise word kept, unicode and emoji preserved, whitespace and case variants |
| Name cleaning | 3 | key case insensitive, noise rejected, suffixes and prefixes |
| CSV reports | 2 | csv schema matches ocr tool, empty rows writes nothing |
| Failed-scan safety | 2 | closed panel that cannot reopen is skipped, empty snapshot does not end sessions |
| **Total** | **25** | all passing |

## 5. Limitations

1. **Mock pages, not live Meet.** The mock follows Meet's accessibility structure (roles, aria-labels, headings) but is not Meet. DOM's 100% means its logic copes with many plausible markups. Before relying on it, run `python GMA_tracker_dom.py --dump-dom` in a real meeting.
2. **OCR is probably understated.** It was tuned on real Meet screens and the mock only approximates fonts, chips and colors. On S11/S12, a layout built to match its conventions, it still scored 0 because names came out as last-name fragments. Read the OCR column as sensitivity to layout, not its production accuracy.
3. **DOM was fixed using this benchmark.** The first run exposed a real bug (headings like "Breakout 1" were not recognized) that was then fixed, so the final DOM result is partly tuned to these cases.
4. Names are matched exactly after ignoring case and spacing. A one-letter OCR error counts as a miss.
5. Single run on one machine; timings are indicative. DOM time includes about 0.6 s of fixed scroll waits.

## 6. Reproduce

```bash
# offline unit tests
python -m unittest test_dom_logic -v

# head-to-head benchmark (needs Chromium, Tesseract, OpenCV)
pip install playwright opencv-python-headless pytesseract pandas pillow numpy psutil selenium
sudo apt-get install tesseract-ocr
python verify_dom_vs_ocr.py        # rewrites benchmark_results.json
```

Raw per-case data: [`benchmark_results.json`](benchmark_results.json). Harness: [`verify_dom_vs_ocr.py`](verify_dom_vs_ocr.py). Design: [`DOM_APPROACH_DESIGN.md`](DOM_APPROACH_DESIGN.md).
