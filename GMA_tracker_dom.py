"""
Google Meet Attendance Tracker - DOM approach
=============================================

Reads participant names and breakout-room membership straight from the Google
Meet page DOM (via Selenium + injected JavaScript) instead of screenshots + OCR.

See DOM_APPROACH_DESIGN.md for the full design, selector strategy and
troubleshooting. Run `python GMA_tracker_dom.py --dump-dom` to capture the
panel's HTML when Meet changes its markup and selectors need updating.

Layers (each one testable on its own):
    1. PanelReader       - Selenium + JS: DOM -> {room: [raw names]}   (browser only)
    2. normalize_*       - pure: raw names -> clean names              (no deps)
    3. AttendanceEngine  - pure: snapshots over time -> sessions       (no deps)
    4. ReportWriter      - pure-ish: sessions -> CSV files             (pandas)
    5. MeetTracker       - glue: browser setup, scan loop, shutdown
"""
import argparse
import logging
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

# ============================================================================
# CONFIGURATION
# ============================================================================
YOUR_NAME = "WOC"        # Your name shown in Meet (excluded from tracking)
CHECK_INTERVAL = 15      # seconds between scans (use 300 for real meetings)
GRACE_SCANS = 2          # consecutive missed scans before someone is marked "left"
MAIN_ROOM_NAME = "Main Call"
OUTPUT_DIR = Path("attendance_logs")
CHROME_VERSION = None    # e.g. 147 to pin undetected-chromedriver; None = auto

logger = logging.getLogger("meet_dom")


def setup_logging(output_dir: Path = OUTPUT_DIR) -> None:
    output_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(
                output_dir / f"tracker_dom_{datetime.now():%Y%m%d_%H%M%S}.log",
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
    )


# ============================================================================
# 1. NAME NORMALIZATION (pure)
# ============================================================================
# Meet decorates names with these; none are part of the person's name.
_SUFFIX_RE = re.compile(
    r"\s*[\(\[]\s*(you|host|presentation|co-?host|guest|external)\s*[\)\]]\s*$", re.I
)
_NOISE_LINES = {
    "", "host", "co-host", "cohost", "you", "joined", "invited", "mute", "unmute",
    "pin", "unpin", "remove", "more actions", "contributors", "in the meeting",
    "people", "breakout rooms", "main call", "join", "assigned", "not assigned",
}
# Only full Meet phrases are stripped, never bare verbs, so a person named "Pin Sharma" survives.
_WRAP_RES = (
    re.compile(r"^(?:pin|unpin)\s+(.+?)\s+(?:to|from)\s+your\s+main\s+screen$", re.I),
    re.compile(r"^more\s+actions\s+for\s+(.+)$", re.I),
    re.compile(r"^(?:mute|unmute|remove)\s+(.+?)\s+(?:from\s+the\s+(?:meeting|call)|\(microphone\))$", re.I),
)
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)


def normalize_name(raw: str) -> str:
    """Return a clean display name, or '' if `raw` is UI noise rather than a person."""
    if not raw:
        return ""
    s = raw.translate(_ZERO_WIDTH)
    s = re.sub(r"\s+", " ", s).strip()
    # aria-labels sometimes look like "Jane Smith (You)" or "Pin Jane Smith to your main screen"
    for rx in _WRAP_RES:
        m = rx.match(s)
        if m:
            s = m.group(1).strip()
            break
    while True:  # strip stacked suffixes, e.g. "Jane (Host) (You)"
        t = _SUFFIX_RE.sub("", s).strip()
        if t == s:
            break
        s = t
    if s.lower() in _NOISE_LINES:
        return ""
    if re.fullmatch(r"[\W_\d]+", s):  # pure punctuation / digits => icon text or count
        return ""
    return s


def name_key(name: str) -> str:
    """Case/whitespace-insensitive identity key (so 'jane  smith' == 'Jane Smith')."""
    return re.sub(r"\s+", " ", name).strip().casefold()


def is_self(name: str, your_name: str = YOUR_NAME) -> bool:
    return bool(your_name) and name_key(name) == name_key(your_name)


# ============================================================================
# 2. ATTENDANCE ENGINE (pure)
# ============================================================================
@dataclass
class Session:
    name: str
    join_time: datetime
    leave_time: Optional[datetime] = None


@dataclass
class RoomState:
    present: Dict[str, Session] = field(default_factory=dict)   # key -> open session
    misses: Dict[str, int] = field(default_factory=dict)        # key -> consecutive misses
    sessions: List[Session] = field(default_factory=list)


