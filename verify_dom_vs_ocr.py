"""
Head-to-head verification: DOM tracker vs OCR tracker on identical mock panels.

For every scenario a mock Google-Meet-style side panel is rendered in headless
Chromium (Playwright). The SAME page is then read by
  * DOM : the real PanelReader from GMA_tracker_dom.py (JS executed in the page)
  * OCR : the real BreakoutRoomTracker from GMA_tracker_code.py (screenshots,
          panel-edge detection, Tesseract, clean_name, merge_attendance_data)
and both are scored against the known ground truth.

IMPORTANT: this uses MOCK pages that mimic Meet's accessibility structure and
dark theme. It proves the logic, not Meet's live markup. See DOM_APPROACH_DESIGN.md.

Run:  python verify_dom_vs_ocr.py            (writes benchmark_results.json)
Needs: playwright (+ chromium), opencv-python-headless, pytesseract + tesseract,
       pandas, pillow, numpy.
"""
import io
import json
import re
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from PIL import Image
from playwright.sync_api import sync_playwright

# --- import the OCR tracker without needing undetected_chromedriver --------
for mod in ("undetected_chromedriver",):
    if mod not in sys.modules:
        try:
            __import__(mod)
        except Exception:
            sys.modules[mod] = types.SimpleNamespace(Chrome=None, ChromeOptions=object)
import GMA_tracker_code as ocr_mod  # noqa: E402
import GMA_tracker_dom as dom_mod  # noqa: E402

# ---------------------------------------------------------------------------
# Name pools
# ---------------------------------------------------------------------------
PLAIN = ["Jane Smith", "Bob Jones", "Maria Garcia", "Liam Brown", "Olivia Davis", "Noah Wilson",
         "Emma Taylor", "Lucas Moore", "Ava Clark", "Mason Lewis", "Sophia Hall", "Ethan Young",
         "Mia King", "Logan Wright", "Amelia Scott", "James Green", "Harper Adams", "Henry Baker",
         "Evelyn Nelson", "Jack Carter", "Ella Mitchell", "Owen Perez", "Grace Roberts", "Leo Turner",
         "Chloe Phillips", "Ryan Campbell", "Lily Parker", "Dylan Evans", "Zoe Edwards", "Nathan Collins"]
HARD = ["José Núñez", "Zoë Müller", "李雷", "Марина Иванова", "Sam 🌸", "O'Brien-Smith",
        "alexandria montgomery-wellington", "Dr. Priya Raghavan-Iyer", "ali", "Jean-Luc Picard"]


def make_names(n, hard=0):
    base = (PLAIN * 4)[: max(0, n - hard)]
    # make unique when pool repeats
    uniq = []
    for i, nm in enumerate(base):
        uniq.append(nm if i < len(PLAIN) else f"{nm.split()[0]} {chr(65 + i % 26)}{i}son")
    return uniq + HARD[:hard]


# ---------------------------------------------------------------------------
# Mock panel HTML. Variants emulate different ways Meet could mark rows up.
# ---------------------------------------------------------------------------
CSS = """
body{margin:0;background:#3c8c8c;font-family:Roboto,Arial,sans-serif;width:1366px;height:768px;overflow:hidden}
#tiles{position:absolute;left:0;top:0;width:960px;height:768px;background:#3c8c8c}
#panel{position:absolute;left:966px;top:0;width:400px;height:768px;background:#202124;color:#e8eaed;
 overflow-y:auto;box-sizing:border-box;padding:16px}
.hdr{font-size:15px;font-weight:600;color:#ffffff;margin:18px 0 8px;padding:6px 0;border-bottom:1px solid #3c4043}
.row{display:flex;align-items:center;height:48px}
.av{width:32px;height:32px;border-radius:50%;background:#8ab4f8;margin-right:14px;flex:none}
.nm{font-size:15px;color:#ffffff}
"""


