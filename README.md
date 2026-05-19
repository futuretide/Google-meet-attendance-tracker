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

## Notes

- Requires the host Google account to be logged in
- Works with Chrome (uses undetected-chromedriver to bypass bot detection)
- Tested on Windows with Chrome v147

## Author

**Harsha Sunkavalli**  
MS Computer Science, George Mason University  
[LinkedIn](https://linkedin.com/in/harsha-sunkavalli) | [Email](mailto:smasriharsha@gmail.com)