class AttendanceEngine:
    """Turns periodic snapshots {room: [names]} into join/leave sessions.

    A person is "left" only after GRACE_SCANS consecutive snapshots without them,
    which absorbs transient glitches (panel re-render, momentary reconnect).
    Leave time is back-dated to the last scan the person was actually seen.
    """

    def __init__(self, grace_scans: int = GRACE_SCANS, your_name: str = YOUR_NAME):
        self.grace = max(1, grace_scans)
        self.your_name = your_name
        self.rooms: Dict[str, RoomState] = {}
        self._last_seen: Dict[tuple, datetime] = {}
        self.lock = threading.Lock()

    def update(self, snapshot: Dict[str, List[str]], now: Optional[datetime] = None) -> None:
        now = now or datetime.now()
        with self.lock:
            for room in snapshot:
                self.rooms.setdefault(room, RoomState())
            for room, state in self.rooms.items():
                seen: Dict[str, str] = {}
                for raw in snapshot.get(room, []):
                    name = normalize_name(raw)
                    if name and not is_self(name, self.your_name):
                        seen.setdefault(name_key(name), name)

                for key, name in seen.items():
                    state.misses[key] = 0
                    self._last_seen[(room, key)] = now
                    if key not in state.present:
                        s = Session(name=name, join_time=now)
                        state.present[key] = s
                        state.sessions.append(s)
                        logger.info("[%s] + %s joined", room, name)

                for key in list(state.present):
                    if key in seen:
                        continue
                    state.misses[key] = state.misses.get(key, 0) + 1
                    if state.misses[key] >= self.grace:
                        s = state.present.pop(key)
                        s.leave_time = self._last_seen.get((room, key), now)
                        state.misses.pop(key, None)
                        mins = (s.leave_time - s.join_time).total_seconds() / 60
                        logger.info("[%s] - %s left (%.1f min)", room, s.name, mins)

    def finalize(self, now: Optional[datetime] = None) -> None:
        now = now or datetime.now()
        with self.lock:
            for room, state in self.rooms.items():
                # Someone already missing from recent scans (but still inside the grace
                # window) left before shutdown: back-date to when they were last seen.
                for key, s in state.present.items():
                    if state.misses.get(key, 0) > 0 and s.leave_time is None:
                        s.leave_time = self._last_seen.get((room, key), now)
                for s in state.sessions:
                    if s.leave_time is None:
                        s.leave_time = now
                state.present.clear()
                state.misses.clear()

    def rows(self) -> List[dict]:
        out = []
        with self.lock:
            for room, state in self.rooms.items():
                for s in state.sessions:
                    end = s.leave_time or datetime.now()
                    out.append({
                        "Room": room,
                        "Name": s.name,
                        "Join_Time": s.join_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "Leave_Time": s.leave_time.strftime("%Y-%m-%d %H:%M:%S") if s.leave_time else "",
                        "Duration_Minutes": round((end - s.join_time).total_seconds() / 60, 2),
                        "Date": s.join_time.strftime("%Y-%m-%d"),
                    })
        return out


# ============================================================================
# 3. REPORT WRITER (same CSV schema as the OCR tracker)
# ============================================================================
def write_reports(rows: List[dict], output_dir: Path = OUTPUT_DIR) -> List[Path]:
    import pandas as pd

    if not rows:
        logger.warning("No attendance data to save!")
        return []
    output_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    df = pd.DataFrame(rows)
    written = []

    combined = output_dir / f"ATTENDANCE_ALL_ROOMS_{stamp}.csv"
    df.to_csv(combined, index=False, encoding="utf-8-sig")
    written.append(combined)
    for room in df["Room"].unique():
        safe = re.sub(r"[^\w\-]+", "_", room).strip("_") or "room"
        path = output_dir / f"ATTENDANCE_{safe}_{stamp}.csv"
        df[df["Room"] == room].to_csv(path, index=False, encoding="utf-8-sig")
        written.append(path)

    logger.info("\n%s", df.to_string(index=False))
    logger.info("Participants: %d | Sessions: %d | Avg duration: %.2f min | Rooms: %d",
                df["Name"].nunique(), len(df), df["Duration_Minutes"].mean(), df["Room"].nunique())
    for p in written:
        logger.info("Saved %s", p)
    return written


# ============================================================================
# 4. PANEL READER (browser; all Meet-specific selectors live in this section)
# ============================================================================
# Meet's CSS class names are obfuscated and change often, so we deliberately
# avoid them. We rely on: aria-label / role attributes, visible text, and
# document order. If Meet changes, edit ONLY the JS strings below.