def build_native(rooms):
    """Layout the OCR code was tuned for: 'Main call' + 'Breakout N Join' headers, name chips side by side."""
    parts, bn = [], 0
    for room, names in rooms.items():
        if canon_room(room) == "main":
            parts.append('<div class="hdr" role="heading">Main call</div>')
        else:
            bn += 1
            parts.append(f'<div class="hdr" role="heading" style="display:flex;justify-content:space-between">'
                         f'<span>Breakout {bn}</span><span style="color:#8ab4f8">Join</span></div>')
        parts.append('<div role="list" style="display:flex;flex-wrap:wrap;gap:8px">')
        for n in names:
            esc = n.replace("&", "&amp;")
            parts.append(f'<div role="listitem" aria-label="{esc}" style="display:flex;align-items:center;'
                         f'background:#3c4043;border-radius:16px;padding:4px 14px 4px 4px;height:32px">'
                         f'<div class="av" style="width:24px;height:24px;margin-right:8px"></div>'
                         f'<span class="nm">{esc}</span></div>')
        parts.append('</div>')
    return (f"<html><head><meta charset=utf-8><style>{CSS}</style></head><body><div id=tiles></div>"
            f'<div id="panel">{"".join(parts)}</div></body></html>')


def build_html(rooms, variant):
    if variant == "native":
        return build_native(rooms)
    parts = []
    for room, names in rooms.items():
        label = f"{room} ({len(names)})"
        if variant == "h2":
            parts.append(f'<h2 class="hdr">{label}</h2>')
        elif variant == "expanded":
            parts.append(f'<div class="hdr" aria-expanded="true">{label}</div>')
        else:
            parts.append(f'<div class="hdr" role="heading" aria-level="2">{label}</div>')
        for n in names:
            esc = n.replace("&", "&amp;").replace('"', "&quot;")
            if variant == "text_only":       # no aria-label, name only as visible text
                parts.append(f'<div role="listitem" class="row"><div class="av"></div><div class="nm">{esc}</div></div>')
            elif variant == "nested_aria":   # aria-label only on a nested element
                parts.append(f'<div role="listitem" class="row"><div class="av"></div><span class="nm" aria-label="{esc}">{esc}</span></div>')
            elif variant == "decorated":     # Meet-style decorated labels + extra UI text lines
                parts.append(f'<div role="listitem" class="row" aria-label="{esc}"><div class="av"></div>'
                             f'<div class="nm">{esc}</div></div>')
            else:
                parts.append(f'<div role="listitem" class="row" aria-label="{esc}"><div class="av"></div><div class="nm">{esc}</div></div>')
    return (f"<html><head><meta charset=utf-8><style>{CSS}</style></head><body><div id=tiles></div>"
            f'<div id="panel"><div role="list" aria-label="Participants">{"".join(parts)}</div></div></body></html>')


# ---------------------------------------------------------------------------
# Adapters: Selenium-like driver on top of a Playwright page
# ---------------------------------------------------------------------------
class PWDriver:
    def __init__(self, page):
        self.page = page

    def execute_script(self, js, *args):
        h = self.page.evaluate_handle(
            "([src, a]) => (new Function(src)).apply(null, a)", [js, list(args)])
        if h.as_element() is not None:
            return h.as_element()
        return h.json_value()

    def get_screenshot_as_png(self):
        return self.page.screenshot()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def key(s):
    return re.sub(r"\s+", " ", s).strip().casefold()


def canon_room(r):
    r = r.lower().strip()
    if "main" in r:
        return "main"
    m = re.search(r"breakout\s*(?:room)?\s*(\d+)", r)
    return f"breakout {m.group(1)}" if m else r


