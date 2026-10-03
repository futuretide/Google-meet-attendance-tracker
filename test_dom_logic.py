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


if __name__ == "__main__":
    unittest.main()
