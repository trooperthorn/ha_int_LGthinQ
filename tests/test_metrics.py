"""Replay monitoring transitions, restarts, duplicates and failure boundaries."""
from datetime import datetime, timedelta, timezone
import copy
import unittest
import client_loader
from custom_components.lg_thinq_extended.metrics import Observations, minutes, progress, capability_digest

class MetricTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 23, 17, 3, 30, tzinfo=timezone.utc)
        self.history = Observations()

    def test_logged_eighteen_second_door_interval_and_duplicate(self):
        h = self.history
        h.observe({"main_door_state": "close"}, self.now)
        h.observe({"main_door_state": "open"}, self.now+timedelta(seconds=6.920))
        h.observe({"main_door_state": "open"}, self.now+timedelta(seconds=12))
        h.observe({"main_door_state": "close"}, self.now+timedelta(seconds=24.919))
        self.assertEqual(h.total(self.now, "main_openings"), 1)
        self.assertAlmostEqual(h.total(self.now, "main_door_open_seconds"), 17.999)
        self.assertAlmostEqual(h.values["main_last_open_seconds"], 17.999)

    def test_midnight_splits_duration(self):
        before = self.now.replace(hour=23, minute=59, second=50)
        after = before+timedelta(seconds=30)
        self.history.observe({"main_door_state": "open"}, before)
        self.history.observe({"main_door_state": "close"}, after)
        self.assertEqual(self.history.total(before, "main_door_open_seconds"), 10)
        self.assertEqual(self.history.total(after, "main_door_open_seconds"), 20)

    def test_restart_preserves_counts_without_inventing_duration(self):
        h = self.history
        h.observe({"main_current_state": "initial"}, self.now)
        h.observe({"main_current_state": "running"}, self.now+timedelta(seconds=1))
        h.advance(self.now+timedelta(seconds=11))
        restored = Observations(copy.deepcopy(h.saved))
        restored.observe({"main_current_state": "end"}, self.now+timedelta(hours=2))
        self.assertEqual(restored.total(self.now, "main_washing_seconds"), 10)
        self.assertIsNone(restored.values.get("main_last_cycle_seconds"))
        self.assertEqual(restored.total(self.now, "main_completed_cycles"), 0)

    def test_disconnect_gap_is_excluded(self):
        h = self.history
        h.observe({"main_current_state": "drying"}, self.now)
        h.advance(self.now+timedelta(seconds=10))
        h.gap()
        h.advance(self.now+timedelta(hours=2))
        self.assertIsNone(h.duration("main_current_state", self.now, {"drying"}))
        h.observe({"main_current_state": "drying"}, self.now+timedelta(hours=3))
        self.assertEqual(h.total(self.now, "main_drying_seconds"), 10)

    def test_combined_cycle_counted_once_and_stop_is_not_complete(self):
        h = self.history
        for offset, state in enumerate(["initial", "running", "pause", "drying", "end", "end"]):
            h.observe({"main_current_state": state}, self.now+timedelta(minutes=offset))
        self.assertEqual(h.total(self.now, "main_completed_cycles"), 1)
        self.assertEqual(h.values["main_last_cycle_seconds"], 180)
        h.notification("DRYING_IS_COMPLETE", self.now+timedelta(minutes=6))
        self.assertEqual(h.total(self.now, "main_completed_cycles"), 1)
        for offset, state in enumerate(["running", "power_off"]):
            h.observe({"main_current_state": state}, self.now+timedelta(minutes=10+offset))
        self.assertEqual(h.total(self.now, "main_completed_cycles"), 1)

    def test_preheat_only_completed_transition_gets_duration(self):
        h = self.history
        h.observe({"upper_current_state": "preheating"}, self.now)
        h.observe({"upper_current_state": "cooking_in_progress"}, self.now+timedelta(minutes=8))
        self.assertEqual(h.values["upper_last_preheat_seconds"], 480)
        h.observe({"upper_current_state": "initial"}, self.now+timedelta(minutes=9))
        self.assertNotIn("upper_last_cooking_seconds", h.values)

    def test_logged_timer_progress_and_long_duration(self):
        self.assertEqual(minutes({"main_remain_hour": 1, "main_remain_minute": 18}, "main_", "remain"), 78)
        self.assertEqual(minutes({"main_total_hour": 30, "main_total_minute": 0}, "main_", "total"), 1800)
        self.assertEqual(progress("drying", 78, 96), 18.8)
        for state, remain, total in [("power_off", 0, 96), ("running", 100, 90), ("running", 1, 0)]:
            self.assertIsNone(progress(state, remain, total))

    def test_error_duplicates_and_cycle_counter_reset(self):
        h = self.history
        h.observe({"main_error": "water_drain_error", "main_cycle_count": 23}, self.now)
        h.observe({"main_error": "water_drain_error", "main_cycle_count": 24}, self.now+timedelta(minutes=2))
        self.assertEqual(h.total(self.now, "errors"), 1)
        self.assertEqual(h.total(self.now, "main_cycle_count_increments"), 1)
        h.observe({"main_cycle_count": 0}, self.now+timedelta(minutes=3))
        self.assertIn("main_cycle_count_reset", h.values)
        self.assertEqual(h.total(self.now, "main_cycle_count_increments"), 1)

    def test_capability_hash_ignores_order_but_detects_new_value(self):
        self.assertEqual(capability_digest({"r": ["A", "B"]}), capability_digest({"r": ["B", "A"]}))
        self.assertNotEqual(capability_digest({"r": ["A", "B"]}), capability_digest({"r": ["A", "C"]}))