def score(truth, got):
    """Pooled name detection + room assignment. Names compared case/space-insensitively.

    detected   : truth names found anywhere in the output
    spurious   : output names that are not in truth (garbage / split / fake rooms)
    room_ok    : detected names that were also put in the correct room
    near_miss  : missed truth names for which a corrupted look-alike (ratio>=0.8) was output
    """
    import difflib
    t_room = {key(n): canon_room(r) for r, ns in truth.items() for n in ns}
    g_room = {}
    for r, ns in got.items():
        for n in ns:
            g_room.setdefault(key(n), canon_room(r))
    T, G = set(t_room), set(g_room)
    detected, missed, spurious = T & G, T - G, G - T
    room_ok = sum(1 for n in detected if g_room[n] == t_room[n])
    near = sum(1 for m in missed if any(difflib.SequenceMatcher(None, m, sp).ratio() >= 0.8 for sp in spurious))
    prec = len(detected) / len(G) if G else 1.0
    rec = len(detected) / len(T) if T else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return dict(truth=len(T), detected=len(detected), missed=len(missed), spurious=len(spurious),
                room_correct=room_ok, near_miss=near, precision=round(prec, 4),
                recall=round(rec, 4), f1=round(f1, 4),
                room_accuracy=round(room_ok / len(T), 4) if T else 1.0,
                missed_names=sorted(missed)[:6], spurious_names=sorted(spurious)[:6])


def run_dom(driver, truth):
    reader = dom_mod.PanelReader(driver)
    t = time.perf_counter()
    raw = reader.read()
    dt = time.perf_counter() - t
    got = {}
    for room, names in raw.items():
        cleaned = [dom_mod.normalize_name(n) for n in names]
        got[room] = [n for n in cleaned if n and not dom_mod.is_self(n, 'WOC')]
    return got, dt


def run_ocr(driver, page, tmpdir):
    stop = types.SimpleNamespace(is_set=lambda: False)
    ocr_mod.OUTPUT_DIR = Path(tmpdir)
    tr = ocr_mod.BreakoutRoomTracker(driver, stop)
    tr.screenshot_dir = Path(tmpdir)
    shots = []
    t = time.perf_counter()
    page.evaluate("document.getElementById('panel').scrollTop = 0")
    for i in range(80):
        shots.append(tr.take_screenshot(f"s{i}"))
        before = page.evaluate("document.getElementById('panel').scrollTop")
        page.evaluate("const p=document.getElementById('panel'); p.scrollTop += p.clientHeight*0.8")
        if page.evaluate("document.getElementById('panel').scrollTop") == before:
            break
    merged = tr.merge_attendance_data(shots)
    dt = time.perf_counter() - t
    return {room: list(people) for room, people in merged.items()}, dt, len(shots)



# ---------------------------------------------------------------------------
# Adversarial scenarios (DOM edge cases). Each returns (html, truth_rooms).
# truth excludes the tracker's own account ("WOC") exactly as the engine does.
# ---------------------------------------------------------------------------
def _page(inner, script=""):
    return (f"<html><head><meta charset=utf-8><style>{CSS}</style></head><body><div id=tiles></div>"
            f'<div id="panel">{inner}</div><script>{script}</script></body></html>')


def _row(n, label=None, extra=""):
    lab = n if label is None else label
    return (f'<div role="listitem" class="row" aria-label="{lab}"><div class="av"></div>'
            f'<div class="nm">{n}</div>{extra}</div>')


def adv_decorated():
    names = make_names(6)
    inner = ('<div role="list" aria-label="Participants"><div role="heading">Main Call</div>'
             + _row("WOC", "WOC (You)") + _row(names[0], f"{names[0]} (Host)") + "".join(_row(n) for n in names[1:]) + "</div>")
    return _page(inner), {"Main Call": names}


def adv_row_buttons():
    # every row has a "more actions" button with aria-expanded and icon text -> must NOT be read as a room heading
    names = make_names(6)
    btn = '<button aria-expanded="false" aria-label="More actions" style="margin-left:auto">more_vert</button>'
    inner = '<div role="list">' + '<div role="heading">Main Call</div>' + "".join(_row(n, extra=btn) for n in names) + "</div>"
    return _page(inner), {"Main Call": names}


