"""Offline tests for the pure logic in GMA_tracker_dom.py (no browser needed)."""
import unittest
from datetime import datetime, timedelta

from GMA_tracker_dom import AttendanceEngine, normalize_name, name_key


class NormalizeTests(unittest.TestCase):
    def test_suffixes_and_prefixes(self):
        self.assertEqual(normalize_name("Jane Smith (You)"), "Jane Smith")
        self.assertEqual(normalize_name("Jane (Host) (You)"), "Jane")
        self.assertEqual(normalize_name("Pin Jane Smith to your main screen"), "Jane Smith")
        self.assertEqual(normalize_name("Jane​  Smith"), "Jane Smith")

    def test_noise_rejected(self):
        for junk in ("", "Mute", "Host", "12", "•", "Breakout rooms"):
            self.assertEqual(normalize_name(junk), "", junk)

    def test_key_case_insensitive(self):
        self.assertEqual(name_key("jane  SMITH"), name_key("Jane Smith"))


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2025, 3, 15, 10, 0, 0)
        self.e = AttendanceEngine(grace_scans=2, your_name="WOC")

    def at(self, m):
        return self.t0 + timedelta(minutes=m)

    def test_join_leave_with_backdated_leave(self):
        self.e.update({"Main Call": ["Jane", "WOC"]}, self.at(0))
        self.e.update({"Main Call": ["Jane"]}, self.at(5))
        self.e.update({"Main Call": []}, self.at(10))      # miss 1: still present
        self.assertEqual(len(self.e.rooms["Main Call"].present), 1)
        self.e.update({"Main Call": []}, self.at(15))      # miss 2: left, back-dated to 5
        row = self.e.rows()[0]
        self.assertEqual(row["Name"], "Jane")
        self.assertEqual(row["Duration_Minutes"], 5.0)
        self.assertEqual(len(self.e.rows()), 1)            # self excluded

    def test_glitch_does_not_split_session(self):
        self.e.update({"R": ["Bob"]}, self.at(0))
        self.e.update({"R": []}, self.at(5))
        self.e.update({"R": ["Bob"]}, self.at(10))
        self.assertEqual(len(self.e.rows()), 1)

    def test_room_move_and_rejoin(self):
        self.e.update({"Main Call": ["Ann"], "Room 1": []}, self.at(0))
        self.e.update({"Main Call": [], "Room 1": ["Ann"]}, self.at(5))
        self.e.update({"Main Call": [], "Room 1": ["Ann"]}, self.at(10))
        rooms = {r["Room"] for r in self.e.rows()}
        self.assertEqual(rooms, {"Main Call", "Room 1"})
        self.e.finalize(self.at(20))
        self.assertTrue(all(r["Leave_Time"] for r in self.e.rows()))


class NormalizeEdgeTests(unittest.TestCase):
    def test_unicode_and_emoji_preserved(self):
        for n in ("José Núñez", "Zoë", "李雷", "Марина Иванова", "Sam \U0001F338", "O'Brien-Smith Jr."):
            self.assertEqual(normalize_name(n), n)

    def test_whitespace_and_case_variants(self):
        self.assertEqual(normalize_name("  Jane   Smith  "), "Jane Smith")
        self.assertEqual(normalize_name("Jane Smith (Presentation)"), "Jane Smith")
        self.assertEqual(normalize_name("Jane [Host]"), "Jane")
        self.assertEqual(normalize_name("Jane (HOST)"), "Jane")
        self.assertEqual(normalize_name(None), "")

    def test_more_noise(self):
        for junk in ("Pin", "Unmute", "More actions", "Contributors", "Main Call", "...", "3", None):
            self.assertEqual(normalize_name(junk), "", junk)

    def test_name_containing_noise_word_kept(self):
        self.assertEqual(normalize_name("Host Williams"), "Host Williams")
        self.assertEqual(normalize_name("Pin Sharma"), "Pin Sharma")
        self.assertEqual(normalize_name("Mute Ali"), "Mute Ali")
        self.assertEqual(normalize_name("More actions for Ann Lee"), "Ann Lee")
        self.assertEqual(normalize_name("Unpin Ann Lee from your main screen"), "Ann Lee")