# Clicks the toolbar button whose aria-label matches. Returns true if clicked.
JS_CLICK_BY_LABEL = """
const wanted = arguments[0].map(s => s.toLowerCase());
const els = document.querySelectorAll('button, [role="button"], [role="tab"], [role="menuitem"]');
for (const el of els) {
  const label = ((el.getAttribute('aria-label') || '') + ' ' + (el.textContent || '')).toLowerCase();
  if (wanted.some(w => label.includes(w)) && el.offsetParent !== null) { el.click(); return true; }
}
return false;
"""

# True when the people / breakout panel is visible.
JS_PANEL_OPEN = """
for (const el of document.querySelectorAll('[role="list"], [role="tabpanel"], [role="complementary"], [role="dialog"]')) {
  const r = el.getBoundingClientRect();
  if (r.width > 0 && r.height > 0 && /participants|people|breakout/i.test(el.getAttribute('aria-label') || '')) return true;
}
return false;
"""

# Returns the scrollable container of the participant list (or null).
JS_FIND_PANEL = """
function panel() {
  const lists = Array.from(document.querySelectorAll('[role="list"]'))
    .filter(l => l.getBoundingClientRect().width > 0 && l.querySelector('[role="listitem"]'));
  if (!lists.length) return null;
  // The side panel is the list(s) sharing the nearest common ancestor with a visible
  // listitem; take the first visible list's closest scrollable ancestor.
  let el = lists[0];
  while (el && el !== document.body) {
    const s = getComputedStyle(el);
    if (/(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight) return el;
    el = el.parentElement;
  }
  return lists[0].parentElement;
}
return panel();
"""

# Walks the panel in document order. Anything that looks like a room heading
# switches the current room; every [role=listitem] is a participant under it.
# Returns [[room, rawName], ...].
JS_EXTRACT = """
const root = arguments[0] || document.body;
const mainName = arguments[1];
// Headings that are NOT rooms (panel titles / section labels).
const NOT_ROOM = /^(people|participants|breakout\\s*rooms|in the meeting|contributors|invited|waiting|add people|search.*|edit rooms|close rooms|unassigned)$/i;
const MAIN_RE = /^main\\s*(call|room|session)?$/i;
const out = []; let room = mainName;
function personName(item) {
  // Preference order: data attribute -> aria-label -> nested aria-label -> first visible text line.
  const d = item.getAttribute('data-participant-name') || item.getAttribute('data-self-name');
  if (d) return d;
  const a = item.getAttribute('aria-label'); if (a) return a;
  const inner = item.querySelector('[aria-label]'); if (inner && inner.getAttribute('aria-label')) return inner.getAttribute('aria-label');
  const t = (item.innerText || '').split('\\n').map(x => x.trim()).filter(Boolean);
  return t[0] || '';
}
function roomLabel(n) {
  // First visible line, minus a trailing "(N)" count and a trailing "Join" button label.
  let txt = ((n.getAttribute('aria-label') || n.innerText || '').split('\\n')[0] || '').trim();
  txt = txt.replace(/\\s*\\(\\d+\\)\\s*$/, '').replace(/\\s+join$/i, '').trim();
  return txt;
}
const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
let n = walker.currentNode;
while (n) {
  if (n.getAttribute) {
    const role = n.getAttribute('role');
    if (role === 'listitem') {
      const nm = personName(n); if (nm) out.push([room, nm]);
    } else if (!n.closest('[role="listitem"]') &&
               (role === 'heading' || n.tagName === 'H2' || n.tagName === 'H3' || n.getAttribute('aria-expanded') !== null)) {
      // Any heading-like element outside a participant row starts a new room section,
      // so custom room names ("Group A", "Breakout 1", "Room 3") work without a naming pattern.
      const txt = roomLabel(n);
      if (txt && txt.length < 60 && !NOT_ROOM.test(txt)) {
        room = MAIN_RE.test(txt) ? mainName : txt;
      }
    }
  }
  n = walker.nextNode();
}
return out;
"""

JS_PANEL_HTML = "const p = arguments[0] || document.body; return p.outerHTML;"