def adv_section_titles():
    names = make_names(8)
    inner = ('<div role="heading">People</div><div role="heading">Breakout rooms</div><div role="list">'
             '<div role="heading">Main Call (4)</div>' + "".join(_row(n) for n in names[:4]) +
             '<div aria-expanded="true">Breakout 1 Join</div>' + "".join(_row(n) for n in names[4:]) +
             '<div role="heading">Contributors (0)</div></div>')
    return _page(inner), {"Main Call": names[:4], "Breakout 1": names[4:]}


def adv_custom_names():
    names = make_names(12)
    rooms = {"Main Call": names[:3], "Group A": names[3:6], "Team Blue": names[6:9], "Sala 1": names[9:]}
    inner = '<div role="list">' + "".join(
        f'<div role="heading">{r} ({len(ns)})</div>' + "".join(_row(n) for n in ns) for r, ns in rooms.items()) + "</div>"
    return _page(inner), rooms


def adv_virtualized():
    names = make_names(60)
    script = f"""
    const N={names!r}, H=48, panel=document.getElementById('panel'), list=document.getElementById('vl');
    list.style.height=(N.length*H)+'px'; list.style.position='relative';
    function render(){{
      const first=Math.max(0,Math.floor(panel.scrollTop/H)-2), last=Math.min(N.length,first+Math.ceil(panel.clientHeight/H)+5);
      list.querySelectorAll('[role=listitem]').forEach(e=>e.remove());
      for(let i=first;i<last;i++){{
        const d=document.createElement('div'); d.setAttribute('role','listitem'); d.setAttribute('aria-label',N[i]); d.className='row';
        d.style.cssText='position:absolute;top:'+(i*H)+'px;left:0;right:0'; d.innerHTML='<div class="av"></div><div class="nm">'+N[i]+'</div>'; list.appendChild(d);
      }}
    }}
    panel.addEventListener('scroll',render); render();
    """
    return _page('<div role="heading">Main Call</div><div id="vl" role="list"></div>', script), {"Main Call": names}


def adv_duplicates():
    return _page('<div role="list"><div role="heading">Main Call</div>' + _row("Sam Lee") + _row("sam  lee") + _row("Ann Roe") + "</div>"), \
        {"Main Call": ["Sam Lee", "Ann Roe"]}


def adv_closed_panel():
    return _page('<div>Meeting details</div>'), {}


ADV = [("A01 decorated labels + self row", adv_decorated), ("A02 per-row action buttons", adv_row_buttons),
       ("A03 non-room section titles", adv_section_titles), ("A04 custom/non-English room names", adv_custom_names),
       ("A05 virtualized list (60)", adv_virtualized), ("A06 duplicate names", adv_duplicates),
       ("A07 panel closed", adv_closed_panel)]

# ---------------------------------------------------------------------------
SCENARIOS = [
    # (id, variant, rooms spec, description)
    ("S01 small main only",        "aria",        {"Main Call": make_names(5)}, ""),
    ("S02 30 people main",         "aria",        {"Main Call": make_names(30)}, ""),
    ("S03 3 breakout rooms",       "aria",        {"Main Call": make_names(4), "Breakout Room 1": make_names(10)[4:], "Breakout Room 2": make_names(16)[10:], "Breakout Room 3": make_names(22)[16:]}, ""),
    ("S04 60 people (scrolling)",  "aria",        {"Main Call": make_names(20), "Breakout Room 1": make_names(40)[20:], "Breakout Room 2": make_names(60)[40:]}, ""),
    ("S05 hard names (accents/CJK/emoji)", "aria", {"Main Call": make_names(10, hard=10)}, ""),
    ("S06 markup: h2 headings",    "h2",          {"Main Call": make_names(5), "Breakout Room 1": make_names(10)[5:]}, ""),
    ("S07 markup: aria-expanded",  "expanded",    {"Main Call": make_names(5), "Breakout Room 1": make_names(10)[5:]}, ""),
    ("S08 markup: text-only rows", "text_only",   {"Main Call": make_names(8)}, ""),
    ("S09 markup: nested aria",    "nested_aria", {"Main Call": make_names(8)}, ""),
    ("S11 OCR-native chips layout", "native",     {"Main call": make_names(6), "Breakout 1": make_names(12)[6:], "Breakout 2": make_names(18)[12:]}, ""),
    ("S12 OCR-native, 30 people",   "native",     {"Main call": make_names(10), "Breakout 1": make_names(20)[10:], "Breakout 2": make_names(30)[20:]}, ""),
    ("S10 empty rooms",            "aria",        {"Main Call": make_names(3), "Breakout Room 1": [], "Breakout Room 2": make_names(6)[3:]}, ""),
]


