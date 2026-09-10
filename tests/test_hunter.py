import unittest

from hdu_seat.config import Settings, SpaceCategory
from hdu_seat.hunter import SeatHunter


class FakeClient:
    def __init__(self):
        self.calls = 0

    def seats(self):
        self.calls += 1
        return [{"id": "A-01", "title": "001", "available": self.calls >= 2}]

    def reserve(self, seat):
        return {"CODE": "ok", "DATA": {"result": "success", "seat": seat["id"]}}


class HunterTests(unittest.TestCase):
    def _settings(self, **kwargs):
        defaults = dict(base_url="https://example.test", cookie="sid=x", space_category=SpaceCategory(591, 3))
        defaults.update(kwargs)
        return Settings(**defaults)

    def test_retries_until_a_seat_is_available(self):
        settings = self._settings(max_attempts=3, poll_interval=0)
        client = FakeClient()
        result = SeatHunter(settings, client, sleeper=lambda _: None).run()
        self.assertEqual(result.status, "reserved")
        self.assertEqual(client.calls, 2)

    def test_run_stops_after_success(self):
        settings = self._settings(max_attempts=5, poll_interval=0)
        client = FakeClient()
        result = SeatHunter(settings, client, sleeper=lambda _: None).run(stop_on_success=True)
        self.assertEqual(result.status, "reserved")
        self.assertEqual(client.calls, 2)

    def test_dry_run_never_reserves(self):
        settings = self._settings(max_attempts=1)
        client = FakeClient()
        client.seats = lambda: [{"id": "A-01", "available": True}]
        result = SeatHunter(settings, client, sleeper=lambda _: None).run(dry_run=True)
        self.assertEqual(result.status, "dry-run")

    def test_empty_result_explains_that_selected_seat_will_be_retried(self):
        settings = self._settings()
        settings.rule.seat_ids = ["001"]
        client = FakeClient()
        client.seats = lambda: [{"id": "A-01", "title": "001", "available": False}]

        result = SeatHunter(settings, client, sleeper=lambda _: None).run_once()

        self.assertEqual(result.status, "empty")
        self.assertIn("目标座位", result.message)
        self.assertIn("继续重试", result.message)

    def test_filters_explain_when_other_seats_are_available(self):
        settings = self._settings()
        settings.rule.seat_ids = ["999"]
        client = FakeClient()
        client.seats = lambda: [{"id": "A-01", "title": "001", "available": True}]

        result = SeatHunter(settings, client, sleeper=lambda _: None).run_once()

        self.assertIn("当前有 1 个可约座位", result.message)
        self.assertIn("筛选条件", result.message)

    def test_unavailable_target_reports_its_area(self):
        settings = self._settings()
        settings.rule.seat_ids = ["35"]
        settings.rule.preferred_floor = 4
        client = FakeClient()
        client.seats = lambda: [
            {"id": "62001", "title": "35", "floor": "6", "area": "六楼北区", "available": True},
            {"id": "62002", "title": "35", "floor": "4", "area": "四楼西区", "available": False},
        ]

        result = SeatHunter(settings, client, sleeper=lambda _: None).run_once()

        self.assertIn("四楼西区", result.message)
        self.assertIn("已占用或关闭", result.message)

    def test_should_stop_breaks_loop(self):
        settings = self._settings(max_attempts=5, poll_interval=0)
        client = FakeClient()
        client.seats = lambda: [{"id": "A-01", "available": False}]
        stop = {"value": False}

        def should_stop():
            return stop["value"]

        hunter = SeatHunter(settings, client, sleeper=lambda _: None, should_stop=should_stop)
        # 第一次尝试后手动置为停止
        orig_run_once = hunter.run_once
        calls = {"n": 0}

        def run_once(dry_run=False):
            calls["n"] += 1
            if calls["n"] >= 2:
                stop["value"] = True
            return orig_run_once(dry_run=dry_run)

        hunter.run_once = run_once
        hunter.run()
        self.assertTrue(calls["n"] <= 2)
        self.assertEqual(hunter.history[-1].status, "stopped")


if __name__ == "__main__":
    unittest.main()
