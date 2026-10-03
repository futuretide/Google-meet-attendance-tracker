# DOM-Based Attendance Tracker — Design & Working Document

**Files:** `GMA_tracker_dom.py` (implementation) · `test_dom_logic.py` (offline tests) · this document
**Replaces (alongside):** `GMA_tracker_code.py` (OCR approach — left untouched)

---

## 1. Why change approach

| | OCR approach (`GMA_tracker_code.py`) | DOM approach (`GMA_tracker_dom.py`) |
|---|---|---|
| Data source | Screenshots → Tesseract → regex clean-up | Text/attributes read from the page |
| Name accuracy | Lossy (OCR noise, emoji, non-Latin scripts) | Exact strings Meet renders |
| Dependencies | OpenCV, Tesseract binary, Pillow, numpy | Selenium + pandas only |
| Screen dependency | Needs visible window, fixed zoom/resolution, pixel edge detection | None — works minimised / any resolution |
| Speed per scan | Seconds (screenshots + OCR per scroll position) | Well under a second per scroll position |
| Presence signal | Green/yellow dot (HSV) — code treats "name seen" as present anyway | Name in the participant list |
| Main weakness | Image quality | **Meet markup changes** (mitigated below) |

**Core trade-off:** OCR is fragile to *pixels*; DOM is fragile to *markup*. Markup breaks
loudly (empty snapshot) and is fixed by editing one JS string; OCR breaks silently
(wrong/garbled names). This design makes the markup risk small and visible.

## 2. Architecture

```
 Chrome (undetected-chromedriver, host logged in)
        │  Selenium execute_script
        ▼
 ┌──────────────┐  {room: [raw names]}  ┌──────────────────┐  sessions  ┌──────────────┐
 │ PanelReader  │ ────────────────────▶ │ AttendanceEngine │ ─────────▶ │ write_reports│
 │ (JS in page) │   normalize_name()    │ (join/leave +    │            │  → CSV files │
 └──────────────┘                       │  grace period)   │            └──────────────┘
        ▲                               └──────────────────┘
        │ scan every CHECK_INTERVAL s   (pure Python, unit-tested offline)
 MeetTracker (thread + stop_event)
```

Only `PanelReader` touches the browser. Everything downstream is pure Python, so it can
be tested without Meet.

### Components

| Component | Responsibility |
|---|---|
| `PanelReader.open_panel()` | Clicks the toolbar "People" button (falls back to "Breakout rooms") by `aria-label`/text. |
| `PanelReader.is_open()` | Detects a visible list/dialog whose `aria-label` matches participants/people/breakout. |
| `PanelReader.read()` | Finds the scrollable panel, scrolls top→bottom in 80 % steps, extracts at each step, de-duplicates → `{room: [raw names]}`. Scrolling handles virtualised lists that only render visible rows. |
| `JS_EXTRACT` | Walks panel in document order. A heading (`role=heading`, `h2/h3`, or any `aria-expanded` element) whose text matches *Main Call / Breakout Room … / Room N* switches the current room; every `role=listitem` is a participant in the current room. |
| `normalize_name()` | Strips `(You)`, `(Host)`, "Pin … to your main screen", zero-width chars; rejects UI noise (`Mute`, `Host`, digits, icons). |
| `AttendanceEngine` | Converts snapshots into sessions; see §4. |
| `write_reports()` | Same CSV schema/filenames as the OCR tool. |

## 3. Selector strategy

Meet's CSS classes are obfuscated and rotate. We never use them. We use, in order:

1. `role` attributes (`list`, `listitem`, `heading`) — accessibility contract, rarely changes
2. `aria-label` (person name; toolbar button names)
3. `aria-expanded` (collapsible room sections)
4. Visible text / document order

Name resolution per row: `data-participant-name`/`data-self-name` → row `aria-label` →
nested `[aria-label]` → first line of `innerText`.

**All Meet-specific selectors are in the `JS_*` constants in section 4 of the file.**

## 4. Attendance logic

- A snapshot is `{room: [names]}`. Self (`YOUR_NAME`) is excluded; names are keyed
  case/whitespace-insensitively.
- **Join:** name appears in a room it wasn't in → open a new session.
- **Leave:** absent for `GRACE_SCANS` (default 2) consecutive scans → close the session,
  **back-dated to the last scan the person was seen**. A one-scan glitch never splits a
  session.