class EngineEdgeTests(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2025, 3, 15, 10, 0, 0)
        self.at = lambda m: self.t0 + timedelta(minutes=m)

    def test_grace_one_leaves_immediately(self):
        e = AttendanceEngine(grace_scans=1, your_name="WOC")
        e.update({"R": ["A"]}, self.at(0))
        e.update({"R": []}, self.at(5))
        self.assertEqual(e.rows()[0]["Leave_Time"], "2025-03-15 10:00:00")

    def test_grace_zero_is_clamped_to_one(self):
        self.assertEqual(AttendanceEngine(grace_scans=0).grace, 1)

    def test_rejoin_after_leave_makes_second_session(self):
        e = AttendanceEngine(grace_scans=1, your_name="")
        e.update({"R": ["A"]}, self.at(0))
        e.update({"R": []}, self.at(5))
        e.update({"R": ["A"]}, self.at(10))
        e.finalize(self.at(15))
        rows = e.rows()
        self.assertEqual([r["Duration_Minutes"] for r in rows], [0.0, 5.0])

    def test_self_excluded_case_insensitively_and_with_suffix(self):
        e = AttendanceEngine(your_name="woc")
        e.update({"R": ["WOC (You)", "Bob"]}, self.at(0))
        self.assertEqual([r["Name"] for r in e.rows()], ["Bob"])

    def test_duplicate_names_same_poll_collapse_to_one(self):
        e = AttendanceEngine(your_name="")
        e.update({"R": ["Sam", "sam", "SAM "]}, self.at(0))
        self.assertEqual(len(e.rows()), 1)

    def test_noise_rows_never_become_participants(self):
        e = AttendanceEngine(your_name="")
        e.update({"R": ["Mute", "Host", "7", "Real Person"]}, self.at(0))
        self.assertEqual([r["Name"] for r in e.rows()], ["Real Person"])

    def test_room_appearing_later_and_empty_snapshot_room(self):
        e = AttendanceEngine(your_name="")
        e.update({"Main Call": ["A"]}, self.at(0))
        e.update({"Main Call": ["A"], "Room 1": ["B"]}, self.at(5))
        self.assertEqual({r["Room"] for r in e.rows()}, {"Main Call", "Room 1"})

    def test_finalize_idempotent_and_sets_leave_time(self):
        e = AttendanceEngine(your_name="")
        e.update({"R": ["A"]}, self.at(0))
        e.finalize(self.at(10)); e.finalize(self.at(99))
        self.assertEqual(e.rows()[0]["Duration_Minutes"], 10.0)

    def test_large_roster_100_people_20_scans(self):
        e = AttendanceEngine(your_name="")
        people = [f"Person {i}" for i in range(100)]
        for scan in range(20):
            e.update({"Main Call": people}, self.at(scan))
        e.finalize(self.at(20))
        rows = e.rows()
        self.assertEqual(len(rows), 100)
        self.assertTrue(all(r["Duration_Minutes"] == 20.0 for r in rows))

    def test_concurrent_update_and_rows_threadsafe(self):
        import threading
        e = AttendanceEngine(your_name="")
        def writer():
            for i in range(200):
                e.update({"R": [f"P{i % 7}"]}, self.at(i))
        def reader():
            for _ in range(200):
                e.rows()
        ts = [threading.Thread(target=f) for f in (writer, reader, reader)]
        [t.start() for t in ts]; [t.join() for t in ts]


class ReportTests(unittest.TestCase):
    def test_csv_schema_matches_ocr_tool(self):
        import tempfile, pathlib
        from GMA_tracker_dom import write_reports
        e = AttendanceEngine(your_name="")
        e.update({"Breakout Room 1": ["A"]}, datetime(2025, 3, 15, 10, 0))
        e.finalize(datetime(2025, 3, 15, 10, 30))
        with tempfile.TemporaryDirectory() as d:
            files = write_reports(e.rows(), pathlib.Path(d))
            import pandas as pd
            df = pd.read_csv(files[0])
            self.assertEqual(list(df.columns),
                ["Room", "Name", "Join_Time", "Leave_Time", "Duration_Minutes", "Date"])
            self.assertEqual(len(files), 2)  # combined + one room
            self.assertIn("Breakout_Room_1", files[1].name)

    def test_empty_rows_writes_nothing(self):
        from GMA_tracker_dom import write_reports
        self.assertEqual(write_reports([]), [])


class ScanSafetyTests(unittest.TestCase):
    """A broken scan (panel closed / stale selectors) must never mark people as left."""

    def _tracker(self, reads, opens=True):
        from GMA_tracker_dom import MeetTracker
        t = MeetTracker()
        t.engine = AttendanceEngine(grace_scans=1, your_name="")
        class R:
            def __init__(s): s.i = 0
            def is_open(s): return True
            def open_panel(s): return opens
            def read(s):
                v = reads[min(s.i, len(reads) - 1)]; s.i += 1; return v
        t.reader = R()
        return t

    def test_empty_snapshot_does_not_end_sessions(self):
        t = self._tracker([{"Main Call": ["A", "B"]}, {}, {}, {"Main Call": ["A", "B"]}])
        results = [t.scan_once() for _ in range(4)]
        self.assertEqual(results, [True, False, False, True])
        t.engine.finalize()
        self.assertEqual(len(t.engine.rows()), 2)          # no split sessions

    def test_closed_panel_that_cannot_reopen_is_skipped(self):
        t = self._tracker([{"Main Call": ["A"]}])
        t.reader.is_open = lambda: False
        t.reader.open_panel = lambda: False
        self.assertFalse(t.scan_once())
        self.assertEqual(t.engine.rows(), [])


if __name__ == "__main__":
    unittest.main()
