import unittest
from datetime import datetime
from unittest.mock import patch

from hdu_seat.client import BEIJING_TZ, HDUClientError
from hdu_seat.hunter import Attempt
from hdu_seat.server import (
    SeatWebServer,
    dict_to_settings,
    scheduled_start_timestamp,
    settings_to_dict,
    settings_to_nested,
)


class ServerConfigTests(unittest.TestCase):
    def test_roundtrip_preserves_core_fields(self):
        flat = {
            "cookie": "sid=abc",
            "category_id": "591",
            "content_id": "3",
            "date": None,
            "start_time": "08:00",
            "duration_hours": "4",
            "num": "1",
            "seat_ids": ["001", "002"],
            "keywords": ["window"],
            "poll_interval": "3",
            "schedule_at": "2099-09-04T07:59:30",
        }
        settings = dict_to_settings(flat)
        out = settings_to_dict(settings)
        self.assertEqual(out["category_id"], 591)
        self.assertEqual(out["content_id"], 3)
        self.assertEqual(out["seat_ids"], ["001", "002"])
        self.assertEqual(out["duration_hours"], 4.0)
        self.assertEqual(out["schedule_at"], "2099-09-04T07:59:30")

    def test_nested_has_config_shape(self):
        settings = dict_to_settings({"cookie": "sid=abc", "category_id": 591, "content_id": 3})
        nested = settings_to_nested(settings)
        self.assertEqual(nested["space_category"]["category_id"], 591)
        self.assertEqual(nested["space_category"]["content_id"], 3)
        self.assertIn("booking", nested)
        self.assertIn("rule", nested)
        self.assertEqual(nested["schedule_at"], settings.schedule_at)

    def test_numeric_fallbacks(self):
        settings = dict_to_settings({"cookie": "sid=abc", "category_id": "bad", "content_id": "bad"})
        self.assertEqual(settings.space_category.category_id, 591)
        self.assertEqual(settings.space_category.content_id, 3)

    def test_legacy_json_cookie_is_unwrapped(self):
        settings = dict_to_settings({"cookie": '{"cookie": "sid=abc; uid=1"}'})
        self.assertEqual(settings.cookie, "sid=abc; uid=1")

    def test_boolean_and_floor_are_converted(self):
        settings = dict_to_settings({
            "cookie": "sid=abc",
            "preferred_floor": "3",
            "avoid_near_door": "false",
        })
        self.assertEqual(settings.rule.preferred_floor, 3)
        self.assertFalse(settings.rule.avoid_near_door)

    def test_string_false_is_not_truthy(self):
        self.assertFalse(dict_to_settings({"cookie": "sid=abc", "avoid_near_door": "0"}).rule.avoid_near_door)

    def test_live_snapshot_keeps_only_currently_available_seats(self):
        server = SeatWebServer("missing-test-config.json")
        server._update_seats([
            {"id": "1", "title": "001", "area": "二楼", "available": True},
            {"id": "2", "title": "002", "area": "二楼", "available": False},
        ])

        snapshot = server.snapshot()
        self.assertEqual([seat["id"] for seat in snapshot["seats"]], ["1"])
        self.assertEqual(snapshot["seat_revision"], 1)
        self.assertIsNotNone(snapshot["seat_updated_at"])

    def test_scheduled_start_is_interpreted_as_beijing_time(self):
        settings = dict_to_settings({"cookie": "sid=abc", "schedule_at": "2099-09-04T07:59:30"})
        timestamp = scheduled_start_timestamp(settings, now=0)
        expected = datetime(2099, 9, 4, 7, 59, 30, tzinfo=BEIJING_TZ).timestamp()
        self.assertEqual(timestamp, expected)

    def test_past_scheduled_start_is_rejected(self):
        settings = dict_to_settings({"cookie": "sid=abc", "schedule_at": "2000-01-01T00:00"})
        with self.assertRaisesRegex(HDUClientError, "已过去"):
            scheduled_start_timestamp(settings)

    def test_waiting_schedule_can_be_cancelled(self):
        server = SeatWebServer("missing-test-config.json")
        server._persist = lambda _: None
        result = server.start({"cookie": "sid=abc", "schedule_at": "2099-09-04T07:59:30"})
        self.assertTrue(result["waiting"])
        self.assertTrue(server.snapshot()["waiting"])

        server.stop()
        server.worker.join(timeout=1)
        snapshot = server.snapshot()
        self.assertFalse(snapshot["running"])
        self.assertFalse(snapshot["waiting"])
        self.assertEqual(snapshot["last_result"]["message"], "已取消定时抢座")

    def test_running_loop_reloads_saved_seat_selection_each_attempt(self):
        server = SeatWebServer("missing-test-config.json")
        server._persist = lambda _: None
        initial = dict_to_settings({
            "cookie": "sid=abc",
            "seat_ids": ["old-seat"],
            "poll_interval": 0,
            "max_attempts": 2,
        })
        server.settings = initial
        server.running = True
        seen = []

        class FakeHunter:
            def __init__(self, settings, on_seats=None):
                seen.append(list(settings.rule.seat_ids))

            def run_once(self, dry_run=False):
                if len(seen) == 1:
                    updated = settings_to_dict(initial)
                    updated["seat_ids"] = ["new-seat"]
                    server.save_config(updated)
                    return Attempt("now", "empty", "retry")
                return Attempt("now", "reserved", "ok", {"id": "new-seat"})

        with patch("hdu_seat.server.SeatHunter", FakeHunter):
            server._run_loop(initial)

        self.assertEqual(seen, [["old-seat"], ["new-seat"]])
        self.assertEqual(server.snapshot()["last_result"]["status"], "reserved")


if __name__ == "__main__":
    unittest.main()