- **Moving rooms:** leave from the old room + join in the new one (each room gets its own row).
- **Rejoin:** a new session row for the same person.
- **Shutdown (Ctrl+C):** open sessions are closed at the stop time, then reports are written.
- An empty snapshot (panel closed / selectors stale) is **not** fed to the engine, so a
  broken scan can't mark everyone as left.

Duration accuracy is bounded by `CHECK_INTERVAL` (± one interval).

## 5. Output

Identical to the OCR tool, in `attendance_logs/`:
`ATTENDANCE_ALL_ROOMS_<ts>.csv`, `ATTENDANCE_<Room>_<ts>.csv`, `tracker_dom_<ts>.log`
with columns `Room, Name, Join_Time, Leave_Time, Duration_Minutes, Date`.

## 6. Usage

```bash
pip install selenium undetected-chromedriver pandas setuptools
# edit YOUR_NAME / CHECK_INTERVAL at the top of GMA_tracker_dom.py
python GMA_tracker_dom.py              # run the tracker
python GMA_tracker_dom.py --dump-dom   # diagnostic: save panel HTML + parsed result
python -m unittest test_dom_logic -v   # offline tests
```

Flow: log in manually → paste meeting link → join → (create breakout rooms) → ENTER →
tracking loop → `Ctrl+C` to stop and save.

## 7. Verification status — read this

| Item | Status |
|---|---|
| Name normalisation, engine (join/leave/grace/rooms/shutdown/concurrency), CSV schema, failed-scan safety | ✅ 24 offline unit tests pass (`test_dom_logic.py`) |
| Panel extraction JS (`PanelReader` end to end) | ✅ 19 mock-panel scenarios in headless Chromium, 311/311 names and rooms correct, 0 spurious (`verify_dom_vs_ocr.py`) |
| Adversarial cases | ✅ decorated labels and self row, per-row action buttons, non-room section titles, custom/non-English room names, virtualized 60-row list, duplicate names, closed panel |
| Against **real Google Meet** | ⚠️ **Not yet verified.** No Meet session was available; mocks follow Meet's accessibility structure but are not Meet. |

Defects found and fixed by this testing:
1. Room headings were only recognised as "Breakout Room …"; "Breakout 1", "Group A" etc. were filed under Main Call. Now any heading-like element outside a participant row starts a room (non-room titles such as People/Contributors are excluded).
2. A bare leading verb was stripped from names, so "Pin Sharma" became "Sharma". Now only full Meet phrases ("Pin X to your main screen", "More actions for X") are unwrapped.

Known remaining limits: identical display names in one room collapse to one person; a room literally named like a section title (e.g. "Unassigned") is ignored as a heading; a person literally named "Host", "You" or similar is filtered as UI noise.

### First-run checklist (do this before relying on it)
1. Join a test meeting with 2–3 people and, if possible, one breakout room.
2. Run `python GMA_tracker_dom.py --dump-dom`. Check the printed "Raw read" shows the
   right names under the right rooms.
3. If rooms/names are wrong, open the saved `attendance_logs/panel_dump_*.html`, find how a
   room heading and a participant row are marked up, and adjust `JS_EXTRACT` (usually
   the `ROOM_RE` regex or the heading test) / `JS_FIND_PANEL`.
4. Run a short real scan (`CHECK_INTERVAL = 15`), have someone leave/rejoin, confirm the CSV.

## 8. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Log: "Empty snapshot (selectors may be stale)" | Panel closed or markup changed → `--dump-dom`, adjust `JS_FIND_PANEL` |
| Everyone under "Main Call" | Room headings not recognised → widen `ROOM_RE` / heading test in `JS_EXTRACT` |
| Extra junk "participants" (e.g. "Mute") | Add the text to `_NOISE_LINES` in `normalize_name` |
| People marked left then rejoined | Raise `GRACE_SCANS` |
| Panel won't auto-open | Button label differs by locale → add to `PEOPLE_LABELS` (or open manually when prompted) |
| Non-English Meet UI | Update `ROOM_RE`, `PEOPLE_LABELS`, `_NOISE_LINES` for your language |

## 9. Known limitations / next steps

- Host-only view of other breakout rooms' members depends on what Meet exposes to the host;
  the DOM can only show what the UI lists.
- Duplicate display names in one room collapse to one person (same limitation as OCR).
  If Meet exposes a stable participant ID in the DOM (e.g. `data-participant-id`) on the
  real page, key on that instead of the name — a small change in `AttendanceEngine`.
- Possible next step: a Chrome extension/MutationObserver to get event-driven join/leave
  instead of polling.