class PanelReader:
    """Reads {room: [raw names]} from the open People / Breakout panel."""

    PEOPLE_LABELS = ["people", "show everyone", "participants"]
    BREAKOUT_LABELS = ["breakout rooms"]

    def __init__(self, driver, main_room: str = MAIN_ROOM_NAME):
        self.driver = driver
        self.main_room = main_room

    def _run(self, js, *args):
        return self.driver.execute_script(js, *args)

    def is_open(self) -> bool:
        try:
            return bool(self._run(JS_PANEL_OPEN))
        except Exception:
            return False

    def open_panel(self) -> bool:
        """Open the People panel (breakout rooms are listed inside it for the host)."""
        if self.is_open():
            return True
        for labels in (self.PEOPLE_LABELS, self.BREAKOUT_LABELS):
            try:
                if self._run(JS_CLICK_BY_LABEL, labels):
                    time.sleep(2)
                    if self.is_open():
                        return True
            except Exception as e:
                logger.debug("open_panel error: %s", e)
        return False

    def read(self) -> Dict[str, List[str]]:
        """Scroll the panel top->bottom, merging rows (handles virtualized lists)."""
        panel = self._run(JS_FIND_PANEL)
        if panel is None:
            return {}
        merged: Dict[str, List[str]] = {}
        seen: Set[tuple] = set()

        def collect():
            for room, raw in self._run(JS_EXTRACT, panel, self.main_room) or []:
                if (room, raw) not in seen:
                    seen.add((room, raw))
                    merged.setdefault(room, []).append(raw)

        self._run("arguments[0].scrollTop = 0;", panel)
        time.sleep(0.3)
        collect()
        for _ in range(60):  # hard cap; ~60 screens of participants
            before = self._run("return arguments[0].scrollTop;", panel)
            self._run("arguments[0].scrollTop += arguments[0].clientHeight * 0.8;", panel)
            time.sleep(0.3)
            if self._run("return arguments[0].scrollTop;", panel) == before:
                break
            collect()
        self._run("arguments[0].scrollTop = 0;", panel)
        return merged

    def dump_html(self, path: Path) -> None:
        panel = self._run(JS_FIND_PANEL)
        html = self._run(JS_PANEL_HTML, panel)
        path.write_text(html, encoding="utf-8")
        logger.info("Panel HTML written to %s (%d bytes)", path, len(html))


# ============================================================================
# 5. TRACKER / MAIN
# ============================================================================
class MeetTracker:
    def __init__(self):
        self.driver = None
        self.reader: Optional[PanelReader] = None
        self.engine = AttendanceEngine()
        self.stop_event = threading.Event()

    def setup_browser(self):
        import undetected_chromedriver as uc

        options = uc.ChromeOptions()
        for a in ("--start-maximized", "--disable-notifications", "--no-first-run",
                  "--no-default-browser-check", "--disable-popup-blocking"):
            options.add_argument(a)
        kwargs = {"version_main": CHROME_VERSION} if CHROME_VERSION else {}
        try:
            self.driver = uc.Chrome(options=options, **kwargs)
        except Exception as e:
            logger.error("Could not start Chrome: %s", e)
            sys.exit(1)
        self.driver.get("https://meet.google.com/")
        input("Log in with the host Google account in the browser, then press ENTER...")

    def scan_once(self) -> bool:
        if not self.reader.is_open() and not self.reader.open_panel():
            logger.warning("People panel not open and could not be reopened")
            return False
        snapshot = self.reader.read()
        if not snapshot:
            logger.warning("Empty snapshot (selectors may be stale: run --dump-dom)")
            return False
        logger.info("Scan: %s", {r: len(n) for r, n in snapshot.items()})
        self.engine.update(snapshot)
        return True

    def track(self):
        if not self.reader.open_panel():
            input("Could not open the People panel. Open it manually, then press ENTER...")
        while not self.stop_event.is_set():
            try:
                self.scan_once()
            except Exception as e:
                logger.error("Scan error: %s", e)
            self.stop_event.wait(CHECK_INTERVAL)
        self.engine.finalize()
        write_reports(self.engine.rows())

    def run(self, dump_only: bool = False):
        self.setup_browser()
        self.driver.get(input("Paste MAIN MEETING LINK: ").strip())
        input("Join the meeting (mic/camera off), then press ENTER...")
        self.reader = PanelReader(self.driver)

        if dump_only:
            self.reader.open_panel()
            input("Arrange the panel as you want to capture it, then press ENTER...")
            OUTPUT_DIR.mkdir(exist_ok=True)
            self.reader.dump_html(OUTPUT_DIR / f"panel_dump_{datetime.now():%Y%m%d_%H%M%S}.html")
            print("Raw read:", self.reader.read())
            self.driver.quit()
            return

        input("Create/start your breakout rooms if needed, then press ENTER to begin tracking...")
        t = threading.Thread(target=self.track)
        t.start()
        try:
            while t.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping and saving attendance...")
            self.stop_event.set()
            t.join()
        finally:
            try:
                self.driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Google Meet attendance tracker (DOM approach)")
    ap.add_argument("--dump-dom", action="store_true",
                    help="capture the participant panel HTML + parsed result, then exit")
    args = ap.parse_args()
    setup_logging()
    MeetTracker().run(dump_only=args.dump_dom)
