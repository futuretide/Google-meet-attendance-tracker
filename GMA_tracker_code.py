import sys
import subprocess
import os

def ensure_dependencies():
    packages = [
        "undetected-chromedriver", "selenium", "pandas",
        "opencv-python", "pytesseract", "Pillow", "psutil", "setuptools"
    ]
    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By
        import pandas as pd
        import cv2
        import pytesseract
        from PIL import Image
        import psutil
    except ImportError as e:
        print(f"Missing dependency detected: {e}")
        print("Installing required packages. This may take a minute...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + packages)
            print("Installation complete! Please restart the script now.")
            sys.exit(0)
        except Exception as install_err:
            print(f"Failed to install packages automatically: {install_err}")
            print(f"Please install manually: pip install {' '.join(packages)}")
            sys.exit(1)

ensure_dependencies()

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import pandas as pd
import time
import threading
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Set
import cv2
import numpy as np
from PIL import Image
import io

# ============================================================================
# CONFIGURATION
# ============================================================================
YOUR_NAME = "WOC"       # Your name shown in Meet (to exclude from tracking)
CHECK_INTERVAL = 15     # seconds between scans (set to 300 for real meetings)
OUTPUT_DIR = Path("attendance_logs")

OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(OUTPUT_DIR / f"tracker_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# PRESENCE DOT DETECTION
# ============================================================================
def has_green_dot(image_path: str) -> bool:
    """Detect green OR yellow/orange dot (both mean participant is present)"""
    try:
        img = cv2.imread(image_path)
        if img is None:
            return False

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # Green dot (active/unmuted)
        mask_green = cv2.inRange(hsv, np.array([40, 100, 100]), np.array([85, 255, 255]))
        # Yellow/orange dot (muted but present)
        mask_yellow = cv2.inRange(hsv, np.array([15, 100, 100]), np.array([40, 255, 255]))

        mask = cv2.bitwise_or(mask_green, mask_yellow)

        if cv2.countNonZero(mask) < 5:
            return False

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if 5 < area < 300:
                perimeter = cv2.arcLength(cnt, True)
                if perimeter > 0:
                    circularity = 4 * np.pi * area / (perimeter * perimeter)
                    if circularity > 0.4:
                        return True
        return False
    except Exception as e:
        logger.error(f"Dot detection error: {e}")
        return False


# ============================================================================
# BREAKOUT ROOM TRACKER
# ============================================================================
class BreakoutRoomTracker:
    def __init__(self, driver, stop_event: threading.Event):
        self.driver = driver
        self.stop_event = stop_event
        self.screenshot_dir = OUTPUT_DIR / "breakout_screenshots"
        self.screenshot_dir.mkdir(exist_ok=True)
        self.rooms: Dict[str, Dict] = {}
        self.lock = threading.Lock()

    def open_breakout_rooms_panel(self):
        try:
            logger.info("Opening Activities -> Breakout Rooms...")
            clicked = self.driver.execute_script("""
                const buttons = Array.from(document.querySelectorAll('button, div[role="button"]'));
                for (let btn of buttons) {
                    const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                    const text = (btn.textContent || '').toLowerCase();
                    if (label.includes('activities') || label.includes('meeting') ||
                        text.includes('activities') || label.includes('more options')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            """)
            if not clicked:
                logger.warning("Could not find Activities button")
            time.sleep(2)

            clicked = self.driver.execute_script("""
                const items = Array.from(document.querySelectorAll('div, span, button, li'));
                for (let item of items) {
                    const text = (item.textContent || '').toLowerCase();
                    if (text.includes('breakout') && text.includes('room')) {
                        item.click();
                        return true;
                    }
                }
                return false;
            """)
            if clicked:
                time.sleep(3)
                logger.info("Breakout Rooms panel opened")
                return True
            else:
                logger.warning("Could not find Breakout Rooms option")
                return False
        except Exception as e:
            logger.error(f"Failed to open breakout rooms panel: {e}")
            return False

    def scroll_and_capture_panel(self) -> List[str]:
        screenshots = []
        try:
            scroll_script = """
                let scrollContainer = null;
                const dialogs = document.querySelectorAll('[role="dialog"], [role="complementary"]');
                for (let panel of dialogs) {
                    const text = (panel.textContent || '').toLowerCase();
                    if (text.includes('breakout') || text.includes('main call')) {
                        scrollContainer = panel;
                        break;
                    }
                }
                if (!scrollContainer) {
                    const allElements = document.querySelectorAll('*');
                    for (let el of allElements) {
                        const style = window.getComputedStyle(el);
                        const hasScroll = el.scrollHeight > el.clientHeight + 10;
                        const isScrollable = style.overflowY === 'auto' || style.overflowY === 'scroll';
                        if (hasScroll && isScrollable && el.clientHeight > 200) {
                            const text = (el.textContent || '').toLowerCase();
                            if (text.includes('breakout') || text.includes('room') || text.includes('main')) {
                                scrollContainer = el;
                                break;
                            }
                        }
                    }
                }
                if (!scrollContainer) {
                    const allElements = document.querySelectorAll('*');
                    for (let el of allElements) {
                        const rect = el.getBoundingClientRect();
                        const hasScroll = el.scrollHeight > el.clientHeight + 10;
                        if (hasScroll && rect.right > window.innerWidth * 0.6 && rect.height > 300) {
                            scrollContainer = el;
                            break;
                        }
                    }
                }
                return scrollContainer ? true : false;
            """
            has_scroll = self.driver.execute_script(scroll_script)

            if not has_scroll:
                logger.warning("Could not find scrollable breakout panel - taking single screenshot")
                screenshots.append(self.take_screenshot("position_0"))
                return screenshots
            else:
                logger.info("Found scrollable panel")

            self.driver.execute_script("""
                let scrollContainer = null;
                const dialogs = document.querySelectorAll('[role="dialog"], [role="complementary"]');
                for (let panel of dialogs) {
                    if ((panel.textContent || '').toLowerCase().includes('breakout')) {
                        scrollContainer = panel; break;
                    }
                }
                if (!scrollContainer) {
                    const allElements = document.querySelectorAll('*');
                    for (let el of allElements) {
                        const hasScroll = el.scrollHeight > el.clientHeight + 10;
                        const rect = el.getBoundingClientRect();
                        if (hasScroll && rect.right > window.innerWidth * 0.6) {
                            scrollContainer = el; break;
                        }
                    }
                }
                if (scrollContainer) scrollContainer.scrollTop = 0;
            """)
            time.sleep(1)
            screenshots.append(self.take_screenshot("position_0"))

            for i in range(10):
                scrolled = self.driver.execute_script("""
                    let scrollContainer = null;
                    const dialogs = document.querySelectorAll('[role="dialog"], [role="complementary"]');
                    for (let panel of dialogs) {
                        if ((panel.textContent || '').toLowerCase().includes('breakout')) {
                            scrollContainer = panel; break;
                        }
                    }
                    if (!scrollContainer) {
                        const allElements = document.querySelectorAll('*');
                        for (let el of allElements) {
                            const hasScroll = el.scrollHeight > el.clientHeight + 10;
                            const rect = el.getBoundingClientRect();
                            if (hasScroll && rect.right > window.innerWidth * 0.6) {
                                scrollContainer = el; break;
                            }
                        }
                    }
                    if (scrollContainer) {
                        const before = scrollContainer.scrollTop;
                        scrollContainer.scrollTop += 300;
                        return scrollContainer.scrollTop > before;
                    }
                    return false;
                """)
                if not scrolled:
                    logger.info(f"Reached end of scroll after {i + 1} positions")
                    break
                time.sleep(0.5)
                screenshots.append(self.take_screenshot(f"position_{i + 1}"))

            logger.info(f"Captured {len(screenshots)} screenshots while scrolling")
        except Exception as e:
            logger.error(f"Error during scrolling: {e}")
        return screenshots

    def detect_panel_left_edge(self, img: Image.Image) -> int:
        """
        Dynamically detect where the breakout panel starts on the x-axis.
        Works at any resolution and any video tile color (brown, teal, green, etc).

        Strategy: scan RIGHT-TO-LEFT skipping the scrollbar (~55px), find the
        leftmost column of consistent dark panel background (RGB ~30,31,33).
        Allow up to 30px of non-dark tolerance so chip/card borders don't
        stop the scan prematurely.
        Gives ~100px safety margin before the first text at all tested resolutions.
        Falls back to w//2 if no dark panel is found.
        """
        arr = np.array(img)
        h, w = arr.shape[:2]
        scan_y1 = min(100, h // 8)
        scan_y2 = min(700, int(h * 0.8))

        last_dark_x = w // 2
        in_panel = False
        non_dark_streak = 0

        for x in range(w - 55, w // 3, -1):
            col = arr[scan_y1:scan_y2, x, :3].astype(float)
            avg_r = col[:, 0].mean()
            avg_g = col[:, 1].mean()
            avg_b = col[:, 2].mean()
            is_dark_panel = avg_r < 55 and avg_g < 55 and avg_b < 55 and abs(avg_r - avg_g) < 12

            if is_dark_panel:
                in_panel = True
                last_dark_x = x
                non_dark_streak = 0
            elif in_panel:
                non_dark_streak += 1
                if non_dark_streak > 30:  # left the panel region
                    break

        # 50px safety margin so no panel text is ever clipped
        return max(0, last_dark_x - 50)

    def take_screenshot(self, suffix: str = "") -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.screenshot_dir / f"breakout_{timestamp}_{suffix}.png"
        screenshot = self.driver.get_screenshot_as_png()
        img = Image.open(io.BytesIO(screenshot))
        width, height = img.size
        # Dynamically detect the panel left edge instead of using a hardcoded fraction.
        # The fraction changes with screen resolution (e.g. 0.36 at 768px, 0.59 at 1248px).
        # detect_panel_left_edge() scans actual pixel colors to find where the video tile
        # ends and the dark panel begins, working correctly at any resolution.
        crop_x = self.detect_panel_left_edge(img)
        cropped = img.crop((crop_x, 0, width, height))
        cropped.save(filename)
        return str(filename)

    def clean_name(self, name: str) -> str:
        """Clean OCR noise from participant names"""
        import re
        # Remove leading non-alphanumeric characters (brackets, symbols etc)
        name = re.sub(r"^[^a-zA-Z0-9]+", "", name).strip()
        # Replace common OCR misreads
        name = name.replace("@", "_").replace("|", "_")
        # Remove trailing garbage (brackets, special chars)
        name = re.sub(r"[^a-zA-Z0-9_\s\-\.\']+$", "", name).strip()
        # Collapse multiple spaces
        name = re.sub(r"\s+", " ", name).strip()

        # Strip leading avatar OCR noise tokens:
        # Avatar circles get OCR'd as short 1-2 char tokens before the real name.
        # e.g. "Po fe) Pavan" -> "Pavan", "Po Pavan" -> "Pavan", "S86 Sri" -> "Sri..."
        # Strategy: if first word(s) are short/noisy and rest looks like a real name, drop them
        words = name.split()
        while len(words) > 1:
            first = words[0]
            # Drop token if it's 1-2 chars, contains non-alpha chars, or is all digits
            is_noise = (
                len(first) <= 2 or           # single letters like "S", "Po" etc
                not first.isalpha() or        # contains symbols like "fe)"
                re.search(r'\d', first)       # contains digits like "S86"
            )
            if is_noise:
                words = words[1:]
            else:
                break
        name = " ".join(words).strip()

        # Strip TRAILING avatar OCR noise tokens (same logic as leading).
        # After PILL_GAP splitting, a group can end with the next chip's avatar token
        # e.g. "Pavan Pe" -> "Pavan", "Sri Harsha So" -> "Sri Harsha".
        words = name.split()
        while len(words) > 1:
            last = words[-1]
            is_noise = (
                len(last) <= 2 or
                not last.isalpha() or
                re.search(r'\d', last)
            )
            if is_noise:
                words = words[:-1]
            else:
                break
        name = " ".join(words).strip()

        # Remove consecutive duplicate words caused by multi-pass OCR merging the
        # same word from two slightly different pixel positions into one name string.
        # e.g. "Sri Harsha Harsha Sunkavalli" -> "Sri Harsha Sunkavalli"
        words = name.split()
        deduped = []
        for w in words:
            if not deduped or w.lower() != deduped[-1].lower():
                deduped.append(w)
        name = " ".join(deduped).strip()

        return name

    def extract_room_attendance(self, image_path: str) -> Dict[str, Dict[str, bool]]:
        """
        Two-pass OCR approach:
        Pass 1: Find room headers by Y position
        Pass 2: Assign participants to nearest room above them
        """
        try:
            import pytesseract
            import re
            import os

            # Find Tesseract
            tesseract_cmd = shutil.which('tesseract')
            possible_paths = [
                tesseract_cmd,
                r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
                r'C:\Tesseract-OCR\tesseract.exe',
                os.path.join(os.getenv('LOCALAPPDATA', ''), r'Tesseract-OCR\tesseract.exe'),
            ]
            possible_paths = list(dict.fromkeys([p for p in possible_paths if p]))
            tesseract_found = False
            for path in possible_paths:
                if os.path.exists(path):
                    pytesseract.pytesseract.tesseract_cmd = path
                    tesseract_found = True
                    break
            if not tesseract_found:
                logger.error("Tesseract not found!")
                return {}

            orig_img = cv2.imread(image_path)
            if orig_img is None:
                logger.error(f"Could not read image: {image_path}")
                return {}

            img = orig_img  # keep original for dot detection

            # 2x scale for OCR
            ocr_img = cv2.resize(orig_img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(ocr_img, cv2.COLOR_BGR2GRAY)

            # Google Meet uses dark UI with WHITE text inside pill/chip widgets.
            # Standard preprocessing darkens the background further, hiding white text.
            # Fix: run OCR on THREE versions and merge all results:
            #   1. Normal gray (catches light-on-dark text areas like room headers)
            #   2. Inverted (white text on dark background becomes black on white → readable)
            #   3. CLAHE-enhanced (improves low-contrast areas)
            gray_normal   = cv2.convertScaleAbs(gray, alpha=1.3, beta=10)
            gray_inverted = cv2.bitwise_not(gray)  # KEY FIX: inverts dark bg / white text
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray_clahe = clahe.apply(gray)

            config = "--oem 3 --psm 6"
            all_data_versions = []
            for version_img in [gray_normal, gray_inverted, gray_clahe]:
                d = pytesseract.image_to_data(version_img, output_type=pytesseract.Output.DICT, config=config)
                all_data_versions.append(d)

            # Merge all OCR results into one unified word list
            # Use a dict keyed by (x_bucket, y_bucket) to deduplicate overlapping reads
            merged_words = {}  # (x_bucket, y_bucket) -> (x, y, text, conf, orig_index)
            global_idx = 0
            for d in all_data_versions:
                for i in range(len(d['text'])):
                    text = d['text'][i].strip()
                    conf = int(d['conf'][i])
                    if conf < 20 or len(text) < 2:
                        continue
                    x = d['left'][i]
                    y = d['top'][i]
                    w = d['width'][i]
                    h = d['height'][i]
                    # bucket by position to deduplicate
                    xb = (x // 30) * 30
                    yb = (y // 20) * 20
                    key = (xb, yb)
                    if key not in merged_words or conf > merged_words[key][3]:
                        merged_words[key] = (x, y, text, conf, w, h, global_idx)
                    global_idx += 1

            # Rebuild data dict from merged words for downstream processing
            data = {'text': [], 'conf': [], 'left': [], 'top': [], 'width': [], 'height': []}
            for (x, y, text, conf, w, h, idx) in merged_words.values():
                data['text'].append(text)
                data['conf'].append(conf)
                data['left'].append(x)
                data['top'].append(y)
                data['width'].append(w)
                data['height'].append(h)

            UI_SKIP = {
                "you", "host", "chat", "mute", "pin", "more", "options", "more_vert",
                "edit", "close", "breakout", "rooms", "join", "activities",
                "participants", "now", "people", "x",
                "microphone", "camera", "leave", "open", "shuffle", "add",
                "editrooms", "closerooms", "editroom", "closeroom"
            }
            # Note: "call" and "present" removed from UI_SKIP — they can appear in names

            # Group words into lines by Y bucket (20px tolerance)
            lines = {}
            n_boxes = len(data['text'])
            for i in range(n_boxes):
                text = data['text'][i].strip()
                conf = int(data['conf'][i])
                if conf < 20 or len(text) < 2:
                    continue
                y = data['top'][i]
                x = data['left'][i]
                y_bucket = (y // 20) * 20
                if y_bucket not in lines:
                    lines[y_bucket] = []
                lines[y_bucket].append((x, text, i))

            sorted_lines = sorted(lines.items(), key=lambda kv: kv[0])

            # DEBUG: log every line OCR found so we can diagnose issues
            logger.info(f"=== OCR RAW LINES from {Path(image_path).name} ===")
            for y_bucket, words in sorted_lines:
                words_sorted = sorted(words, key=lambda w: w[0])
                line_text = " ".join(w[1] for w in words_sorted)
                logger.info(f"  Y={y_bucket:4d}: [{line_text}]")
            logger.info("=== END OCR LINES ===")

            # --- GUARD: Detect if "Edit rooms" dialog is open ---
            # If we see edit-mode UI strings, the panel is in edit mode — skip entirely
            all_ocr_text = " ".join(data['text']).lower()
            edit_mode_signals = ["cancel changes", "type guest name", "drag it", "timer", "unassigned"]
            if sum(1 for sig in edit_mode_signals if sig in all_ocr_text) >= 2:
                logger.warning("Edit rooms dialog detected — skipping this scan to avoid noise")
                return {}

            # --- GUARD: Detect if a toast/notification is overlapping the panel ---
            # When participants join/leave, Google Meet shows toast notifications
            # ("Pavan joined", "Visitors are in this meeting") that overlay the panel
            # and corrupt OCR — producing garbage names like "Pavan So Sri Harsha"
            # or fake room names like "Jom". Skip and retry; toasts clear in seconds.
            toast_signals = ["outside", "visitors are", "people list to see", "rein session", "are in session"]
            if any(sig in all_ocr_text for sig in toast_signals):
                logger.warning("Toast/notification overlay detected — skipping scan, will retry next cycle")
                return {}

            # ---- PASS 1: Find room headers ----
            room_headers = []
            breakout_counter = 0  # counts "Breakout Join" lines to name them sequentially

            for y_bucket, words in sorted_lines:
                words.sort(key=lambda w: w[0])
                line_text = " ".join(w[1] for w in words).strip()
                line_text_lower = line_text.lower()

                # Skip the panel title line "Breakout rooms" at the very top
                if "breakout" in line_text_lower and "rooms" in line_text_lower and y_bucket < 400:
                    continue

                # "Main call" header
                if "main" in line_text_lower and "call" in line_text_lower:
                    room_headers.append((y_bucket, "Main call"))
                    continue

                non_ui_words = [w[1] for w in words if w[1].lower() not in UI_SKIP and w[1].lower() != "join"]
                has_join = any(w[1].lower() == "join" for w in words)
                has_breakout = "breakout" in line_text_lower

                # Room header with Join button — e.g. "Breakout 1 Join" or just "Breakout Join"
                if has_join and (non_ui_words or has_breakout):
                    if has_breakout:
                        # Try to extract number after "Breakout" e.g. "1", "2"
                        num_match = re.search(r'breakout\s*(\d+)', line_text_lower)
                        if num_match:
                            room_name = f"Breakout {num_match.group(1)}"
                        else:
                            # OCR missed the number — assign sequentially
                            breakout_counter += 1
                            room_name = f"Breakout {breakout_counter}"
                    else:
                        room_name = " ".join(non_ui_words).strip()
                        room_name = re.sub(r"^[^a-zA-Z0-9']+", "", room_name).strip()
                    if room_name:
                        room_headers.append((y_bucket, room_name))
                    continue

                # Room header WITHOUT Join button (participant already inside room)
                line_has_room = "room" in line_text_lower or "breakout" in line_text_lower
                line_word_count = len([w for w in words if w[1].lower() not in UI_SKIP])
                if line_has_room and line_word_count <= 3:
                    room_name = " ".join(non_ui_words).strip()
                    room_name = re.sub(r"^[^a-zA-Z0-9']+", "", room_name).strip()
                    if room_name and room_name.lower() not in ("rooms", "breakout rooms", "edit rooms", "close rooms", "breakout"):
                        room_headers.append((y_bucket, room_name))
                    continue

            # Ensure Main call always exists
            if not any(r[1] == "Main call" for r in room_headers):
                room_headers.insert(0, (0, "Main call"))

            room_headers.sort(key=lambda r: r[0])
            logger.info(f"=== ROOM HEADERS FOUND: {room_headers} ===")
            header_y_set = set(h[0] for h in room_headers)

            room_attendance = {rname: {} for _, rname in room_headers}

            # ---- PASS 2: Assign participants to rooms ----
            for y_bucket, words in sorted_lines:
                words.sort(key=lambda w: w[0])
                line_text = " ".join(w[1] for w in words).strip()
                line_text_lower = line_text.lower()

                # Skip UI-only lines
                if all(w[1].lower() in UI_SKIP for w in words):
                    continue

                # Skip room header lines
                is_header = (
                    y_bucket in header_y_set or
                    ("main" in line_text_lower and "call" in line_text_lower) or
                    any(w[1].lower() == "join" for w in words)
                )
                if is_header:
                    continue

                # Assign to room whose header Y is closest above this line
                assigned_room = "Main call"
                for (header_y, room_name) in room_headers:
                    if header_y <= y_bucket:
                        assigned_room = room_name
                    else:
                        break
                if assigned_room not in room_attendance:
                    room_attendance[assigned_room] = {}

                # --- SPLIT SAME-ROW PILL CHIPS ---
                # Multiple participants in same room appear side-by-side on the same Y.
                # Detect X-gaps > 100px (2x-scaled OCR coords) between words to split into separate names.
                # IMPORTANT: avatar tokens (1-2 char noise like "Pe", "So", "Po") sit in
                # the gap between chips and must be skipped when computing gap distances.
                # Otherwise the inter-chip gap is split into two smaller gaps, both below
                # the threshold, and chips never split. Fix: track the last non-noise word
                # as the gap anchor instead of the immediate previous word.
                PILL_GAP = 100  # px gap in 2x-scaled OCR coords (= ~50px on screen)
                groups = []
                current_group = [words[0]]
                last_real_w = words[0]  # last non-noise word, used as gap anchor
                for curr_w in words[1:]:
                    curr_text = curr_w[1].strip()
                    curr_is_noise = len(curr_text) <= 2 or not curr_text.isalpha()
                    prev_i = last_real_w[2]
                    prev_end = (data['left'][prev_i] + data['width'][prev_i]) if prev_i < len(data['width']) else last_real_w[0] + 40
                    gap = curr_w[0] - prev_end
                    if not curr_is_noise and gap > PILL_GAP:
                        groups.append(current_group)
                        current_group = [curr_w]
                        last_real_w = curr_w
                    else:
                        current_group.append(curr_w)
                        if not curr_is_noise:
                            last_real_w = curr_w
                groups.append(current_group)

                noise_phrases = [
                    "cancel", "changes", "drag", "type", "guest", "move",
                    "visitor", "isitor", "joined", "organization", "mywoc",
                    "unassigned", "timer", "clear", "here",
                    "side ", "ype ", "ame or", "in main", "main call"
                ]
                # Also block names that are clearly partial words (end-fragments of longer names)
                # These appear when OCR splits a pill chip name across lines
                partial_word_pattern = re.compile(r'^[a-z]')  # starts with lowercase = fragment

                for group in groups:
                    name_parts = [w[1] for w in group if w[1].lower() not in UI_SKIP]
                    if not name_parts:
                        continue
                    participant_name = self.clean_name(" ".join(name_parts))

                    if len(participant_name) < 3:
                        continue
                    if sum(1 for c in participant_name if c.isalpha()) < 4:
                        continue
                    if len(participant_name.split()) == 1 and len(participant_name) < 4:
                        continue
                    name_lower = participant_name.lower()
                    if any(phrase in name_lower for phrase in noise_phrases):
                        continue
                    # Block fragments starting with lowercase (OCR split of longer name)
                    if partial_word_pattern.match(participant_name):
                        continue
                    if re.search(r'\b(GB|MB|KB|TB|GHz|MHz|Wi|Fi|NY)\b', participant_name):
                        continue
                    if re.search(r'^[^a-zA-Z]', participant_name):
                        continue
                    if participant_name.lower() == YOUR_NAME.lower():
                        continue

                    # Dot detection for this group
                    i_idx = group[0][2]
                    last_idx = group[-1][2]
                    name_x = data['left'][i_idx] // 2
                    name_y = data['top'][i_idx] // 2
                    name_h = data['height'][i_idx] // 2
                    name_w_end = (data['left'][last_idx] + data['width'][last_idx]) // 2
                    row_h = max(name_h, 40)
                    roi_x1 = max(0, name_x - 200)
                    roi_y1 = max(0, name_y - 15)
                    roi_x2 = min(img.shape[1], name_w_end + 20)
                    roi_y2 = min(img.shape[0], name_y + row_h + 15)
                    roi = img[roi_y1:roi_y2, roi_x1:roi_x2]
                    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', participant_name)[:30]
                    roi_path = self.screenshot_dir / f"temp_roi_{safe_name}_{i_idx}.png"
                    cv2.imwrite(str(roi_path), roi)
                    has_dot = has_green_dot(str(roi_path))
                    if roi_path.exists():
                        os.remove(roi_path)

                    if participant_name not in room_attendance[assigned_room]:
                        room_attendance[assigned_room][participant_name] = has_dot
                        status = "PRESENT" if has_dot else "ABSENT"
                        logger.info(f"  [{assigned_room}] {participant_name} -> {status}")

            return room_attendance

        except ImportError:
            logger.error("pytesseract not installed.")
            return {}
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            import traceback
            traceback.print_exc()
            return {}

    def merge_attendance_data(self, all_screenshots: List[str]) -> Dict[str, Dict[str, bool]]:
        """
        Merge OCR results from multiple scroll-position screenshots.
        Strategy: first screenshot establishes the canonical room list.
        Subsequent screenshots can ADD participants to existing rooms,
        but cannot CREATE new room names (prevents scroll-induced duplicates
        like Breakout 3/4 appearing when the panel is just scrolled down).
        """
        # --- GUARD: Detect layout change mid-scan ---
        # Google Meet switches between panel-only layout (~510px wide screenshot)
        # and full-video layout (~1920px wide screenshot) when someone joins or
        # leaves silently (no toast notification). If this happens between
        # position_0 and position_1 screenshots, the two crops are from different
        # layouts and mixing them produces wrong room assignments.
        # Detection: the saved screenshot width = panel width after cropping.
        # A difference >100px between screenshots means the layout changed.
        if len(all_screenshots) > 1:
            widths = []
            for sp in all_screenshots:
                try:
                    widths.append(Image.open(sp).size[0])
                except Exception:
                    pass
            if widths and (max(widths) - min(widths)) > 100:
                logger.warning(f"Layout change detected mid-scan (widths: {widths}) — skipping, will retry next cycle")
                return {}

        merged = {}
        canonical_rooms = None  # set on first valid screenshot

        for screenshot_path in all_screenshots:
            room_data = self.extract_room_attendance(screenshot_path)
            if not room_data:
                continue

            if canonical_rooms is None:
                # First screenshot — establish canonical room list
                canonical_rooms = set(room_data.keys())
                merged = {room: dict(participants) for room, participants in room_data.items()}
                logger.info(f"Canonical rooms established: {sorted(canonical_rooms)}")
            else:
                # Subsequent screenshots — only add participants to KNOWN rooms
                for room_name, participants in room_data.items():
                    if room_name in canonical_rooms:
                        for name, has_dot in participants.items():
                            if name in merged[room_name]:
                                merged[room_name][name] = merged[room_name][name] or has_dot
                            else:
                                merged[room_name][name] = has_dot
                    # else: ignore rooms not seen in first screenshot (scroll duplicates)

        return merged

    def update_attendance(self, room_attendance: Dict[str, Dict[str, bool]]):
        now = datetime.now()
        with self.lock:
            for room_name, participants in room_attendance.items():
                if room_name not in self.rooms:
                    self.rooms[room_name] = {'present': set(), 'last_seen': {}, 'sessions': []}

                room_data = self.rooms[room_name]

                for name, has_dot in participants.items():
                    # A participant appearing in the breakout rooms panel means they ARE present.
                    # The dot (yellow/green) is a bonus signal — but even without it,
                    # if OCR found their name in the panel, they are in the meeting.
                    is_present = True  # visible in panel = present

                    if is_present and name not in room_data['present']:
                        dot_status = "dot=YES" if has_dot else "dot=NO (still counted)"
                        logger.info(f"✓ [{room_name}] {name} JOINED ({dot_status})")
                        session_num = len([s for s in room_data['sessions'] if s['Name'] == name]) + 1
                        room_data['sessions'].append({
                            'Name': name, 'Join_Time': now,
                            'Leave_Time': None, 'Session_Number': session_num
                        })
                        room_data['present'].add(name)
                        room_data['last_seen'][name] = now
                    elif is_present and name in room_data['present']:
                        room_data['last_seen'][name] = now

                # Mark left: anyone we previously saw who is no longer in the panel
                for name in list(room_data['present']):
                    if name not in participants:
                        leave_time = now
                        join_time = room_data['last_seen'].get(name, now)
                        duration = (leave_time - join_time).total_seconds() / 60
                        logger.info(f"✗ [{room_name}] {name} LEFT (Duration: {duration:.1f} min)")
                        for s in reversed(room_data['sessions']):
                            if s['Name'] == name and s['Leave_Time'] is None:
                                s['Leave_Time'] = leave_time
                                break
                        room_data['present'].discard(name)

    def is_panel_open(self) -> bool:
        try:
            result = self.driver.execute_script("""
                const els = Array.from(document.querySelectorAll('div, span, h2, h3'));
                for (let el of els) {
                    const text = (el.textContent || '').trim().toLowerCase();
                    if (text === 'breakout rooms' || text === 'main call') {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) return true;
                    }
                }
                return false;
            """)
            return bool(result)
        except Exception:
            return False

    def track(self):
        logger.info("Starting breakout room attendance tracking...")

        if not self.open_breakout_rooms_panel():
            logger.error("Failed to open breakout rooms panel. Please open it manually.")
            input("Open Breakout Rooms panel manually, then press ENTER...")

        while not self.stop_event.is_set():
            try:
                logger.info("=== Starting new scan ===")

                if not self.is_panel_open():
                    logger.info("Breakout rooms panel is closed - reopening...")
                    if not self.open_breakout_rooms_panel():
                        logger.warning("Could not reopen panel, skipping scan")
                        time.sleep(10)
                        continue
                    time.sleep(2)

                screenshots = self.scroll_and_capture_panel()
                room_attendance = self.merge_attendance_data(screenshots)

                if room_attendance:
                    total = sum(len(p) for p in room_attendance.values())
                    logger.info(f"Detected {len(room_attendance)} room(s), {total} participant(s)")
                    self.update_attendance(room_attendance)
                else:
                    logger.warning("No attendance data detected")
                    try:
                        self.open_breakout_rooms_panel()
                    except Exception:
                        pass

                logger.info(f"Waiting {CHECK_INTERVAL} seconds until next scan...")
                time.sleep(CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"Tracking error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(10)

        self.finalize_all_sessions()
        self.save_all_reports()

    def finalize_all_sessions(self):
        now = datetime.now()
        with self.lock:
            for room_data in self.rooms.values():
                for s in room_data['sessions']:
                    if s['Leave_Time'] is None:
                        s['Leave_Time'] = now

    def save_all_reports(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        all_data = []

        for room_name, room_data in self.rooms.items():
            for s in room_data['sessions']:
                duration = (s['Leave_Time'] - s['Join_Time']).total_seconds() / 60 if s['Leave_Time'] else 0
                all_data.append({
                    "Room": room_name,
                    "Name": s['Name'],
                    "Join_Time": s['Join_Time'].strftime("%Y-%m-%d %H:%M:%S"),
                    "Leave_Time": s['Leave_Time'].strftime("%Y-%m-%d %H:%M:%S") if s['Leave_Time'] else "",
                    "Duration_Minutes": round(duration, 2),
                    "Date": s['Join_Time'].strftime("%Y-%m-%d")
                })

        if all_data:
            df = pd.DataFrame(all_data)
            combined_file = OUTPUT_DIR / f"ATTENDANCE_ALL_ROOMS_{timestamp}.csv"
            df.to_csv(combined_file, index=False, encoding='utf-8-sig')

            logger.info(f"\n{'=' * 70}")
            logger.info("FINAL ATTENDANCE REPORT - ALL ROOMS")
            logger.info(f"{'=' * 70}")
            logger.info(f"\n{df.to_string(index=False)}")
            logger.info(f"\n📊 Combined report saved: {combined_file}")

            for room_name in self.rooms.keys():
                room_df = df[df['Room'] == room_name]
                if not room_df.empty:
                    safe_room_name = room_name.replace(" ", "_").replace("/", "_").replace("'", "")
                    room_file = OUTPUT_DIR / f"ATTENDANCE_{safe_room_name}_{timestamp}.csv"
                    room_df.to_csv(room_file, index=False, encoding='utf-8-sig')
                    logger.info(f"📄 {room_name} report saved: {room_file}")

            logger.info(f"\n{'=' * 70}")
            logger.info("SUMMARY STATISTICS")
            logger.info(f"{'=' * 70}")
            logger.info(f"Total Participants: {df['Name'].nunique()}")
            logger.info(f"Total Sessions: {len(df)}")
            logger.info(f"Average Duration: {df['Duration_Minutes'].mean():.2f} minutes")
            logger.info(f"Total Rooms: {df['Room'].nunique()}")
            logger.info(f"{'=' * 70}\n")
        else:
            logger.warning("No attendance data to save!")


# ============================================================================
# MAIN TRACKER
# ============================================================================
class MeetTracker:
    def __init__(self):
        self.driver = None
        self.tracker = None
        self.stop_event = threading.Event()

    def setup_browser(self):
        options = uc.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        print("Starting Chrome...")
        CHROME_VERSION = 147

        self.driver = None
        for i, attempt in enumerate([
            lambda: uc.Chrome(options=options, version_main=CHROME_VERSION),
            lambda: uc.Chrome(options=options),
        ]):
            try:
                result = attempt()
                if result:
                    self.driver = result
                    print(f"Chrome started successfully (attempt {i+1})")
                    break
            except Exception as e:
                print(f"Attempt {i+1} failed: {e}")
                time.sleep(2)

        if self.driver is None:
            print("CRITICAL ERROR: Could not start Chrome.")
            sys.exit(1)

        time.sleep(3)
        try:
            self.driver.get("https://meet.google.com/")
            time.sleep(2)
        except Exception as e:
            print(f"Warning: {e}")

        print("\n" + "=" * 70)
        print("IMPORTANT: MANUAL LOGIN REQUIRED")
        print("=" * 70)
        print("Please log in with the host Google account in the browser.")
        print("\n1. Log into the Google account")
        print("2. Make sure you can see meet.google.com")
        print("3. Come back here and press ENTER")
        print("=" * 70)
        input("\nPress ENTER after you have logged in...")

        time.sleep(2)
        try:
            if "meet.google.com" in self.driver.current_url:
                print("Login successful!")
            else:
                input("Warning: Check browser. Press ENTER to continue...")
        except Exception:
            input("Could not verify login. Press ENTER to continue...")

    def reconnect_window(self):
        try:
            handles = self.driver.window_handles
            if handles:
                self.driver.switch_to.window(handles[-1])
                print("Reconnected to existing Chrome window")
                return True
        except Exception:
            pass
        return False

    def run(self):
        self.setup_browser()

        url = input("\nPaste MAIN MEETING LINK: ").strip()
        try:
            self.driver.get(url)
        except Exception:
            print("Window lost, attempting to reconnect...")
            if self.reconnect_window():
                try:
                    self.driver.get(url)
                except Exception:
                    print(f"Please manually paste this link in Chrome: {url}")
                    input("Press ENTER once you are on the meeting page...")
            else:
                print(f"Please manually paste this link in Chrome: {url}")
                input("Press ENTER once you are on the meeting page...")

        time.sleep(5)

        print("\n" + "=" * 70)
        print("JOIN THE MEETING")
        print("=" * 70)
        input("1. Click 'Ask to join' or 'Join now'\n2. Turn OFF mic/camera\n3. Press ENTER...")

        print("\n" + "=" * 70)
        print("SETUP BREAKOUT ROOMS")
        print("=" * 70)
        print("IMPORTANT: Create your breakout rooms if not already created")
        input("Press ENTER when breakout rooms are ready...")

        self.tracker = BreakoutRoomTracker(self.driver, self.stop_event)

        print("\n" + "=" * 70)
        print("STARTING ATTENDANCE TRACKING")
        print("=" * 70)
        print(f"Checking every {CHECK_INTERVAL} seconds")
        print("Tracking from: Activities -> Breakout Rooms panel")
        print("Press Ctrl+C to stop and save attendance\n")

        tracking_thread = threading.Thread(target=self.tracker.track)
        tracking_thread.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\nStopping and saving attendance...")
            self.stop_event.set()
            tracking_thread.join()
            try:
                self.driver.quit()
            except Exception:
                pass
            print("\nDone! Check 'attendance_logs' folder for reports")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("Google Meet Breakout Room Attendance Tracker 2025")
    print("=" * 70)
    print("\nREQUIREMENTS:")
    print("pip install opencv-python pytesseract pillow pandas undetected-chromedriver")
    print("Download Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki")
    print("=" * 70 + "\n")

    MeetTracker().run()