def main():
    results = []
    with sync_playwright() as p:
        import os
        exe = os.environ.get('CHROMIUM_PATH') or next((str(c) for c in Path('/opt/pw-browsers').glob('chromium-*/chrome-linux*/chrome')), None)
        browser = p.chromium.launch(executable_path=exe, args=['--no-sandbox'])
        for sid, variant, rooms, _ in SCENARIOS:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.set_content(build_html(rooms, variant))
            drv = PWDriver(page)
            truth = {r: n for r, n in rooms.items()}
            total = sum(len(n) for n in truth.values())

            dom_got, dom_t = run_dom(drv, truth)
            with tempfile.TemporaryDirectory() as td:
                try:
                    ocr_got, ocr_t, nshots = run_ocr(drv, page, td)
                except Exception as e:  # report, don't hide
                    ocr_got, ocr_t, nshots = {}, 0.0, 0
                    print("OCR error in", sid, e)
            row = dict(scenario=sid, participants=total, rooms=len(truth),
                       dom=score(truth, dom_got), dom_seconds=round(dom_t, 3),
                       ocr=score(truth, ocr_got), ocr_seconds=round(ocr_t, 2), ocr_screenshots=nshots)
            results.append(row)
            print(f"{sid:40s} n={total:3d} | DOM F1={row['dom']['f1']:.2f} room={row['dom']['room_accuracy']:.2f} {dom_t:5.2f}s"
                  f" | OCR F1={row['ocr']['f1']:.2f} room={row['ocr']['room_accuracy']:.2f} {ocr_t:6.2f}s")
            page.close()
        for sid, fn in ADV:
            html, truth = fn()
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.set_content(html)
            drv = PWDriver(page)
            total = sum(len(n) for n in truth.values())
            dom_got, dom_t = run_dom(drv, truth)
            with tempfile.TemporaryDirectory() as td:
                try:
                    ocr_got, ocr_t, nshots = run_ocr(drv, page, td)
                except Exception as e:
                    ocr_got, ocr_t, nshots = {}, 0.0, 0
            row = dict(scenario=sid, participants=total, rooms=len(truth), adversarial=True,
                       dom=score(truth, dom_got), dom_seconds=round(dom_t, 3),
                       ocr=score(truth, ocr_got), ocr_seconds=round(ocr_t, 2), ocr_screenshots=nshots)
            results.append(row)
            print(f"{sid:40s} n={total:3d} | DOM F1={row['dom']['f1']:.2f} room={row['dom']['room_accuracy']:.2f} "
                  f"spur={row['dom']['spurious']} | OCR F1={row['ocr']['f1']:.2f} spur={row['ocr']['spurious']}")
            if row['dom']['missed'] or row['dom']['spurious']:
                print("    DOM missed:", row['dom']['missed_names'], "spurious:", row['dom']['spurious_names'])
            page.close()
        browser.close()
    (ROOT / "benchmark_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


if __name__ == "__main__":
    main()
